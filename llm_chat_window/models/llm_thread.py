# -*- coding: utf-8 -*-
from odoo import api, models


class LLMThread(models.Model):
    _inherit = "llm.thread"

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            wid = vals.get("chat_window_id")
            if wid:
                win = self.env["llm.chat.window"].browse(int(wid))
                if win.exists():
                    vals.setdefault("provider_id", win.provider_id.id)
                    vals.setdefault("model_id", win.model_id.id)
                    vals.setdefault("tool_ids", [(6, 0, win.tool_ids.ids)])
                    if win.assistant_id:
                        vals.setdefault("assistant_id", win.assistant_id.id)
                    vals.setdefault("hide_thread_settings", win.hide_thread_settings)
                    vals["chat_window_id"] = win.id
        return super().create(vals_list)
