# -*- coding: utf-8 -*-
import json
import logging

from odoo import models, tools

_logger = logging.getLogger(__name__)

_TEXT_MIMETYPE_PREFIXES = ("text/", "application/json", "application/xml")


class MailMessage(models.Model):
    _inherit = "mail.message"

    # ------------------------------------------------------------------
    # Resultados de herramientas en el historial enviado al modelo
    # ------------------------------------------------------------------

    def _llm_tool_is_error(self):
        """True si el mensaje tool terminó en error (excepción o resultado con error)."""
        self.ensure_one()
        data = self._ensure_body_json_dict()
        if data.get("status") == "error" or ("error" in data and "result" not in data):
            return True
        result = data.get("result")
        if isinstance(result, dict):
            return bool(result.get("error")) or result.get("success") is False
        return False

    def _llm_history_char_limit(self, is_error=False):
        """Límite de caracteres del resultado de una tool al reenviarlo al modelo.

        Sólo aplica mientras se construye el historial (``get_llm_messages`` pone
        ``llm_history_turn_start_id`` en el contexto). Los resultados del turno
        actual se conservan casi completos; los de turnos anteriores se recortan.
        """
        turn_start = self.env.context.get("llm_history_turn_start_id")
        if turn_start is None:
            return None
        icp = self.env["ir.config_parameter"].sudo()
        if self.id > turn_start:
            key, default = "llm_experience.tool_result_max_chars_current", 60000
        elif is_error:
            key, default = "llm_experience.tool_error_max_chars_old", 1500
        else:
            key, default = "llm_experience.tool_result_max_chars_old", 6000
        try:
            return max(200, int(icp.get_param(key) or default))
        except (TypeError, ValueError):
            return default

    def _llm_history_tool_text(self, text, is_error=False):
        """Recorta ``text`` según ``_llm_history_char_limit`` con una nota para el modelo."""
        self.ensure_one()
        if not isinstance(text, str):
            return text
        limit = self._llm_history_char_limit(is_error=is_error)
        if not limit or len(text) <= limit:
            return text
        return json.dumps(
            {
                "result_truncated": text[:limit],
                "note": (
                    "Resultado recortado para ahorrar contexto: se omitieron %s de %s "
                    "caracteres. Si necesitas ese detalle, vuelve a consultar con "
                    "filtros más específicos o menos campos."
                )
                % (len(text) - limit, len(text)),
            },
            ensure_ascii=False,
        )

    def openai_format_message(self):
        formatted = super().openai_format_message()
        if formatted and formatted.get("role") == "tool":
            formatted["content"] = self._llm_history_tool_text(
                formatted.get("content") or "", is_error=self._llm_tool_is_error()
            )
        return formatted

    # ------------------------------------------------------------------
    # Estimación de tamaño y transcripción para resúmenes
    # ------------------------------------------------------------------

    def _llm_plain_body(self):
        self.ensure_one()
        if not self.body:
            return ""
        try:
            return tools.html2plaintext(self.body)
        except Exception:
            return str(self.body)

    def _llm_tool_raw_text(self):
        self.ensure_one()
        data = self._ensure_body_json_dict()
        if "result" in data:
            raw = data["result"]
            return raw if isinstance(raw, str) else json.dumps(
                raw, ensure_ascii=False, default=str
            )
        if "error" in data:
            return json.dumps({"error": data["error"]}, ensure_ascii=False, default=str)
        return ""

    def _llm_estimate_chars(self):
        """Caracteres aproximados que este mensaje ocupa en la petición al modelo."""
        self.ensure_one()
        role = self.llm_role
        data = self._ensure_body_json_dict()
        if role == "tool":
            text = self._llm_history_tool_text(
                self._llm_tool_raw_text(), is_error=self._llm_tool_is_error()
            )
            return len(text or "") + 60
        chars = len(self._llm_plain_body())
        if role == "assistant" and data.get("tool_calls"):
            chars += len(json.dumps(data["tool_calls"], ensure_ascii=False, default=str))
        if role == "user":
            for att in self.attachment_ids:
                mimetype = (att.mimetype or "").lower()
                size = att.file_size or 0
                if mimetype.startswith("image/"):
                    chars += 1000
                elif mimetype.startswith(_TEXT_MIMETYPE_PREFIXES):
                    chars += size
                else:
                    chars += min(size // 4, 400000)
        return chars + 20

    def _llm_compaction_line(self):
        """Línea de transcripción compacta para el resumen del historial."""
        self.ensure_one()
        role = self.llm_role
        data = self._ensure_body_json_dict()
        if role == "user":
            text = self._llm_plain_body()[:8000]
            names = ", ".join(self.attachment_ids.mapped("name"))
            if names:
                text += "\n(adjuntos: %s)" % names
            return "[Usuario #%s]\n%s" % (self.id, text)
        if role == "assistant":
            lines = []
            text = self._llm_plain_body()
            if text.strip():
                lines.append("[Asistente #%s]\n%s" % (self.id, text[:3000]))
            for tc in data.get("tool_calls") or []:
                fn = tc.get("function") or {}
                args = fn.get("arguments") or ""
                if not isinstance(args, str):
                    args = json.dumps(args, ensure_ascii=False, default=str)
                lines.append(
                    "[Asistente #%s → herramienta %s] %s"
                    % (self.id, fn.get("name") or "?", args[:600])
                )
            return "\n".join(lines)
        if role == "tool":
            name = data.get("tool_name") or "?"
            if self._llm_tool_is_error():
                err = data.get("error") or self._llm_tool_raw_text()
                return "[Resultado %s · ERROR] %s" % (name, str(err)[:800])
            return "[Resultado %s] %s" % (name, self._llm_tool_raw_text()[:1500])
        return ""
