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
        ondelete="set null",
        index=True,
        help="Si el chat se elimina, el registro de coste se conserva para auditoría.",
    )
    thread_id_snapshot = fields.Integer(
        string="ID chat (instantánea)",
        index=True,
        help="ID original del chat en el momento de creación; no cambia aunque se borre el chat.",
    )
    thread_name_snapshot = fields.Char(
        string="Nombre chat (instantánea)",
        help="Nombre del chat en el momento de creación.",
    )
    user_id_snapshot = fields.Many2one(
        "res.users",
        string="Usuario (instantánea)",
        ondelete="set null",
    )
    thread_deleted = fields.Boolean(
        string="Chat eliminado",
        compute="_compute_thread_deleted",
        store=True,
    )
    display_thread_name = fields.Char(
        string="Chat",
        compute="_compute_display_thread_name",
        store=False,
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
    provider_name_snapshot = fields.Char(string="Proveedor (instantánea)")
    year_month = fields.Char(
        string="Mes (YYYY-MM)",
        compute="_compute_year_month",
        store=True,
        index=True,
    )

    @api.depends("create_date")
    def _compute_year_month(self):
        for rec in self:
            if rec.create_date:
                rec.year_month = rec.create_date.strftime("%Y-%m")
            else:
                rec.year_month = False

    @api.depends("thread_id", "thread_id_snapshot")
    def _compute_thread_deleted(self):
        for rec in self:
            rec.thread_deleted = bool(rec.thread_id_snapshot) and not rec.thread_id

    def _compute_display_thread_name(self):
        for rec in self:
            if rec.thread_id:
                rec.display_thread_name = rec.thread_id.name or (
                    "Chat #%s" % rec.thread_id.id
                )
            elif rec.thread_name_snapshot:
                rec.display_thread_name = "%s (eliminado)" % rec.thread_name_snapshot
            elif rec.thread_id_snapshot:
                rec.display_thread_name = "Chat #%s (eliminado)" % rec.thread_id_snapshot
            else:
                rec.display_thread_name = ""
