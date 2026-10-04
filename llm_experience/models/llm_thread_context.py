# -*- coding: utf-8 -*-
"""Gestión de contexto estilo Cursor: el historial nunca se pierde.

- El historial enviado al modelo son los mensajes posteriores al *corte*
  (``context_cutoff_message_id``) más el último mensaje del usuario, sin límite
  de cantidad.
- Antes de cada petición se estima el tamaño localmente (caracteres / factor
  calibrado con el uso real). Si supera el umbral, los mensajes antiguos se
  resumen en ``usage_compaction_summary`` (resumen acumulativo), el corte avanza
  y la conversación continúa.
"""
import json
import logging

from odoo import _, api, fields, models

_logger = logging.getLogger(__name__)

_KEEP_CURRENT_TURN_ROUNDS = 2
_SUMMARY_SYSTEM_PROMPT = (
    "Eres el módulo de memoria de un asistente de IA que trabaja dentro de Odoo. "
    "Tu resumen sustituirá a los mensajes que recibes, así que no puede perderse "
    "nada necesario para continuar la conversación sin que el usuario repita nada."
)
_SUMMARY_INSTRUCTIONS = (
    "Actualiza el RESUMEN DE CONTEXTO integrando la NUEVA PARTE de la conversación.\n"
    "Conserva, en viñetas y en español, agrupado por secciones:\n"
    "1. Objetivo y peticiones del usuario (cita literal las instrucciones cortas).\n"
    "2. Decisiones, acuerdos y preferencias expresadas.\n"
    "3. Datos concretos obtenidos de Odoo: modelos, IDs, nombres, importes, fechas, "
    "dominios y campos que funcionaron.\n"
    "4. Errores de herramientas y lo aprendido (campos o modelos inexistentes, "
    "permisos, formatos rechazados) para no repetirlos.\n"
    "5. Trabajo ya realizado (registros creados, modificados o enviados).\n"
    "6. Pendientes y siguiente paso previsto.\n"
    "No inventes nada. Sin saludos. Condensa lo antiguo si el resumen crece; "
    "apunta a menos de 1500 palabras."
)


