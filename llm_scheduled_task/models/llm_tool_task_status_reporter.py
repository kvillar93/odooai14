# -*- coding: utf-8 -*-
"""Tool ``llm_task_status_reporter``.

Permite al asistente cerrar explícitamente la ejecución de una tarea
programada indicando éxito o error y un resumen ejecutivo de lo que hizo.

Es la forma recomendada (y la que el wrapper del prompt impone) de marcar
el log ``llm.scheduled.task.log`` correspondiente, en lugar de depender
del cron supervisor o del diagnóstico IA posterior.

El campo ``send_status_via_email_to`` es opcional y, si viene relleno,
adicionalmente envía un correo con el resumen final de la ejecución
(útil para tareas tipo «hazme un informe y mándamelo»).
"""
import logging
from typing import Any, Optional

from odoo import _, api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class LLMToolTaskStatusReporter(models.Model):
    _inherit = "llm.tool"

    @api.model
    def _get_available_implementations(self):
        impl = super()._get_available_implementations()
        return impl + [
            (
                "llm_task_status_reporter",
                "Reportar estado final de tarea programada",
            ),
        ]

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    def _llm_status_get_thread_from_context(self):
        """Obtiene el ``llm.thread`` activo (el del mensaje que disparó el tool)."""
        msg = self.env.context.get("message")
        if not msg or not getattr(msg, "model", None):
            return self.env["llm.thread"]
        if msg.model != "llm.thread" or not msg.res_id:
            return self.env["llm.thread"]
        return self.env["llm.thread"].browse(msg.res_id)

    def _llm_status_find_running_log(self, thread):
        """Localiza el log *running* asociado al thread (si existe)."""
        if not thread:
            return self.env["llm.scheduled.task.log"]
        Log = self.env["llm.scheduled.task.log"].sudo()
        log = Log.search(
            [("thread_id", "=", thread.id), ("state", "=", "running")],
            order="execution_date desc, id desc",
            limit=1,
        )
        if log:
            return log
        # Si ya no hay running, devolvemos el más reciente para sobreescribir
        return Log.search(
            [("thread_id", "=", thread.id)],
            order="execution_date desc, id desc",
            limit=1,
        )

    # ------------------------------------------------------------------
    # Execute
    # ------------------------------------------------------------------
    def llm_task_status_reporter_execute(
        self,
        state: str,
        summary: str,
        details: Optional[str] = None,
    ) -> dict[str, Any]:
        """
        state: Estado final obligatorio. Valores admitidos: ``success`` (todo lo
            pedido se completó incluyendo envío de correos / generación de
            artefactos / actualizaciones de registros) o ``error`` (faltó
            algún paso, hubo un fallo en una herramienta, datos
            insuficientes, etc.).
        summary: Resumen ejecutivo en español (1-2 frases) de lo realizado o
            del motivo del error. Aparecerá en el log de la tarea.
        details: Opcional. Detalles adicionales (qué herramientas se usaron,
            ids de registros creados, destinatarios de correo, etc.).
        """
        self.ensure_one()

        state_norm = (state or "").strip().lower()
        if state_norm not in ("success", "error"):
            raise UserError(
                _(
                    "El parámetro «state» debe ser «success» o «error». "
                    "Recibido: %s"
                )
                % state
            )

        summary = (summary or "").strip()
        if not summary:
            raise UserError(
                _(
                    "El parámetro «summary» es obligatorio: explica en una "
                    "frase lo que hiciste o por qué falló."
                )
            )

        details = (details or "").strip()

        thread = self._llm_status_get_thread_from_context()
        log = self._llm_status_find_running_log(thread)

        if not log:
            return {
                "ok": False,
                "mensaje": _(
                    "No se encontró un log de tarea programada asociado a "
                    "este chat. El estado no se persistió, pero se registró "
                    "el resumen para el supervisor."
                ),
                "estado": state_norm,
                "resumen": summary,
            }

        message_parts = [_("Reporte del asistente: %s") % summary]
        if details:
            message_parts.append(_("Detalles: %s") % details)
        message_text = "\n".join(message_parts)[:4000]

        write_vals = {
            "state": state_norm,
            "error_message": message_text,
        }
        # Si aún estaba en running, calculamos la duración real
        if log.state == "running" and log.execution_date:
            now = fields.Datetime.now()
            duration = max(0.0, (now - log.execution_date).total_seconds())
            write_vals["duration_seconds"] = duration

        log.sudo().write(write_vals)
        _logger.info(
            "llm_task_status_reporter: log id=%s tarea «%s» marcado como %s "
            "por el propio asistente.",
            log.id,
            log.task_id.name if log.task_id else "?",
            state_norm,
        )

        return {
            "ok": True,
            "log_id": log.id,
            "tarea": log.task_id.name if log.task_id else False,
            "estado": state_norm,
            "resumen": summary,
            "mensaje": _(
                "Estado registrado correctamente. El log de la ejecución "
                "queda marcado como «%(state)s»."
            )
            % {"state": state_norm},
        }
