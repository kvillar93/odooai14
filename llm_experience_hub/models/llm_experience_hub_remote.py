# -*- coding: utf-8 -*-
import json
import logging
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urljoin
from urllib.request import Request, urlopen

from odoo import api, fields, models

_logger = logging.getLogger(__name__)


class LlmExperienceHubRemote(models.Model):
    _name = "llm.experience.hub.remote"
    _description = "Instancia Odoo remota con llm_experience (sincronización de costes)"

    name = fields.Char(string="Nombre", required=True)
    active = fields.Boolean(default=True)
    base_url = fields.Char(
        string="URL base",
        required=True,
        help="Ej.: https://mi-cliente.odoo.com (sin barra final).",
    )
    api_token = fields.Char(
        string="Token API",
        required=True,
        groups="base.group_system",
        help="Debe coincidir con el parámetro llm_experience.hub_sync_token en el servidor remoto.",
    )
    last_sync_at = fields.Datetime(string="Última sincronización", readonly=True)
    last_sync_error = fields.Text(string="Último error", readonly=True)
    remote_database_uuid = fields.Char(
        string="UUID base remota (última respuesta)",
        readonly=True,
    )
    thread_count = fields.Integer(
        string="Chats importados",
        compute="_compute_counts",
    )
    line_count = fields.Integer(
        string="Líneas de coste importadas",
        compute="_compute_counts",
    )

    thread_ids = fields.One2many(
        "llm.experience.hub.remote.thread",
        "remote_id",
        string="Chats remotos",
    )
    line_ids = fields.One2many(
        "llm.experience.hub.remote.line",
        "remote_id",
        string="Líneas remotas",
    )

    def _compute_counts(self):
        Thread = self.env["llm.experience.hub.remote.thread"]
        Line = self.env["llm.experience.hub.remote.line"]
        for rec in self:
            rec.thread_count = Thread.search_count([("remote_id", "=", rec.id)])
            rec.line_count = Line.search_count([("remote_id", "=", rec.id)])

    def _build_summary_url(self):
        self.ensure_one()
        return urljoin(self.base_url.rstrip("/") + "/", "llm_experience/api/cost/summary")

    def _http_get_json(self, params):
        self.ensure_one()
        url = self._build_summary_url()
        query = urlencode(params)
        full = f"{url}?{query}"
        req = Request(
            full,
            headers={"User-Agent": "Odoo-llm-experience-hub/16"},
            method="GET",
        )
        with urlopen(req, timeout=120) as resp:
            raw = resp.read().decode("utf-8")
        return json.loads(raw)

    def _since_param(self):
        self.ensure_one()
        if not self.last_sync_at:
            return None
        dt = self.last_sync_at
        if isinstance(dt, str):
            dt = fields.Datetime.from_string(dt)
        return dt.strftime("%Y-%m-%dT%H:%M:%S.%f") + "Z"

    def action_sync_now(self):
        """Sincroniza solo esta instancia (botón manual)."""
        for rec in self:
            rec._sync_one()
        return True

    @api.model
    def cron_sync_all_remotes(self):
        """Cron: sincroniza todas las instancias activas."""
        remotes = self.search([("active", "=", True)])
        for rec in remotes:
            rec._sync_one()
        return True

    def _sync_one(self):
        self.ensure_one()
        params = {"token": self.api_token}
        since = self._since_param()
        if since:
            params["since"] = since
        try:
            data = self._http_get_json(params)
        except HTTPError as e:
            msg = "HTTP %s: %s" % (e.code, e.reason)
            self.write({"last_sync_error": msg})
            _logger.warning("Hub sync %s: %s", self.name, msg)
            return
        except (URLError, TimeoutError, ValueError, json.JSONDecodeError) as e:
            self.write({"last_sync_error": repr(e)})
            _logger.exception("Hub sync %s", self.name)
            return

        if not data.get("ok"):
            self.write({"last_sync_error": json.dumps(data)})
            return

        self._apply_payload(data)
        self.write(
            {
                "last_sync_at": fields.Datetime.now(),
                "last_sync_error": False,
                "remote_database_uuid": data.get("database_uuid") or "",
            }
        )

    def _apply_payload(self, data):
        self.ensure_one()
        Thread = self.env["llm.experience.hub.remote.thread"].sudo()
        Line = self.env["llm.experience.hub.remote.line"].sudo()

        for t in data.get("threads") or []:
            rid = int(t["id"])
            existing = Thread.search(
                [("remote_id", "=", self.id), ("remote_thread_id", "=", rid)],
                limit=1,
            )
            vals = {
                "remote_id": self.id,
                "remote_thread_id": rid,
                "name": t.get("name") or "",
                "remote_user_id": t.get("user_id"),
                "remote_write_date": t.get("write_date"),
                "usage_cost_usd_total": t.get("usage_cost_usd_total") or 0.0,
                "usage_cost_currency": t.get("usage_cost_currency") or "USD",
                "usage_billable_accumulated": int(t.get("usage_billable_accumulated") or 0),
                "remote_model_name": t.get("model_name") or "",
            }
            if existing:
                existing.write(vals)
            else:
                Thread.create(vals)

        for ln in data.get("cost_lines") or []:
            lid = int(ln["id"])
            if Line.search_count(
                [("remote_id", "=", self.id), ("remote_line_id", "=", lid)]
            ):
                continue
            Line.create(
                {
                    "remote_id": self.id,
                    "remote_line_id": lid,
                    "remote_thread_id": int(ln.get("thread_id") or 0),
                    "remote_create_date": ln.get("create_date"),
                    "prompt_tokens": int(ln.get("prompt_tokens") or 0),
                    "output_tokens": int(ln.get("output_tokens") or 0),
                    "cached_tokens": int(ln.get("cached_tokens") or 0),
                    "cost_usd_delta": float(ln.get("cost_usd_delta") or 0.0),
                    "cumulative_usd_total": float(ln.get("cumulative_usd_total") or 0.0),
                    "model_name_snapshot": ln.get("model_name_snapshot") or "",
                }
            )


