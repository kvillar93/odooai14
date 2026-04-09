# -*- coding: utf-8 -*-
import logging

from odoo import api, fields, models

_logger = logging.getLogger(__name__)


class LlmThreadCostLine(models.Model):
    _name = "llm.thread.cost.line"
    _description = "Desglose de coste estimado por respuesta (chat)"
    _order = "id desc"

    thread_id = fields.Many2one(
        "llm.thread",
        string="Chat",
        required=True,
        ondelete="cascade",
        index=True,
    )
    prompt_tokens = fields.Integer(string="Tokens entrada", default=0)
    output_tokens = fields.Integer(string="Tokens salida", default=0)
    cached_tokens = fields.Integer(string="Tokens caché", default=0)
    cost_usd_delta = fields.Float(
        string="Coste USD (este turno)",
        digits=(16, 8),
        required=True,
    )
    cumulative_usd_total = fields.Float(
        string="Coste USD acumulado (tras este turno)",
        digits=(16, 8),
        required=True,
    )
    pricing_rate_id = fields.Many2one(
        "llm.gemini.pricing.rate",
        string="Tarifa aplicada",
        ondelete="set null",
    )
    model_name_snapshot = fields.Char(string="Modelo (instantánea)")