class LLMThread(models.Model):
    _inherit = "llm.thread"

    # ------------------------------------------------------------------
    # Historial enviado al modelo
    # ------------------------------------------------------------------

    def _context_base_domain(self):
        return [
            ("model", "=", self._name),
            ("res_id", "=", self.id),
            ("llm_role", "!=", False),
        ]

    def get_llm_messages(self, limit=25):
        """Mensajes posteriores al corte + ancla de usuario, en orden cronológico.

        ``limit`` se ignora: el tamaño se controla con el resumen de contexto,
        no recortando mensajes (lo que hacía olvidar la petición original).
        """
        self.ensure_one()
        Message = self.env["mail.message"]
        base = self._context_base_domain()
        cutoff = self.context_cutoff_message_id or 0
        domain = base + ([("id", ">", cutoff)] if cutoff else [])
        messages = Message.search(domain, order="id asc")
        if cutoff and (not messages or messages[0].llm_role != "user"):
            # El corte cayó dentro de un turno: fijar la petición del usuario
            # para que el modelo siempre sepa qué está resolviendo.
            anchor = Message.search(
                base + [("llm_role", "=", "user"), ("id", "<=", cutoff)],
                order="id desc",
                limit=1,
            )
            messages = (anchor | messages).sorted("id")
        last_user = Message.search(
            base + [("llm_role", "=", "user")], order="id desc", limit=1
        )
        return messages.with_context(llm_history_turn_start_id=last_user.id or 0)

    # ------------------------------------------------------------------
    # Estimación
    # ------------------------------------------------------------------

    def _context_estimate_breakdown(self, messages, prepend_messages=None):
        """Caracteres por componente: sistema, resumen, herramientas e historial."""
        self.ensure_one()
        breakdown = {"system": 0, "summary": 0, "tools": 0, "history": 0}
        summary = self.usage_compaction_summary or ""
        for msg in prepend_messages or []:
            if not isinstance(msg, dict):
                continue
            content = msg.get("content")
            if not isinstance(content, str):
                content = json.dumps(content, ensure_ascii=False, default=str)
            key = "summary" if summary and summary in content else "system"
            breakdown[key] += len(content)
        for message in messages:
            breakdown["history"] += message._llm_estimate_chars()
        for tool in self.tool_ids:
            try:
                schema = tool.get_input_schema() or {}
            except Exception:
                schema = {}
            breakdown["tools"] += len(tool.name or "") + len(tool.description or "")
            breakdown["tools"] += len(json.dumps(schema, ensure_ascii=False, default=str))
        return breakdown

    def _context_estimate_chars(self, messages, prepend_messages=None):
        return sum(self._context_estimate_breakdown(messages, prepend_messages).values())

    def _context_chars_to_tokens(self, chars):
        cpt = self.usage_chars_per_token or 3.5
        return int(chars / max(1.0, cpt))

    def _context_estimate(self, prepend_messages=None):
        """(caracteres, tokens) estimados de la próxima petición.

        Guarda además el desglose en tokens para el medidor.
        """
        self.ensure_one()
        if prepend_messages is None:
            prepend_messages = self.get_prepend_messages()
        breakdown = self._context_estimate_breakdown(
            self.get_llm_messages(), prepend_messages
        )
        self.usage_breakdown_json = {
            key: self._context_chars_to_tokens(value) for key, value in breakdown.items()
        }
        chars = sum(breakdown.values())
        return chars, self._context_chars_to_tokens(chars)

    # ------------------------------------------------------------------
    # Pre-flight: se llama antes de cada petición al modelo
    # ------------------------------------------------------------------

    def _context_preflight(self, prepend_messages):
        """Estima la petición y resume el historial si hace falta.

        Devuelve el mensaje de nota de la compactación o ``False``.
        """
        self.ensure_one()
        chars, tokens = self._context_estimate(prepend_messages)
        threshold = self._usage_compaction_threshold()
        note = False
        if tokens >= threshold or self.usage_needs_compaction:
            _logger.info(
                "Contexto thread=%s: ~%s tokens (umbral %s); se resume el historial.",
                self.id,
                tokens,
                threshold,
            )
            note = self._context_compact(reason="auto", estimated_tokens=tokens)
            if note:
                chars, tokens = self._context_estimate()
        self.write(
            {
                "usage_last_request_chars": chars,
                "usage_last_estimated_prompt": tokens,
                "usage_live_tokens": tokens,
                "usage_needs_compaction": False,
            }
        )
        return note

    # ------------------------------------------------------------------
    # Compactación
    # ------------------------------------------------------------------

    def _context_split_rounds(self, messages):
        """Agrupa mensajes en rondas que empiezan por un mensaje ``assistant``."""
        rounds = []
        for message in messages:
            if message.llm_role == "assistant" or not rounds:
                rounds.append(message)
            else:
                rounds[-1] |= message
        return rounds

    def _context_select_messages_to_summarize(self):
        """Mensajes a resumir: turnos previos y, si hace falta, rondas antiguas del actual."""
        self.ensure_one()
        window = self.get_llm_messages()
        turn_start = window.env.context.get("llm_history_turn_start_id") or 0
        cutoff = self.context_cutoff_message_id or 0
        fresh = window.filtered(lambda m: m.id > cutoff)
        previous = fresh.filtered(lambda m: m.id < turn_start)
        current = fresh.filtered(lambda m: m.id > turn_start)
        selected = previous
        current_tokens = self._context_chars_to_tokens(
            sum(m._llm_estimate_chars() for m in current)
        )
        if current and (
            not previous or current_tokens > self._usage_compaction_threshold() * 0.5
        ):
            rounds = self._context_split_rounds(current)
            for older in rounds[:-_KEEP_CURRENT_TURN_ROUNDS]:
                selected |= older
        return selected.sorted("id")

    def _context_compact(self, reason="auto", estimated_tokens=None):
        """Resume el historial antiguo y mueve el corte. Devuelve la nota publicada."""
        self.ensure_one()
        to_summarize = self._context_select_messages_to_summarize()
        if not to_summarize:
            return False
        if estimated_tokens is None:
            estimated_tokens = self._context_estimate()[1]
        summary = self._context_build_summary(
            to_summarize, self.usage_compaction_summary or ""
        )
        if not summary:
            return False
        history = list((self.usage_compaction_meta_json or {}).get("history") or [])
        meta = {
            "reason": reason,
            "date": fields.Datetime.to_string(fields.Datetime.now()),
            "messages_summarized": len(to_summarize),
            "from_message_id": to_summarize[0].id,
            "to_message_id": to_summarize[-1].id,
            "tokens_before": int(estimated_tokens or 0),
        }
        self.write(
            {
                "usage_compaction_summary": summary,
                "context_cutoff_message_id": to_summarize[-1].id,
                "usage_compaction_count": self.usage_compaction_count + 1,
                "usage_last_compaction_date": fields.Datetime.now(),
                "usage_needs_compaction": False,
            }
        )
        tokens_after = self._context_estimate()[1]
        meta["tokens_after"] = tokens_after
        history.append(meta)
        self.write(
            {
                "usage_live_tokens": tokens_after,
                "usage_compaction_meta_json": dict(meta, history=history[-20:]),
            }
        )
        note = self.message_post(
            body=_(
                "<p><em>🔄 Contexto resumido para continuar: %(count)s mensajes "
                "(~%(before)s → ~%(after)s tokens). El asistente conserva lo "
                "importante de la conversación.</em></p>"
            )
            % {
                "count": len(to_summarize),
                "before": self._context_format_tokens(meta["tokens_before"]),
                "after": self._context_format_tokens(tokens_after),
            },
            message_type="comment",
            subtype_xmlid="mail.mt_note",
            author_id=self.env.ref("base.partner_root").id,
        )
        self.env.cr.commit()
        _logger.info("Contexto thread=%s compactado: %s", self.id, meta)
        return note

    def _context_reset(self):
        """Contexto limpio en el mismo chat: el modelo deja de ver lo anterior."""
        self.ensure_one()
        last = self.env["mail.message"].search(
            self._context_base_domain(), order="id desc", limit=1
        )
        self.write(
            {
                "context_cutoff_message_id": last.id or 0,
                "usage_compaction_summary": False,
                "usage_live_tokens": 0,
                "usage_needs_compaction": False,
                "experience_research_plan": False,
            }
        )
        return self.message_post(
            body=_(
                "<p><em>🧹 Contexto reiniciado: los mensajes anteriores siguen "
                "visibles, pero el asistente empieza desde cero.</em></p>"
            ),
            message_type="comment",
            subtype_xmlid="mail.mt_note",
            author_id=self.env.ref("base.partner_root").id,
        )

    @api.model
    def _context_format_tokens(self, tokens):
        tokens = int(tokens or 0)
        if tokens >= 1000:
            return "%.1fk" % (tokens / 1000.0)
        return str(tokens)

    def _context_build_summary(self, messages, previous_summary):
        """Resumen acumulativo; transcripciones grandes se procesan por bloques."""
        self.ensure_one()
        lines = [line for line in (m._llm_compaction_line() for m in messages) if line]
        try:
            chunk_chars = int(
                self.env["ir.config_parameter"]
                .sudo()
                .get_param("llm_experience.compaction_chunk_chars")
                or 240000
            )
        except (TypeError, ValueError):
            chunk_chars = 240000
        chunks, current, size = [], [], 0
        for line in lines:
            if current and size + len(line) > chunk_chars:
                chunks.append(current)
                current, size = [], 0
            current.append(line[:chunk_chars])
            size += len(line)
        if current:
            chunks.append(current)

        summary = previous_summary
        for chunk in chunks:
            transcript = "\n\n".join(chunk)
            new_summary = self._context_summarize_with_model(summary, transcript)
            if not new_summary:
                new_summary = self._context_extractive_summary(summary, chunk)
            summary = new_summary
        return summary

    def _context_summarize_with_model(self, previous_summary, transcript):
        self.ensure_one()
        prompt = "%s\n\nRESUMEN DE CONTEXTO PREVIO:\n%s\n\nNUEVA PARTE:\n%s" % (
            _SUMMARY_INSTRUCTIONS,
            previous_summary or _("(vacío)"),
            transcript,
        )
        try:
            result = self.sudo().provider_id.chat(
                messages=[
                    {"role": "system", "content": _SUMMARY_SYSTEM_PROMPT},
                    {"role": "user", "content": prompt},
                ],
                model=self.model_id,
                stream=False,
                reasoning_effort="instant",
                tool_choice="none",
                llm_thread=self.with_context(llm_compaction_call=True),
            )
            result = self._collect_chat_result(result)
        except Exception as err:
            _logger.warning("Contexto thread=%s: fallo al resumir: %s", self.id, err)
            return ""
        if not isinstance(result, dict) or result.get("error"):
            return ""
        return (result.get("content") or "").strip()

    @api.model
    def _context_extractive_summary(self, previous_summary, lines):
        """Respaldo sin modelo: conserva todas las peticiones del usuario y extractos."""
        kept = []
        for line in lines:
            if line.startswith("[Usuario"):
                kept.append(line[:4000])
            elif "ERROR" in line[:80]:
                kept.append(line[:400])
            else:
                kept.append(line[:300])
        parts = [previous_summary] if previous_summary else []
        parts.append(
            _("Extracto de la conversación (resumen automático no disponible):")
        )
        parts.append("\n".join(kept))
        return "\n\n".join(parts)

    # ------------------------------------------------------------------
    # Señales para el modelo durante el bucle de herramientas
    # ------------------------------------------------------------------

    def _context_current_turn_messages(self):
        self.ensure_one()
        window = self.get_llm_messages()
        turn_start = window.env.context.get("llm_history_turn_start_id") or 0
        return window.filtered(lambda m: m.id > turn_start)

    def _context_tool_error_hint(self, current_turn):
        """Instrucción de sistema si las herramientas fallan en racha o se repiten."""
        tool_msgs = current_turn.filtered(lambda m: m.llm_role == "tool")
        if not tool_msgs:
            return None
        streak = []
        for message in reversed(tool_msgs):
            if not message._llm_tool_is_error():
                break
            streak.append(message)
        failed_signatures = {}
        for message in tool_msgs.filtered(lambda m: m._llm_tool_is_error()):
            data = message._ensure_body_json_dict()
            args = data.get("arguments")
            signature = (
                data.get("tool_name"),
                json.dumps(args, sort_keys=True, default=str) if args else "",
            )
            failed_signatures[signature] = failed_signatures.get(signature, 0) + 1
        repeated = [sig for sig, count in failed_signatures.items() if count >= 2]
        if len(streak) < 2 and not repeated:
            return None
        details = []
        for message in streak[:3]:
            data = message._ensure_body_json_dict()
            error = data.get("error") or message._llm_tool_raw_text()
            details.append("- %s: %s" % (data.get("tool_name") or "?", str(error)[:300]))
        text = _(
            "Atención: las últimas llamadas a herramientas fallaron%(repeat)s.\n"
            "%(details)s\n"
            "No repitas la misma llamada con los mismos argumentos. Cambia de "
            "estrategia: verifica nombres de modelos y campos (por ejemplo con el "
            "inspector de modelos), simplifica el dominio, reduce los campos o "
            "pregunta al usuario si falta información. Continúa con la tarea."
        ) % {
            "repeat": _(" y se repitieron llamadas idénticas") if repeated else "",
            "details": "\n".join(details),
        }
        return {"role": "system", "content": text}

    def _context_tool_rounds_exceeded(self, current_turn):
        """Tope opcional de rondas de herramientas por turno (0 = ilimitado)."""
        try:
            limit = int(
                self.env["ir.config_parameter"]
                .sudo()
                .get_param("llm_experience.max_tool_rounds_per_turn")
                or 0
            )
        except (TypeError, ValueError):
            limit = 0
        if limit <= 0:
            return False
        rounds = current_turn.filtered(
            lambda m: m.llm_role == "assistant" and m.has_tool_calls()
        )
        return len(rounds) >= limit

    def _get_assistant_message_meta(self):
        meta = super()._get_assistant_message_meta()
        meta["reasoning_effort"] = self._experience_effective_reasoning_effort()
        return meta

    def _get_extra_chat_kwargs(self):
        kwargs = super()._get_extra_chat_kwargs()
        kwargs["reasoning_effort"] = self._experience_effective_reasoning_effort()
        tool_choice = self.env.context.get("llm_tool_choice")
        if tool_choice:
            kwargs["tool_choice"] = tool_choice
        return kwargs
