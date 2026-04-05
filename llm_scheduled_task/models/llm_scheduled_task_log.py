# -*- coding: utf-8 -*-
from odoo import _, api, fields, models


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
