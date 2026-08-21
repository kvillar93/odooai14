# -*- coding: utf-8 -*-
from odoo import api, models


class LLMThread(models.Model):
    _inherit = "llm.thread"

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            wid = vals.get("chat_window_id")
            if not wid:
                continue
            win = self.env["llm.chat.window"].browse(int(wid))
            if not win.exists():
                continue

            vals.setdefault("provider_id", win.provider_id.id)
            vals.setdefault("model_id", win.model_id.id)
            vals.setdefault("hide_thread_settings", win.hide_thread_settings)
            vals["chat_window_id"] = win.id

            assistant = win.assistant_id
            if assistant:
                vals.setdefault("assistant_id", assistant.id)
                # Propagar el prompt del asistente: sin esto el contexto del
                # sistema (rol, capacidades, restricciones) nunca se inyecta
                # en el chat porque ``llm_assistant.LLMThread.create`` solo
                # aplica defaults cuando NO hay assistant_id ya en vals.
                if assistant.prompt_id:
                    vals.setdefault("prompt_id", assistant.prompt_id.id)
                # Tools: si la ventana no definió tools propias, heredamos
                # las del asistente. Si la ventana sí trae tools, las suyas
                # ganan (es el comportamiento previo).
                if win.tool_ids:
                    vals.setdefault("tool_ids", [(6, 0, win.tool_ids.ids)])
                else:
                    vals.setdefault(
                        "tool_ids", [(6, 0, assistant.tool_ids.ids)]
                    )
            else:
                vals.setdefault("tool_ids", [(6, 0, win.tool_ids.ids)])
        return super().create(vals_list)
