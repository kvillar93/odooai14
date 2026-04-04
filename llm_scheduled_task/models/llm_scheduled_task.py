# -*- coding: utf-8 -*-
import logging
import time as _time

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError

_logger = logging.getLogger(__name__)


class LLMScheduledTask(models.Model):
    _name = "llm.scheduled.task"
    _description = "Tarea Programada LLM"
    _order = "name"
    _inherit = ["mail.thread", "mail.activity.mixin"]

    # ─────────────────────────────────────────────────
    # Campos básicos
    # ─────────────────────────────────────────────────
    name = fields.Char("Nombre", required=True, tracking=True)
    active = fields.Boolean("Activo", default=True)
    state = fields.Selection(
        [("active", "Activo"), ("paused", "Pausado")],
        string="Estado",
        default="active",
        tracking=True,
    )
    task_prompt = fields.Text(
        "Instrucción del LLM",
        required=True,
        help=(
            "Describe qué debe hacer el LLM cada vez que se ejecute la tarea. "
            "Puedes referenciar herramientas (odoo_record_retriever, llm_artifact_builder, etc.) "
            "y solicitar acciones concretas como enviar reportes, verificar registros o notificar.\n\n"
            "Ejemplo: 'Consulta las órdenes de venta pendientes de los últimos 7 días, "
            "genera un resumen y envíalo por correo a ventas@empresa.com'."
        ),
    )
    notes = fields.Text(
        "Notas",
        help="Comentarios o documentación interna sobre el propósito de la tarea.",
    )
    user_id = fields.Many2one(
        "res.users",
        "Propietario",
        default=lambda self: self.env.user,
        required=True,
        tracking=True,
    )

    # ─────────────────────────────────────────────────
    # Configuración del LLM
    # ─────────────────────────────────────────────────
    assistant_id = fields.Many2one(
        "llm.assistant",
        "Asistente",
        tracking=True,
        help="Asistente LLM a usar. Si se configura, define automáticamente el proveedor, modelo y herramientas.",
    )
    provider_id = fields.Many2one(
        "llm.provider",
        "Proveedor LLM",
        tracking=True,
    )
    model_id = fields.Many2one(
        "llm.model",
        "Modelo LLM",
        domain="[('provider_id', '=', provider_id)]",
        tracking=True,
    )
    tool_ids = fields.Many2many(
        "llm.tool",
        string="Herramientas disponibles",
        help="Herramientas que el LLM puede usar durante la ejecución.",
    )

    # ─────────────────────────────────────────────────
    # Programación
    # ─────────────────────────────────────────────────
    interval_number = fields.Integer(
        "Cada",
        default=1,
        required=True,
    )
    interval_type = fields.Selection(
        [
            ("minutes", "Minutos"),
            ("hours", "Horas"),
            ("days", "Días"),
            ("weeks", "Semanas"),
            ("months", "Meses"),
        ],
        string="Unidad",
        default="days",
        required=True,
        tracking=True,
    )
    next_run = fields.Datetime(
        "Primera / próxima ejecución",
        required=True,
        default=fields.Datetime.now,
        help="Fecha y hora de la primera ejecución. Después se repetirá según el intervalo.",
        tracking=True,
    )

    # ─────────────────────────────────────────────────
    # Relaciones técnicas
    # ─────────────────────────────────────────────────
    cron_id = fields.Many2one(
        "ir.cron",
        "Cron Job",
        readonly=True,
        copy=False,
        ondelete="set null",
    )
    thread_id = fields.Many2one(
        "llm.thread",
        "Chat dedicado",
        readonly=True,
        copy=False,
        ondelete="set null",
        help="Chat LLM reutilizado en cada ejecución de la tarea.",
    )

    # ─────────────────────────────────────────────────
    # Estadísticas
    # ─────────────────────────────────────────────────
    log_ids = fields.One2many(
        "llm.scheduled.task.log",
        "task_id",
        string="Ejecuciones",
        readonly=True,
    )
    log_count = fields.Integer(
        "Ejecuciones",
        compute="_compute_log_count",
    )
    last_run = fields.Datetime(
        "Última ejecución",
        compute="_compute_last_run",
        store=True,
    )
    last_state = fields.Selection(
        [("running", "Ejecutando"), ("success", "Exitoso"), ("error", "Error")],
        string="Último resultado",
        compute="_compute_last_run",
        store=True,
    )

    # ─────────────────────────────────────────────────
    # Computed
    # ─────────────────────────────────────────────────
    @api.depends("log_ids")
    def _compute_log_count(self):
        for task in self:
            task.log_count = len(task.log_ids)

    @api.depends("log_ids.execution_date", "log_ids.state")
    def _compute_last_run(self):
        for task in self:
            last = task.log_ids.sorted("execution_date", reverse=True)[:1]
            if last:
                task.last_run = last.execution_date
                task.last_state = last.state
            else:
                task.last_run = False
                task.last_state = False

    # ─────────────────────────────────────────────────
    # Onchange
    # ─────────────────────────────────────────────────
    @api.onchange("assistant_id")
    def _onchange_assistant_id(self):
        if self.assistant_id:
            self.provider_id = self.assistant_id.provider_id
            self.model_id = self.assistant_id.model_id
            self.tool_ids = self.assistant_id.tool_ids

    # ─────────────────────────────────────────────────
    # Constraints
    # ─────────────────────────────────────────────────
    @api.constrains("interval_number")
    def _check_interval_number(self):
        for task in self:
            if task.interval_number < 1:
                raise ValidationError(_("El intervalo debe ser mayor o igual a 1."))

    @api.constrains("provider_id", "model_id", "assistant_id")
    def _check_llm_config(self):
        for task in self:
            if not task.assistant_id and not task.provider_id:
                raise ValidationError(
                    _(
                        "Debes configurar un Asistente o un Proveedor/Modelo LLM "
                        "para la tarea «%(name)s»."
                    )
                    % {"name": task.name}
                )

    # ─────────────────────────────────────────────────
    # ORM Hooks
    # ─────────────────────────────────────────────────
    @api.model_create_multi
    def create(self, vals_list):
        tasks = super().create(vals_list)
        for task in tasks:
            task._sync_cron()
        return tasks

    def write(self, vals):
        res = super().write(vals)
        cron_fields = {
            "state", "interval_number", "interval_type", "next_run", "name",
        }
        if cron_fields.intersection(vals):
            for task in self:
                task._sync_cron()
        return res

    def unlink(self):
        for task in self:
            if task.cron_id:
                task.cron_id.sudo().unlink()
            if task.thread_id:
                task.thread_id.sudo().unlink()
        return super().unlink()

    # ─────────────────────────────────────────────────
    # Cron management
    # ─────────────────────────────────────────────────
    def _sync_cron(self):
        """Crea o actualiza el ir.cron vinculado a esta tarea."""
        self.ensure_one()
        cron_vals = {
            "name": _("LLM Tarea: %s") % self.name,
            "active": self.state == "active",
            "interval_number": self.interval_number,
            "interval_type": self.interval_type,
            "nextcall": self.next_run or fields.Datetime.now(),
        }
        if self.cron_id:
            self.cron_id.sudo().write(cron_vals)
        else:
            ir_model = (
                self.env["ir.model"]
                .sudo()
                .search([("model", "=", "llm.scheduled.task")], limit=1)
            )
            if not ir_model:
                _logger.warning(
                    "No se encontró el modelo llm.scheduled.task en ir.model. "
                    "El cron no se creará."
                )
                return
            cron_vals.update({
                "model_id": ir_model.id,
                "state": "code",
                "code": f"model.browse({self.id})._do_execute()",
                "numbercall": -1,
                "doall": False,
                "user_id": self.user_id.id or self.env.user.id,
            })
            cron = self.env["ir.cron"].sudo().create(cron_vals)
            # Usar sudo() para evitar que el check de write_date falle
            self.sudo().write({"cron_id": cron.id})

    # ─────────────────────────────────────────────────
    # Thread management
    # ─────────────────────────────────────────────────
    def _get_or_create_thread(self):
        """Devuelve el chat dedicado de la tarea, creándolo si no existe."""
        self.ensure_one()
        if self.thread_id and self.thread_id.exists():
            return self.thread_id

        thread_vals = {
            "name": _("[Tarea] %s") % self.name,
            "is_scheduled_task": True,
            "user_id": self.user_id.id,
        }
        if self.assistant_id:
            thread_vals.update({
                "assistant_id": self.assistant_id.id,
                "provider_id": self.assistant_id.provider_id.id,
                "model_id": self.assistant_id.model_id.id,
                "tool_ids": [(6, 0, self.assistant_id.tool_ids.ids)],
            })
        else:
            thread_vals.update({
                "provider_id": self.provider_id.id,
                "model_id": self.model_id.id,
                "tool_ids": [(6, 0, self.tool_ids.ids)],
            })

        # sudo() para que create_uid = SUPERUSER (excluye del chat normal)
        thread = self.env["llm.thread"].sudo().create(thread_vals)
        self.sudo().write({"thread_id": thread.id})
        return thread

    # ─────────────────────────────────────────────────
    # Actions
    # ─────────────────────────────────────────────────
    def action_run_now(self):
        """Ejecuta la tarea manualmente de inmediato."""
        self.ensure_one()
        self._do_execute()
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("Tarea ejecutada"),
                "message": _("La tarea «%s» se ejecutó. Revisa los logs para ver el resultado.") % self.name,
                "type": "success",
                "sticky": False,
                "next": {"type": "ir.actions.act_window_close"},
            },
        }

    def action_pause(self):
        return self.write({"state": "paused"})

    def action_activate(self):
        return self.write({"state": "active"})

    def action_view_logs(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": _("Ejecuciones: %s") % self.name,
            "res_model": "llm.scheduled.task.log",
            "view_mode": "tree,form",
            "domain": [("task_id", "=", self.id)],
            "context": {"default_task_id": self.id},
        }

    def action_view_thread(self):
        """Abre el chat dedicado de la tarea."""
        self.ensure_one()
        thread = self._get_or_create_thread()
        return {
            "type": "ir.actions.act_window",
            "name": _("Chat de tarea: %s") % self.name,
            "res_model": "llm.thread",
            "res_id": thread.id,
            "view_mode": "form",
            "target": "current",
            "context": {"show_task_threads": True},
        }

    # ─────────────────────────────────────────────────
    # Ejecución del LLM
    # ─────────────────────────────────────────────────
    def _do_execute(self):
        """
        Núcleo de la ejecución:
        1. Obtiene / crea el chat dedicado.
        2. Postea el prompt como mensaje de usuario.
        3. Ejecuta el bucle LLM completo (incluyendo tool calls).
        4. Registra el resultado en llm.scheduled.task.log.
        """
        self.ensure_one()
        _logger.info(
            "LLM Tarea '%s' (id=%s): iniciando ejecución.", self.name, self.id
        )

        thread = self._get_or_create_thread()
        start_ts = _time.time()

        # Crear log en estado 'running' y hacer commit para visibilidad inmediata
        log = (
            self.env["llm.scheduled.task.log"]
            .sudo()
            .create({
                "task_id": self.id,
                "execution_date": fields.Datetime.now(),
                "state": "running",
            })
        )
        self.env.cr.commit()

        try:
            # Contar mensajes antes de la ejecución para calcular cuántos se generaron
            msg_domain = [("model", "=", "llm.thread"), ("res_id", "=", thread.id)]
            msg_before = self.env["mail.message"].sudo().search_count(msg_domain)

            # Ejecutar el LLM como el propietario de la tarea
            task_user = self.user_id or self.env.user
            thread_as_user = thread.with_user(task_user)

            for _chunk in thread_as_user.generate(self.task_prompt):
                # Los mensajes se guardan en DB dentro de generate(); solo consumimos el generator
                pass

            msg_after = self.env["mail.message"].sudo().search_count(msg_domain)
            duration = _time.time() - start_ts

            log.sudo().write({
                "state": "success",
                "duration_seconds": duration,
                "message_count": max(0, msg_after - msg_before),
            })
            _logger.info(
                "LLM Tarea '%s': completada en %.1f s (%d mensajes generados).",
                self.name,
                duration,
                max(0, msg_after - msg_before),
            )
        except Exception as exc:
            duration = _time.time() - start_ts
            _logger.exception(
                "LLM Tarea '%s' (id=%s): error durante la ejecución.", self.name, self.id
            )
            log.sudo().write({
                "state": "error",
                "error_message": str(exc),
                "duration_seconds": duration,
            })
            self.env.cr.commit()
        finally:
            # Actualizar last_run aunque haya error
            self.sudo().write({"state": self.state})  # Trigger recompute de last_run
