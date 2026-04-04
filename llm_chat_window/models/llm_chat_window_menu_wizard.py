# -*- coding: utf-8 -*-
from odoo import _, fields, models


class LLMChatWindowMenuWizard(models.TransientModel):
    _name = "llm.chat.window.menu.wizard"
    _description = "Asistente para crear menú de ventana de chat"

    window_id = fields.Many2one(
        "llm.chat.window",
        string="Ventana de chat",
        required=True,
        ondelete="cascade",
    )
    parent_menu_id = fields.Many2one(
        "ir.ui.menu",
        string="Menú padre",
        help="Vacío para colocar el acceso como menú raíz (nivel aplicación).",
    )
    menu_name = fields.Char(
        string="Texto del menú",
        help="Si se deja vacío, se usa el nombre de la ventana de chat.",
    )
    sequence = fields.Integer(default=10, string="Secuencia")

    def action_create_menu(self):
        self.ensure_one()
        window = self.window_id
        name = (self.menu_name or "").strip() or window.name
        action = self.env["ir.actions.client"].sudo().create(
            {
                "name": name,
                "tag": "llm_thread.chat_client_action",
                "params": {"default_chat_window_id": window.id},
                "target": "current",
            }
        )
        self.env["ir.ui.menu"].sudo().create(
            {
                "name": name,
                "parent_id": self.parent_menu_id.id if self.parent_menu_id else False,
                "action": f"ir.actions.client,{action.id}",
                "sequence": self.sequence or 10,
            }
        )
        return {"type": "ir.actions.act_window_close"}
