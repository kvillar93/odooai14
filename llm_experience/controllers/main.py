# -*- coding: utf-8 -*-
import json
import logging
from datetime import datetime

from odoo import http
from odoo.http import request

_logger = logging.getLogger(__name__)


class LlmExperienceCostController(http.Controller):
    @http.route(
        "/llm_experience/api/cost/summary",
        type="http",
        auth="public",
        methods=["GET"],
        csrf=False,
    )
    def cost_summary(self, token=None, since=None, **kwargs):
        """Resumen de costes por chat y líneas nuevas para el hub central.

        Parámetros:
        - token: debe coincidir con ir.config_parameter llm_experience.hub_sync_token
        - since: ISO8601 opcional; filtra líneas de coste creadas después de esta fecha.
        """
        icp = request.env["ir.config_parameter"].sudo()
        expected = (icp.get_param("llm_experience.hub_sync_token") or "").strip()
        if not expected or (token or "").strip() != expected:
            return request.make_json_response(
                {"error": "forbidden", "message": "Token inválido o no configurado."},
                status=403,
            )

        Thread = request.env["llm.thread"].sudo()
        Line = request.env["llm.thread.cost.line"].sudo()
        domain_threads = []
        since_dt = None
        if since:
            try:
                since_s = since.replace("Z", "+00:00")
                since_dt = datetime.fromisoformat(since_s)
            except (ValueError, TypeError):
                since_dt = None

        threads = Thread.search(domain_threads, order="write_date desc", limit=5000)
        thread_payload = []
        for t in threads:
            thread_payload.append(
                {
                    "id": t.id,
                    "name": t.name,
                    "user_id": t.user_id.id if t.user_id else None,
                    "write_date": t.write_date.isoformat() if t.write_date else None,
                    "model_id": t.model_id.id if t.model_id else None,
                    "model_name": t.model_id.name if t.model_id else None,
                    "usage_billable_accumulated": t.usage_billable_accumulated,
                    "usage_cost_usd_total": round(t.usage_cost_usd_total or 0.0, 8),
                    "usage_cost_currency": t.usage_cost_currency or "USD",
                }
            )

        line_domain = []
        if since_dt:
            line_domain = [("create_date", ">=", since_dt)]
        lines = Line.search(line_domain, order="id asc", limit=50000)
        line_payload = []
        for ln in lines:
            line_payload.append(
                {
                    "id": ln.id,
                    "thread_id": ln.thread_id.id,
                    "create_date": ln.create_date.isoformat() if ln.create_date else None,
                    "prompt_tokens": ln.prompt_tokens,
                    "output_tokens": ln.output_tokens,
                    "cached_tokens": ln.cached_tokens,
                    "cost_usd_delta": round(ln.cost_usd_delta or 0.0, 8),
                    "cumulative_usd_total": round(ln.cumulative_usd_total or 0.0, 8),
                    "model_name_snapshot": ln.model_name_snapshot,
                }
            )

        payload = {
            "ok": True,
            "generated_at": datetime.utcnow().isoformat() + "Z",
            "database_uuid": icp.get_param("database.uuid") or "",
            "threads": thread_payload,
            "cost_lines": line_payload,
        }
        return request.make_response(
            json.dumps(payload, default=str),
            headers=[("Content-Type", "application/json; charset=utf-8")],
        )