class LlmExperienceHubRemoteThread(models.Model):
    _name = "llm.experience.hub.remote.thread"
    _description = "Chat remoto (snapshot de coste)"
    _order = "remote_write_date desc, id desc"

    remote_id = fields.Many2one(
        "llm.experience.hub.remote",
        string="Instancia",
        required=True,
        ondelete="cascade",
        index=True,
    )
    remote_thread_id = fields.Integer(string="ID hilo remoto", required=True, index=True)
    name = fields.Char(string="Nombre")
    remote_user_id = fields.Integer(string="Usuario remoto (ID)")
    remote_write_date = fields.Char(string="Última escritura (remoto)")
    usage_cost_usd_total = fields.Float(
        string="Coste USD acumulado",
        digits=(16, 8),
    )
    usage_cost_currency = fields.Char(default="USD")
    usage_billable_accumulated = fields.Integer(string="Tokens acumulados")
    remote_model_name = fields.Char(string="Modelo (remoto)")

    _sql_constraints = [
        (
            "hub_remote_thread_unique",
            "unique(remote_id, remote_thread_id)",
            "Ya existe este chat remoto para la instancia.",
        ),
    ]


class LlmExperienceHubRemoteLine(models.Model):
    _name = "llm.experience.hub.remote.line"
    _description = "Línea de coste importada desde remoto"
    _order = "id desc"

    remote_id = fields.Many2one(
        "llm.experience.hub.remote",
        string="Instancia",
        required=True,
        ondelete="cascade",
        index=True,
    )
    remote_line_id = fields.Integer(string="ID línea remota", required=True, index=True)
    remote_thread_id = fields.Integer(string="ID hilo remoto", index=True)
    remote_create_date = fields.Char(string="Fecha creación (remoto)")
    prompt_tokens = fields.Integer()
    output_tokens = fields.Integer()
    cached_tokens = fields.Integer()
    cost_usd_delta = fields.Float(digits=(16, 8))
    cumulative_usd_total = fields.Float(digits=(16, 8))
    model_name_snapshot = fields.Char()

    _sql_constraints = [
        (
            "hub_remote_line_unique",
            "unique(remote_id, remote_line_id)",
            "Esta línea de coste ya fue importada.",
        ),
    ]
