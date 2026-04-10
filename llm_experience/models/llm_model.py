# -*- coding: utf-8 -*-
from odoo import fields, models


class LLMModel(models.Model):
    _inherit = "llm.model"

    context_window_tokens = fields.Integer(
        string="Ventana de contexto (tokens)",
        default=1_048_576,
        help="Límite teórico de tokens de contexto para el medidor y umbrales. "
        "Ajuste según el modelo (p. ej. Gemini Flash ~1M).",
    )
