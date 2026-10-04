# -*- coding: utf-8 -*-
from odoo import fields, models

from .llm_reasoning import REASONING_EFFORT_SELECTION


class ResUsers(models.Model):
    _inherit = "res.users"

    llm_reasoning_effort = fields.Selection(
        REASONING_EFFORT_SELECTION,
        string="Último esfuerzo de razonamiento (chat IA)",
        help="Se usa como valor inicial de los chats nuevos.",
    )
