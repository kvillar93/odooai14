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
    group_ids = fields.Many2many(
        "res.groups",
        "llm_chat_window_menu_wizard_group_rel",
        "wizard_id",
        "group_id",
        string="Grupos con acceso",
        help=(
            "Grupos de usuarios que verán este menú. Si se deja vacío, "
            "se aplican las reglas de visibilidad por defecto de Odoo "
            "(visible para todos los usuarios internos)."
        ),
    )

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
        menu_vals = {
            "name": name,
            "parent_id": self.parent_menu_id.id if self.parent_menu_id else False,
            "action": f"ir.actions.client,{action.id}",
            "sequence": self.sequence or 10,
            # Mismo icono que el módulo LLM (solo se aplica a menús raíz).
            "web_icon": "llm,static/description/icon.png",
        }
        if self.group_ids:
            menu_vals["groups_id"] = [(6, 0, self.group_ids.ids)]
        self.env["ir.ui.menu"].sudo().create(menu_vals)
        return {"type": "ir.actions.act_window_close"}
