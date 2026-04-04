# -*- coding: utf-8 -*-
from odoo import _, api, fields, models


class LLMChatWindow(models.Model):
    _name = "llm.chat.window"
    _description = "Ventana de chat LLM preconfigurada"
    _order = "sequence, name"

    name = fields.Char(required=True, string="Nombre del menú")
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)
    hide_thread_settings = fields.Boolean(
        string="Ocultar proveedor, modelo y tools en el chat",
        default=False,
    )
    provider_id = fields.Many2one("llm.provider", string="Proveedor", required=True)
    model_id = fields.Many2one(
        "llm.model",
        string="Modelo de IA",
        required=True,
        domain="[('provider_id', '=', provider_id), ('model_use', 'in', ['chat', 'multimodal'])]",
    )
    assistant_id = fields.Many2one(
        "llm.assistant",
        string="Asistente",
        domain="[('provider_id', '=', provider_id)]",
    )
    tool_ids = fields.Many2many("llm.tool", string="Tools")

    def action_open_chat(self):
        self.ensure_one()
        return {
            "type": "ir.actions.client",
            "tag": "llm_thread.chat_client_action",
            "name": self.name,
            "params": {"default_chat_window_id": self.id},
            "context": {"default_chat_window_id": self.id},
            "target": "current",
        }

    def action_open_menu_wizard(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": _("Crear entrada de menú"),
            "res_model": "llm.chat.window.menu.wizard",
            "view_mode": "form",
            "target": "new",
            "context": {"default_window_id": self.id},
        }
