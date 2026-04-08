# -*- coding: utf-8 -*-
from odoo import fields, models


class LLMModel(models.Model):
    _inherit = "llm.model"

    provider_service = fields.Selection(
        related="provider_id.service",
        string="Servicio del proveedor",
        readonly=True,
    )
    gemini_google_search_grounding = fields.Boolean(
        string="Grounding con Google Search (Gemini)",
        default=False,
        help=(
            "Activa la herramienta nativa de Google: el modelo decide si buscar en la web, "
            "genera consultas y sintetiza resultados con citas (groundingMetadata). "
            "Puede usarse junto con las herramientas Odoo (function calling) en modelos compatibles. "
            "Tiene coste según la tarifa de Google; no sustituye a herramientas Odoo personalizadas."
        ),
    )
    gemini_afc_max_remote_calls = fields.Integer(
        string="AFC: máximo de llamadas remotas (Gemini)",
        default=30,
        help=(
            "Límite de la llamada automática a funciones del SDK google-genai (AFC) por petición. "
            "El valor por defecto del SDK es 10; aquí se sube a 30 salvo que indique otro valor. "
            "En modo pensamiento profundo (llm_experience) AFC se desactiva."
        ),
    )
