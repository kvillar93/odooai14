# -*- coding: utf-8 -*-
from odoo import _, models


class LLMThread(models.Model):
    _inherit = "llm.thread"

    def _get_extra_prepend_messages(self):
        """Antepone el snapshot de conocimiento de módulos si está configurado."""
        msgs = super()._get_extra_prepend_messages()
        snapshot = self.env["llm.module.knowledge.snapshot"].sudo()._get_or_create_singleton()
        if not snapshot.active or not snapshot.prepend_to_chat or not (snapshot.content or "").strip():
            return msgs
        max_chars = max(1000, int(snapshot.prepend_max_chars or 32000))
        text = snapshot.content.strip()
        if len(text) > max_chars:
            text = text[: max_chars - 50] + "\n… [truncado por prepend_max_chars]"
        instruction = _(
            "Contexto de referencia sobre los módulos instalados y extractos de código "
            "(snapshot automático). Úsalo para interpretar modelos y convenciones de esta "
            "base Odoo; no sustituye consultar datos concretos del usuario ni los tools.\n\n"
        )
        return msgs + [
            {
                "role": "system",
                "content": instruction + text,
            }
        ]
