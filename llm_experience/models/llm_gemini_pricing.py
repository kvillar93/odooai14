# -*- coding: utf-8 -*-
"""Tarifas USD/millón de tokens para estimación de coste (Gemini + Anthropic + OpenAI)."""

import logging
import re
from datetime import datetime

from odoo import api, fields, models

_logger = logging.getLogger(__name__)

# Tabla de referencia. El orden importa: el PRIMER patrón que matchee gana,
# así que los patrones más específicos van arriba de los genéricos.
# Tupla: (regex, input_usd_per_million, output_usd_per_million, cached_usd_per_million)
#
# Fuentes (revisadas abril 2026):
#  - Gemini:    https://ai.google.dev/pricing
#  - Anthropic: https://platform.claude.com/docs/en/about-claude/pricing
#  - OpenAI:    https://openai.com/api/pricing/
_DEFAULT_GEMINI_USD_PER_MILLION = [
    # --- Gemini ---
    (r"flash-lite|flash-8b", 0.075, 0.30, 0.02),
    (r"gemini-3|gemini-2\.5|2\.0-flash", 0.10, 0.40, 0.025),
    (r"1\.5-flash", 0.075, 0.30, 0.02),
    (r"1\.5-pro|gemini-pro", 1.25, 5.00, 0.31),
    (r"gemini", 0.10, 0.40, 0.025),

    # ======================================================================
    # --- Anthropic Claude (precios oficiales abril 2026) ---
    # Cached input = 0.1x del input (cache reads) → usamos esa referencia.
    # ======================================================================
    # Opus 4.5 / 4.6 / 4.7 / 4.8…  (familia precio reducido post-4.1)
    (r"claude-opus-4-(?:[5-9]|\d\d)|claude-4-\d+-opus-\d|claude-opus-4-[5-9]\d*", 5.00, 25.00, 0.50),
    # Opus 4.1 / Opus 4.0 (precio antiguo, alto tier)
    (r"claude-opus-4-[01]|claude-opus-4\b", 15.00, 75.00, 1.50),
    # Opus 3.x / Claude 3 Opus (legacy)
    (r"claude-3-opus|claude-opus-3", 15.00, 75.00, 1.50),
    # Haiku 4.x (4.5+)
    (r"claude-haiku-4|claude-4-haiku", 1.00, 5.00, 0.10),
    # Haiku 3.5
    (r"claude-3-5-haiku|claude-haiku-3-5", 0.80, 4.00, 0.08),
    # Haiku 3
    (r"claude-3-haiku|claude-haiku-3", 0.25, 1.25, 0.03),
    # Sonnet 4.x (4.5, 4.6…)
    (r"claude-sonnet-4|claude-4-sonnet|claude-4-\d+-sonnet", 3.00, 15.00, 0.30),
    # Sonnet 3.7 / 3.5 / 3
    (r"claude-3-7-sonnet|claude-3-5-sonnet|claude-3-sonnet|claude-sonnet-3", 3.00, 15.00, 0.30),
    # Claude 2 (legacy)
    (r"claude-2", 8.00, 24.00, 0.80),
    # Fallback genérico Claude
    (r"claude", 3.00, 15.00, 0.30),

    # ======================================================================
    # --- OpenAI (GPT) ---
    # ======================================================================
    (r"gpt-4o-mini", 0.15, 0.60, 0.075),
    (r"gpt-4o", 2.50, 10.00, 1.25),
    (r"gpt-4\.1", 2.00, 8.00, 0.50),
    (r"o3-mini|o4-mini", 1.10, 4.40, 0.55),
    (r"o1-mini", 3.00, 12.00, 1.50),
    (r"o1-preview|o1\b", 15.00, 60.00, 7.50),
    (r"gpt-4-turbo|gpt-4-1106|gpt-4-0125", 10.00, 30.00, 5.00),
    (r"gpt-4", 30.00, 60.00, 15.00),
    (r"gpt-3\.5", 0.50, 1.50, 0.25),
]


def _match_default_prices(name):
    """Devuelve la primera tupla (inp, out, cch) que case con *name* o None."""
    name_l = (name or "").lower()
    if not name_l:
        return None
    for pattern, inp, out, cch in _DEFAULT_GEMINI_USD_PER_MILLION:
        if re.search(pattern, name_l, re.I):
            return inp, out, cch
    return None


