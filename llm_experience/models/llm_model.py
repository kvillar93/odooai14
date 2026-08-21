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

    allowed_user_ids = fields.Many2many(
        "res.users",
        "llm_model_user_rel",
        "model_id",
        "user_id",
        string="Usuarios permitidos",
        help=(
            "Si se seleccionan usuarios, este modelo SOLO será visible "
            "para ellos. Si se deja vacío, es visible para todos los "
            "usuarios con acceso al modelo (comportamiento por defecto)."
        ),
    )


class LLMProvider(models.Model):
    _inherit = "llm.provider"

    allowed_user_ids = fields.Many2many(
        "res.users",
        "llm_provider_user_rel",
        "provider_id",
        "user_id",
        string="Usuarios permitidos",
        help=(
            "Si se seleccionan usuarios, este proveedor SOLO será "
            "visible para ellos. Si se deja vacío, es visible para "
            "todos los usuarios con acceso al proveedor."
        ),
    )

