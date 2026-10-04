# -*- coding: utf-8 -*-
from odoo import fields, models

from .llm_reasoning import DEFAULT_REASONING_EFFORT, REASONING_EFFORT_SELECTION


class LLMModel(models.Model):
    _inherit = "llm.model"

    context_window_tokens = fields.Integer(
        string="Ventana de contexto (tokens)",
        default=1_048_576,
        help="Límite teórico de tokens de contexto para el medidor y umbrales. "
        "Ajuste según el modelo (p. ej. Gemini Flash ~1M).",
    )
    context_budget_tokens = fields.Integer(
        string="Presupuesto de contexto (tokens)",
        default=200_000,
        help="Tamaño de trabajo del contexto de cada chat (el 100 % del medidor). "
        "Al acercarse al umbral, el historial antiguo se resume y la conversación "
        "continúa sin perder información. 0 = usar la ventana completa del modelo.",
    )
    default_reasoning_effort = fields.Selection(
        REASONING_EFFORT_SELECTION,
        string="Esfuerzo de razonamiento por defecto",
        default=DEFAULT_REASONING_EFFORT,
        help="Nivel inicial de los chats nuevos con este modelo cuando el usuario "
        "no ha elegido uno antes.",
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

