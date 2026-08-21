# -*- coding: utf-8 -*-
import json
import logging
import re
from datetime import timedelta

from odoo import _, api, fields, models
from odoo.tools import html2plaintext

_logger = logging.getLogger(__name__)

# Sin mensajes nuevos en el hilo durante este tiempo → ejecución colgada (minutos)
_STALE_ACTIVITY_MINUTES = 15
# No cerrar ejecuciones más recientes (minutos) para no competir con el hilo en curso
_MIN_RUNNING_AGE_MINUTES = 3
# Cuántos mensajes finales del hilo lee la IA para diagnosticar el resultado
_AI_DIAGNOSIS_LAST_MESSAGES = 5
# Recorte por mensaje al construir la transcripción (evita prompts gigantes)
_AI_DIAGNOSIS_MAX_CHARS_PER_MSG = 1500


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
    plan_text = fields.Text(
        "Plan inicial",
        readonly=True,
        help=(
            "Lista de pasos generada por la IA al iniciar la ejecución. "
            "Sirve como checklist y se inyecta en el prompt para que el "
            "modelo lo siga en orden."
        ),
    )
    plan_json = fields.Json(
        "Plan inicial (JSON)",
        readonly=True,
        help="Estructura interna del plan: pasos, tools requeridas, etc.",
    )
    review_iterations = fields.Integer(
        "Reintentos de revisión",
        default=0,
        readonly=True,
        help=(
            "Cuántas veces se reabrió el chat después de la primera respuesta "
            "para forzar la finalización de pasos pendientes (envío de "
            "correo, cierre con llm_task_status_reporter, etc.)."
        ),
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

    def _finalize_supervised_stale(self, message, state="error"):
        """Cierra un log en *running* con un mensaje de supervisión.

        :param str message: Texto descriptivo a guardar en ``error_message``.
        :param str state: Estado final (``error`` o ``success``). El cron de
            supervisión usa ``error`` cuando no puede diagnosticar con IA, y
            ``success``/``error`` según la respuesta del clasificador IA.
        """
        self.ensure_one()
        if self.state != "running":
            return
        now = fields.Datetime.now()
        start = self.execution_date or now
        duration = max(0.0, (now - start).total_seconds())
        vals = {
            "state": state,
            "duration_seconds": duration,
        }
        # Guardamos el mensaje de diagnóstico siempre, independientemente
        # del estado: para success se ve como un resumen, para error como
        # detalle del fallo.
        if state == "error":
            vals["error_message"] = message
        else:
            # En success, lo guardamos también para no perder el contexto.
            vals["error_message"] = message
        self.sudo().write(vals)
        log_fn = _logger.info if state == "success" else _logger.warning
        log_fn(
            "Log ejecución id=%s (tarea %s): finalizado por supervisión "
            "[%s] — %s",
            self.id,
            self.task_id.name,
            state,
            message,
        )

    # ------------------------------------------------------------------
    # Diagnóstico con IA
    # ------------------------------------------------------------------
    def _build_diagnosis_transcript(self):
        """Construye una transcripción legible con los últimos N mensajes
        del hilo de la ejecución, para enviarla al clasificador IA.
        """
        self.ensure_one()
        if not self.thread_id:
            return ""
        Message = self.env["mail.message"].sudo()
        msgs = Message.search(
            [
                ("model", "=", "llm.thread"),
                ("res_id", "=", self.thread_id.id),
            ],
            order="id desc",
            limit=_AI_DIAGNOSIS_LAST_MESSAGES,
        )
        if not msgs:
            return ""
        msgs = msgs.sorted("id")  # cronológico
        lines = []
        for m in msgs:
            role = (
                getattr(m, "llm_role", None)
                or ("user" if m.author_id else "assistant")
            )
            body_html = m.body or ""
            try:
                body_text = html2plaintext(body_html).strip()
            except Exception:
                body_text = re.sub(r"<[^>]+>", "", body_html).strip()
            if not body_text and getattr(m, "body_json", None):
                try:
                    body_text = json.dumps(m.body_json, ensure_ascii=False)[
                        :_AI_DIAGNOSIS_MAX_CHARS_PER_MSG
                    ]
                except Exception:
                    body_text = str(m.body_json)[:_AI_DIAGNOSIS_MAX_CHARS_PER_MSG]
            body_text = body_text[:_AI_DIAGNOSIS_MAX_CHARS_PER_MSG]
            lines.append(f"[{role}] {body_text}")
        return "\n\n".join(lines)

    def _diagnose_with_ai(self):
        """Llama al LLM configurado en la tarea para clasificar la
        ejecución a partir de los últimos mensajes del hilo.

        :returns: tupla ``(state, summary)`` con ``state`` en
            ``("success", "error", "unknown")``.
        """
        self.ensure_one()
        task = self.task_id
        if not task:
            return ("unknown", "Sin tarea asociada para diagnosticar")
        provider = task.provider_id or task.assistant_id.provider_id
        model = task.model_id or task.assistant_id.model_id
        if not provider or not model:
            return ("unknown", "Sin proveedor/modelo configurado para diagnóstico")

        transcript = self._build_diagnosis_transcript()
        if not transcript:
            return (
                "error",
                "Sin mensajes en el hilo: la tarea no produjo actividad.",
            )

        original_prompt = (task.task_prompt or "").strip()
        if len(original_prompt) > 1500:
            original_prompt = original_prompt[:1500] + "…"

        system_prompt = (
            "Eres un supervisor de tareas LLM automatizadas. Tu trabajo es "
            "leer una transcripción y dictaminar si la tarea encargada al "
            "asistente quedó completada con éxito o si terminó en error / "
            "quedó interrumpida. Responde ÚNICAMENTE con un JSON válido "
            "(sin markdown, sin prefijos) con esta forma exacta:\n"
            '{"state": "success" | "error", '
            '"summary": "explicación breve en español (máx. 250 caracteres)"}\n\n'
            "Criterios para 'success':\n"
            " - El asistente confirma haber realizado lo pedido.\n"
            " - Las herramientas (envío de correo, generación de reporte, "
            "actualización de registros…) finalizaron sin errores.\n"
            " - No quedaron acciones pendientes del prompt original.\n\n"
            "Criterios para 'error':\n"
            " - Hay mensajes de error explícitos en herramientas o del modelo.\n"
            " - El asistente quedó esperando confirmación del usuario.\n"
            " - Faltan pasos clave del prompt original.\n"
            " - La conversación quedó truncada o sin respuesta final."
        )

        user_prompt = (
            "PROMPT ORIGINAL DE LA TAREA:\n"
            f"{original_prompt or '(no disponible)'}\n\n"
            f"ÚLTIMOS {_AI_DIAGNOSIS_LAST_MESSAGES} MENSAJES DEL HILO:\n"
            f"{transcript}\n\n"
            "Devuelve únicamente el JSON con la clasificación."
        )

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]

        try:
            text = ""
            chunks = provider.sudo().chat(
                messages, model=model, stream=False
            )
            # provider.chat es un generador que produce dicts
            # ``{"role": "...", "content": "..."}``.
            for chunk in chunks or []:
                if isinstance(chunk, dict):
                    text += str(chunk.get("content") or "")
                else:
                    text += str(chunk or "")
        except Exception as err:
            _logger.warning(
                "Diagnóstico IA falló para log id=%s: %s", self.id, err
            )
            return ("unknown", "No se pudo invocar al LLM para diagnosticar")

        if not text.strip():
            return ("unknown", "El LLM no devolvió respuesta de diagnóstico")

        # Intentar extraer JSON aunque venga rodeado de texto / markdown
        match = re.search(r"\{[\s\S]*\}", text)
        if not match:
            return (
                "unknown",
                "Respuesta de IA sin JSON parseable: %s" % text[:200],
            )
        try:
            data = json.loads(match.group(0))
        except Exception:
            return (
                "unknown",
                "JSON de diagnóstico no válido: %s" % match.group(0)[:200],
            )

        state = (data.get("state") or "").strip().lower()
        summary = str(data.get("summary") or "").strip()[:500]
        if state not in ("success", "error"):
            state = "unknown"
        return (state, summary or "(sin resumen)")

    @api.model
    def cron_supervise_stale_running_logs(self):
        """
        Cron: detecta ejecuciones *running* cuyo hilo no tiene actividad
        reciente y las cierra. En lugar de marcarlas siempre como error,
        usa el LLM configurado para leer los últimos N mensajes del hilo y
        determinar si la tarea **realmente** terminó con éxito o falló.

        Reglas:
        * Si la IA dice ``success`` → log marcado como exitoso con resumen.
        * Si la IA dice ``error`` → log marcado como error con detalle.
        * Si la IA no puede determinar (sin provider, error de red, JSON
          inválido…) → fallback al comportamiento original (error con
          mensaje genérico de supervisión).
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
                # Aún hay actividad reciente: el hilo sigue trabajando.
                continue

            # El hilo está quieto: pedimos diagnóstico al LLM antes de
            # marcar el log.
            state, summary = log._diagnose_with_ai()
            if state == "success":
                log._finalize_supervised_stale(
                    _(
                        "Diagnóstico IA: la tarea se completó correctamente. %s"
                    )
                    % summary,
                    state="success",
                )
            elif state == "error":
                log._finalize_supervised_stale(
                    _("Diagnóstico IA: la tarea terminó en error. %s") % summary,
                )
            else:
                log._finalize_supervised_stale(
                    _(
                        "Ejecución cerrada por supervisión: sin actividad "
                        "reciente en el chat (ventana de %(min)s min) y el "
                        "diagnóstico con IA no fue concluyente — %(why)s"
                    )
                    % {"min": _STALE_ACTIVITY_MINUTES, "why": summary}
                )