class LlmGeminiPricingRate(models.Model):
    _name = "llm.gemini.pricing.rate"
    _description = "Tarifa estimada USD por millón de tokens"
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
    auto_update = fields.Boolean(
        string="Actualización automática",
        default=True,
        help=(
            "Si está activo, el cron diario actualiza los importes desde la "
            "tabla de referencia interna. Desactívalo para fijar precios "
            "manualmente (p. ej. tarifas negociadas)."
        ),
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
    last_sync_source = fields.Char(
        string="Fuente última sincronización",
        help="Nombre o patrón que provocó la última actualización automática.",
    )

    # ------------------------------------------------------------------
    # Lookup
    # ------------------------------------------------------------------
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
        match = _match_default_prices(name_l)
        if match:
            inp, out, cch = match
            # Crea un registro auto:… enlazado al modelo
            key_source = next(
                (p for p, *_ in _DEFAULT_GEMINI_USD_PER_MILLION
                 if re.search(p, name_l, re.I)),
                "",
            )
            key = "auto:" + key_source[:32]
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
                    "last_sync_source": key_source,
                }
            )
        return self.browse()

    # ------------------------------------------------------------------
    # Cron diario
    # ------------------------------------------------------------------
    @api.model
    def cron_refresh_rates_from_defaults(self):
        """Sincroniza importes desde la tabla de referencia interna (diaria).

        1) Actualiza **tarifas existentes con ``auto_update=True``**, buscando
           un match por patrón propio o por los modelos enlazados.
        2) Crea tarifas auto para modelos ``llm.model`` que aún no tengan
           ninguna asociada.
        """
        self = self.sudo()
        LLM = self.env["llm.model"].sudo()
        updated = 0
        created = 0

        # 1) Actualizar tarifas existentes (incluye las precargadas en data).
        for rate in self.search([("auto_update", "=", True)]):
            probe_candidates = []
            if rate.model_name_pattern:
                probe_candidates.append(
                    rate.model_name_pattern.replace("auto:", "").strip()
                )
            probe_candidates.extend(rate.model_ids.mapped("name"))
            match = None
            matched_name = ""
            for name in probe_candidates:
                m = _match_default_prices(name)
                if m:
                    match = m
                    matched_name = name
                    break
            if not match:
                continue
            inp, out, cch = match
            # Solo escribe si cambian los importes (para no ensuciar write_date).
            changed = (
                abs((rate.input_usd_per_million or 0.0) - inp) > 1e-9
                or abs((rate.output_usd_per_million or 0.0) - out) > 1e-9
                or abs((rate.cached_input_usd_per_million or 0.0) - cch) > 1e-9
            )
            if changed:
                rate.write(
                    {
                        "input_usd_per_million": inp,
                        "output_usd_per_million": out,
                        "cached_input_usd_per_million": cch,
                        "last_sync_date": datetime.now(),
                        "last_sync_source": matched_name,
                    }
                )
                updated += 1
            else:
                rate.write(
                    {
                        "last_sync_date": datetime.now(),
                        "last_sync_source": matched_name,
                    }
                )

        # 2) Crear tarifas auto para llm.model sin tarifa asociada.
        for model in LLM.search([]):
            existing = self.search(
                [("model_ids", "in", model.id)], limit=1
            )
            if existing:
                continue
            match = _match_default_prices(model.name or "")
            if not match:
                continue
            inp, out, cch = match
            pattern_source = next(
                (p for p, *_ in _DEFAULT_GEMINI_USD_PER_MILLION
                 if re.search(p, (model.name or "").lower(), re.I)),
                "",
            )
            self.create(
                {
                    "name": "Auto %s" % ((model.name or "")[:60],),
                    "model_ids": [(6, 0, [model.id])],
                    "model_name_pattern": "auto:" + pattern_source[:32],
                    "input_usd_per_million": inp,
                    "output_usd_per_million": out,
                    "cached_input_usd_per_million": cch,
                    "last_sync_date": datetime.now(),
                    "last_sync_source": pattern_source,
                    "auto_update": True,
                    "sequence": 400,
                }
            )
            created += 1

        _logger.info(
            "llm_experience.cron_refresh_rates_from_defaults: "
            "%s tarifas actualizadas, %s creadas.",
            updated,
            created,
        )
        return {"updated": updated, "created": created}

    # ------------------------------------------------------------------
    # Botón manual
    # ------------------------------------------------------------------
    def action_refresh_now(self):
        """Lanza el mismo proceso que el cron desde el botón del formulario."""
        return self.env["llm.gemini.pricing.rate"].cron_refresh_rates_from_defaults()
