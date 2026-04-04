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
            "Tiene coste según la tarifa de Google; no sustituye a herramientas Odoo personalizadas."
        ),
    )
