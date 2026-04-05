# -*- coding: utf-8 -*-
import logging
from datetime import timedelta

from odoo import _, api, fields, models

_logger = logging.getLogger(__name__)

# Sin mensajes nuevos en el hilo durante este tiempo → ejecución colgada (minutos)
_STALE_ACTIVITY_MINUTES = 15
# No cerrar ejecuciones más recientes (minutos) para no competir con el hilo en curso
_MIN_RUNNING_AGE_MINUTES = 3


class LLMScheduledTaskLog(models.Model):
    _name = "llm.scheduled.task.log"
    _description = "Log de Ejecución de Tarea LLM"
    _order = "execution_date desc"
    _rec_name = "display_name"

    task_id = fields.Many2one(
        "llm.scheduled.task",
        string="Tarea",
        required=True,
        ondelete="cascade",
        index=True,
    )
    execution_date = fields.Datetime(
        "Fecha de ejecución",
        default=fields.Datetime.now,
        required=True,
        index=True,
    )
    state = fields.Selection(
        [
            ("running", "Ejecutando"),
            ("success", "Exitoso"),
            ("error", "Error"),
        ],
        string="Estado",
        default="running",
        required=True,
    )
    duration_seconds = fields.Float(
        "Duración (seg)",
        digits=(10, 2),
        readonly=True,
    )
    message_count = fields.Integer(
        "Mensajes generados",
        readonly=True,
        help="Número de mensajes creados en el chat durante esta ejecución.",
    )
    error_message = fields.Text(
        "Detalle del error",
        readonly=True,
    )
    thread_id = fields.Many2one(
        "llm.thread",
        string="Chat de esta ejecución",
        readonly=True,
        ondelete="set null",
        help="Hilo de chat creado solo para esta ejecución (sin mensajes de ejecuciones anteriores).",
    )

    display_name = fields.Char(
        "Nombre",
        compute="_compute_display_name",
        store=False,
    )

    @api.depends("task_id", "execution_date", "state")
    def _compute_display_name(self):
        state_label = {
            "running": "⏳",
            "success": "✅",
            "error": "❌",
        }
        for log in self:
            date_str = ""
            if log.execution_date:
                date_str = log.execution_date.strftime("%d/%m/%Y %H:%M")
            icon = state_label.get(log.state, "")
            task_name = log.task_id.name or ""
            log.display_name = f"{icon} {task_name} — {date_str}"

    def action_view_chat(self):
        """Abre el chat de esta ejecución concreta (no el de otras corridas)."""
        self.ensure_one()
        thread = self.thread_id or self.task_id.thread_id
        if not thread:
            return False
        return {
            "type": "ir.actions.act_window",
            "name": _("Chat: %s") % self.task_id.name,
            "res_model": "llm.thread",
            "res_id": thread.id,
            "view_mode": "form",
            "target": "current",
            "context": {"show_task_threads": True},
        }

    def _finalize_supervised_stale(self, message):
        """Cierra un log en *running* como error con mensaje de supervisión."""
        self.ensure_one()
        if self.state != "running":
            return
        now = fields.Datetime.now()
        start = self.execution_date or now
        duration = max(0.0, (now - start).total_seconds())
        self.sudo().write({
            "state": "error",
            "error_message": message,
            "duration_seconds": duration,
        })
        _logger.warning(
            "Log ejecución id=%s (tarea %s): finalizado por supervisión — %s",
            self.id,
            self.task_id.name,
            message,
        )

    @api.model
    def cron_supervise_stale_running_logs(self):
        """
        Cron: detecta ejecuciones *running* cuyo hilo no tiene actividad reciente
        (mail.message) y las marca como error para desbloquear el estado en la tarea.
        """
        now = fields.Datetime.now()
        min_age = now - timedelta(minutes=_MIN_RUNNING_AGE_MINUTES)
        stale_before = now - timedelta(minutes=_STALE_ACTIVITY_MINUTES)

        running = self.sudo().search([("state", "=", "running")])
        Message = self.env["mail.message"].sudo()

        for log in running:
            if log.execution_date and log.execution_date > min_age:
                continue

            if not log.thread_id:
                log._finalize_supervised_stale(
                    _(
                        "Ejecución cerrada por supervisión: no había hilo de chat asociado."
                    )
                )
                continue

            last_msg = Message.search(
                [
                    ("model", "=", "llm.thread"),
                    ("res_id", "=", log.thread_id.id),
                ],
                order="write_date desc, id desc",
                limit=1,
            )
            last_ts = False
            if last_msg:
                last_ts = last_msg.write_date or last_msg.create_date

            if last_ts and last_ts >= stale_before:
                continue

            log._finalize_supervised_stale(
                _(
                    "Ejecución cerrada por supervisión: sin actividad reciente en el chat "
                    "del hilo de ejecución (ventana de %(min)s min)."
                )
                % {"min": _STALE_ACTIVITY_MINUTES}
            )
