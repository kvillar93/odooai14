# -*- coding: utf-8 -*-
"""Topes mensuales por modelo (USD). Bloquean el chat al alcanzarlos."""
import logging
from datetime import datetime

from odoo import _, api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class LlmModelMonthlyCap(models.Model):
    _name = "llm.model.monthly.cap"
    _description = "Tope mensual de coste (USD) por modelo LLM"
    _order = "sequence, id"

    active = fields.Boolean(default=True)
    sequence = fields.Integer(default=10)
    name = fields.Char(
        string="Nombre",
        compute="_compute_name",
        store=True,
    )
    scope = fields.Selection(
        [
            ("model", "Un modelo específico"),
            ("pattern", "Patrón de nombre (varios modelos)"),
            ("global", "Global (todos los modelos)"),
        ],
        string="Ámbito",
        default="model",
        required=True,
    )
    model_id = fields.Many2one(
        "llm.model",
        string="Modelo",
        ondelete="cascade",
    )
    model_name_pattern = fields.Char(
        string="Patrón de nombre",
        help="Subcadena en minúsculas que debe contener el nombre del modelo.",
    )
    cap_usd = fields.Float(
        string="Tope mensual USD",
        digits=(16, 4),
        required=True,
        default=10.0,
    )
    alert_ratio = fields.Float(
        string="Ratio aviso",
        default=0.80,
        help="Cuando el consumo del mes supera este ratio del tope, avisa en chat.",
    )
    block_when_exceeded = fields.Boolean(
        string="Bloquear al superar",
        default=True,
        help="Si está activo, no permite continuar el chat al superar el tope.",
    )
    year_month = fields.Char(
        string="Mes específico (YYYY-MM)",
        help="Si se deja vacío, aplica a cualquier mes (es persistente).",
    )

    consumed_usd_current = fields.Float(
        string="Consumido mes actual (USD)",
        compute="_compute_consumed_usd_current",
        digits=(16, 8),
    )
    ratio_current = fields.Float(
        string="Consumo actual / tope",
        compute="_compute_consumed_usd_current",
    )

    @api.depends("scope", "model_id", "model_name_pattern", "cap_usd")
    def _compute_name(self):
        for rec in self:
            if rec.scope == "model" and rec.model_id:
                label = rec.model_id.name
            elif rec.scope == "pattern":
                label = "patrón «%s»" % (rec.model_name_pattern or "")
            else:
                label = "global"
            rec.name = "Tope %s: %.2f USD/mes" % (label, rec.cap_usd or 0.0)

    def _matches_model_name(self, name):
        self.ensure_one()
        if self.scope == "global":
            return True
        if self.scope == "model":
            return bool(self.model_id and self.model_id.name == name)
        pat = (self.model_name_pattern or "").strip().lower()
        return bool(pat) and pat in (name or "").lower()

    def _compute_consumed_usd_current(self):
        Line = self.env["llm.thread.cost.line"].sudo()
        today = datetime.utcnow()
        ym = today.strftime("%Y-%m")
        for rec in self:
            rec.consumed_usd_current = 0.0
            rec.ratio_current = 0.0
            domain = [("year_month", "=", ym)]
            if rec.scope == "model" and rec.model_id:
                domain.append(("model_name_snapshot", "=", rec.model_id.name))
            elif rec.scope == "pattern" and rec.model_name_pattern:
                domain.append(
                    ("model_name_snapshot", "ilike", rec.model_name_pattern)
                )
            # Para scope=global, no añade filtro de modelo
            lines = Line.search(domain)
            total = sum(lines.mapped("cost_usd_delta") or [0.0])
            rec.consumed_usd_current = total
            if rec.cap_usd:
                rec.ratio_current = total / rec.cap_usd

    @api.model
    def enforce_before_generate(self, llm_thread):
        """Lanza UserError si la petición actual excedería algún tope aplicable.

        Se llama justo antes de enviar la petición al proveedor.
        """
        if not llm_thread or not llm_thread.model_id:
            return
        today = datetime.utcnow()
        ym = today.strftime("%Y-%m")
        model_name = llm_thread.model_id.name or ""
        caps = self.sudo().search(
            [
                ("active", "=", True),
                ("block_when_exceeded", "=", True),
                "|",
                ("year_month", "=", False),
                ("year_month", "=", ym),
            ]
        )
        if not caps:
            return
        Line = self.env["llm.thread.cost.line"].sudo()
        base_domain = [("year_month", "=", ym)]
        # Solo una consulta agregada mínima por tope:
        for cap in caps:
            if not cap._matches_model_name(model_name):
                continue
            domain = list(base_domain)
            if cap.scope == "model" and cap.model_id:
                domain.append(("model_name_snapshot", "=", cap.model_id.name))
            elif cap.scope == "pattern" and cap.model_name_pattern:
                domain.append(
                    ("model_name_snapshot", "ilike", cap.model_name_pattern)
                )
            consumed = sum(Line.search(domain).mapped("cost_usd_delta") or [0.0])
            if consumed >= (cap.cap_usd or 0.0) > 0:
                raise UserError(
                    _(
                        "Tope mensual alcanzado para %(label)s: "
                        "%(consumed).4f USD consumidos, tope %(cap).2f USD "
                        "(mes %(ym)s). Contacta con el administrador para ampliar "
                        "el tope o desactivar el bloqueo."
                    )
                    % {
                        "label": cap.name,
                        "consumed": consumed,
                        "cap": cap.cap_usd,
                        "ym": ym,
                    }
                )
