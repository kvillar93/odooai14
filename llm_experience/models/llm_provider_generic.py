# -*- coding: utf-8 -*-
"""Fallback genérico cuando un provider no implementa *_format_messages."""
import logging

from odoo import models, tools

_logger = logging.getLogger(__name__)


class LLMProviderGeneric(models.Model):
    _inherit = "llm.provider"

    def format_messages(self, messages, system_prompt=None):
        """Si el provider no tiene método específico, usa formateo genérico."""
        if not self.service:
            return super().format_messages(messages, system_prompt=system_prompt)
        specific = "%s_format_messages" % self.service
        if hasattr(self, specific):
            return super().format_messages(messages, system_prompt=system_prompt)
        return self._generic_format_messages(messages, system_prompt=system_prompt)

    def _generic_format_messages(self, messages, system_prompt=None):
        out = []
        if system_prompt:
            out.append({"role": "system", "content": system_prompt})
        for m in messages or []:
            if isinstance(m, dict) and m.get("role"):
                out.append(dict(m))
                continue
            role = getattr(m, "llm_role", None)
            body = getattr(m, "body", "") or ""
            if body:
                try:
                    body = tools.html2plaintext(body)
                except Exception:
                    pass
            if role in ("user", "assistant", "system"):
                out.append({"role": role, "content": body})
            elif role == "tool":
                data = getattr(m, "body_json", None) or {}
                text = data.get("result") or data.get("error") or body or ""
                out.append({"role": "user", "content": "[tool] %s" % text})
        return out
