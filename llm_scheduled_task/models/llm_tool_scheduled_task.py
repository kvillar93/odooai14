# -*- coding: utf-8 -*-
import logging
from datetime import datetime, timezone
from typing import Any, Optional

from odoo import _, api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

_INTERVAL_TYPES = frozenset(
    ("minutes", "hours", "days", "weeks", "months")
)


class LLMToolScheduledTask(models.Model):
    _inherit = "llm.tool"

    @api.model
    def _get_available_implementations(self):
        impl = super()._get_available_implementations()
        return impl + [
            ("llm_scheduled_task_creator", "Creador de tareas programadas LLM"),
            ("llm_mail_sender", "Envío de correo electrónico (SMTP)"),
        ]

    def _llm_scheduled_task_parse_next_run(self, next_run_iso: Optional[str]):
        """Convierte una cadena ISO (o similar) a valor compatible con Datetime de Odoo (naive UTC)."""
        if not next_run_iso or not str(next_run_iso).strip():
            return fields.Datetime.now()
        raw = str(next_run_iso).strip().replace("Z", "+00:00")
        try:
            dt = datetime.fromisoformat(raw)
        except ValueError:
            try:
                dt = datetime.strptime(raw[:19], "%Y-%m-%d %H:%M:%S")
            except ValueError:
                raise UserError(
                    _("next_run_iso no es una fecha/hora válida: «%s». Usa ISO 8601, p. ej. 2026-04-05T08:00:00")
                    % next_run_iso
                ) from None
        if dt.tzinfo is not None:
            dt = dt.astimezone(timezone.utc).replace(tzinfo=None)
        return fields.Datetime.to_string(dt)

    def _llm_scheduled_task_get_thread_from_context(self):
        """Obtiene el llm.thread del mensaje que disparó la herramienta (si existe)."""
        msg = self.env.context.get("message")
        if not msg or not getattr(msg, "model", None) or not getattr(msg, "res_id", None):
            return self.env["llm.thread"]
        if msg.model != "llm.thread":
            return self.env["llm.thread"]
        return self.env["llm.thread"].browse(msg.res_id)

    def llm_scheduled_task_creator_execute(
        self,
        name: str,
        task_prompt: str,
        interval_number: int = 1,
        interval_type: str = "days",
        next_run_iso: Optional[str] = None,
        inherit_llm_config_from_chat: bool = True,
        assistant_id: Optional[int] = None,
        notes: Optional[str] = None,
    ) -> dict[str, Any]:
        """
        name: Título corto y descriptivo de la tarea programada.
        task_prompt: Instrucción completa que el LLM ejecutará en cada ciclo (reportes, correos, consultas Odoo, etc.).
        interval_number: Cada cuántas unidades de tiempo se repite (entero ≥ 1). Ej.: 1 = cada unidad.
        interval_type: Unidad de tiempo: minutes, hours, days, weeks, months.
        next_run_iso: Fecha/hora de la primera ejecución (ISO 8601, ej. 2026-04-05T08:00:00). Opcional; por defecto ahora.
        inherit_llm_config_from_chat: Si True, copia asistente, proveedor, modelo y herramientas del chat actual.
        assistant_id: ID numérico de llm.assistant si no se hereda del chat y quieres fijar un asistente concreto.
        notes: Notas internas opcionales visibles en el formulario de la tarea.
        """
        self.ensure_one()

        if not name or not str(name).strip():
            raise UserError(_("El nombre de la tarea es obligatorio."))
        if not task_prompt or not str(task_prompt).strip():
            raise UserError(_("La instrucción (task_prompt) es obligatoria."))

        if interval_number < 1:
            raise UserError(_("interval_number debe ser mayor o igual a 1."))
        if interval_type not in _INTERVAL_TYPES:
            raise UserError(
                _("interval_type debe ser uno de: %s")
                % ", ".join(sorted(_INTERVAL_TYPES))
            )

        next_run = self._llm_scheduled_task_parse_next_run(next_run_iso)

        vals = {
            "name": str(name).strip(),
            "task_prompt": str(task_prompt).strip(),
            "interval_number": interval_number,
            "interval_type": interval_type,
            "next_run": next_run,
            "user_id": self.env.user.id,
            "state": "active",
        }
        if notes and str(notes).strip():
            vals["notes"] = str(notes).strip()

        thread = self._llm_scheduled_task_get_thread_from_context()

        if inherit_llm_config_from_chat and thread and thread.exists():
            if thread.assistant_id:
                vals["assistant_id"] = thread.assistant_id.id
                vals["provider_id"] = thread.provider_id.id
                vals["model_id"] = thread.model_id.id
                vals["tool_ids"] = [(6, 0, thread.tool_ids.ids)]
            else:
                if not thread.provider_id or not thread.model_id:
                    raise UserError(
                        _(
                            "El chat actual no tiene asistente ni proveedor/modelo configurados. "
                            "Configura el hilo o indica assistant_id."
                        )
                    )
                vals["provider_id"] = thread.provider_id.id
                vals["model_id"] = thread.model_id.id
                vals["tool_ids"] = [(6, 0, thread.tool_ids.ids)]
        elif assistant_id:
            assistant = self.env["llm.assistant"].browse(int(assistant_id))
            if not assistant.exists():
                raise UserError(_("No existe un asistente con id=%s.") % assistant_id)
            vals["assistant_id"] = assistant.id
            vals["provider_id"] = assistant.provider_id.id
            vals["model_id"] = assistant.model_id.id
            vals["tool_ids"] = [(6, 0, assistant.tool_ids.ids)]
        else:
            raise UserError(
                _(
                    "No se pudo determinar la configuración LLM. Usa inherit_llm_config_from_chat=True "
                    "desde un chat con asistente o proveedor/modelo, o indica assistant_id."
                )
            )

        Task = self.env["llm.scheduled.task"]
        task = Task.create(vals)

        return {
            "ok": True,
            "task_id": task.id,
            "nombre": task.name,
            "mensaje": _(
                "Tarea programada creada (id=%(id)s). Se ejecutará según el intervalo; "
                "puedes verla en LLM → Tareas Programadas."
            )
            % {"id": task.id},
            "proxima_ejecucion": fields.Datetime.to_string(task.next_run)
            if task.next_run
            else False,
            "intervalo": f"{task.interval_number} {task.interval_type}",
        }
