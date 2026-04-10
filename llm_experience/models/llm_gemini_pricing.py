# -*- coding: utf-8 -*-
"""Tarifas USD/millón de tokens para estimación de coste (Gemini y compatibles)."""

import logging
import re
from datetime import datetime

from odoo import api, fields, models

_logger = logging.getLogger(__name__)

# Referencia orientativa; el cron diario actualiza registros existentes.
# Ajustar según https://ai.google.dev/pricing
_DEFAULT_GEMINI_USD_PER_MILLION = [
    ("flash-lite|flash-8b", 0.075, 0.30, 0.02),
    ("gemini-3|gemini-2\\.5|2\\.0-flash", 0.10, 0.40, 0.025),
    ("1\\.5-flash", 0.075, 0.30, 0.02),
    ("1\\.5-pro|gemini-pro", 1.25, 5.00, 0.31),
    ("gemini", 0.10, 0.40, 0.025),
]


class LlmGeminiPricingRate(models.Model):
    _name = "llm.gemini.pricing.rate"
    _description = "Tarifa estimada USD por millón de tokens (Gemini)"
    _order = "sequence, id"

    active = fields.Boolean(default=True)
    sequence = fields.Integer(default=10)
    name = fields.Char(string="Etiqueta", required=True)
    model_ids = fields.Many2many(
        "llm.model",
        "llm_gemini_pricing_rate_model_rel",
        "rate_id",
        "model_id",
        string="Modelos enlazados",
    )
    model_name_pattern = fields.Char(
        string="Patrón en nombre técnico",
        help="Subcadena (minúsculas) contenida en llm.model.name.",
    )
    input_usd_per_million = fields.Float(
        string="Entrada USD / M tokens",
        digits=(16, 8),
        required=True,
        default=0.10,
    )
    output_usd_per_million = fields.Float(
        string="Salida USD / M tokens",
        digits=(16, 8),
        required=True,
        default=0.40,
    )
    cached_input_usd_per_million = fields.Float(
        string="Entrada en caché USD / M tokens",
        digits=(16, 8),
        default=0.025,
    )
    notes = fields.Text(string="Notas")
    last_sync_date = fields.Datetime(string="Última actualización automática")

    @api.model
    def get_rate_for_llm_model(self, llm_model):
        """Devuelve el registro de tarifa aplicable o vacío."""
        self = self.sudo()
        if not llm_model:
            return self.browse()
        rates = self.search([("active", "=", True)], order="sequence, id")
        for r in rates:
            if llm_model in r.model_ids:
                return r
        name_l = (llm_model.name or "").lower()
        for r in rates:
            pat = (r.model_name_pattern or "").strip().lower()
            if pat and pat in name_l:
                return r
        for pattern, inp, out, cch in _DEFAULT_GEMINI_USD_PER_MILLION:
            if re.search(pattern, name_l, re.I):
                key = "auto:" + pattern[:32]
                found = self.search([("model_name_pattern", "=", key)], limit=1)
                if found:
                    return found
                return self.create(
                    {
                        "name": "Auto %s" % (llm_model.name[:48],),
                        "model_name_pattern": key,
                        "model_ids": [(6, 0, [llm_model.id])],
                        "input_usd_per_million": inp,
                        "output_usd_per_million": out,
                        "cached_input_usd_per_million": cch,
                        "sequence": 400,
                        "last_sync_date": datetime.now(),
                    }
                )
        return self.browse()

    @api.model
    def cron_refresh_rates_from_defaults(self):
        """Sincroniza importes desde la tabla de referencia interna (diaria)."""
        self = self.sudo()
        LLM = self.env["llm.model"].sudo()
        for model in LLM.search([]):
            name_l = (model.name or "").lower()
            for pattern, inp, out, cch in _DEFAULT_GEMINI_USD_PER_MILLION:
                if not re.search(pattern, name_l, re.I):
                    continue
                rate = self.search(
                    [("model_ids", "in", model.id)],
                    limit=1,
                )
                vals = {
                    "input_usd_per_million": inp,
                    "output_usd_per_million": out,
                    "cached_input_usd_per_million": cch,
                    "last_sync_date": datetime.now(),
                }
                if rate:
                    rate.write(vals)
                else:
                    self.create(
                        {
                            "name": "Gemini %s" % (model.name[:60],),
                            "model_ids": [(6, 0, [model.id])],
                            "model_name_pattern": "auto:" + pattern[:32],
                            **vals,
                        }
                    )
                break
        _logger.info("llm_experience: cron_refresh_rates_from_defaults completado.")
