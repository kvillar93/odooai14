# -*- coding: utf-8 -*-
import logging

from odoo import _, api, fields, models

_logger = logging.getLogger(__name__)


class LLMThread(models.Model):
    _inherit = "llm.thread"

    # --- Persistencia uso / contexto ---
    usage_context_window = fields.Integer(
        string="Límite de contexto (tokens)",
        default=0,
        help="Copia del límite del modelo activo; se sincroniza al cambiar modelo.",
    )
    usage_soft_limit_ratio = fields.Float(string="Umbral aviso (ratio)", default=0.80)
    usage_hard_limit_ratio = fields.Float(string="Umbral compactación (ratio)", default=0.92)
    usage_live_tokens = fields.Integer(string="Contexto vivo estimado (tokens)", default=0)
    usage_billable_accumulated = fields.Integer(string="Tokens facturables acumulados", default=0)
    usage_last_prompt_tokens = fields.Integer(default=0)
    usage_last_output_tokens = fields.Integer(default=0)
    usage_last_cached_tokens = fields.Integer(default=0)
    usage_last_thoughts_tokens = fields.Integer(default=0)
    usage_last_total_tokens = fields.Integer(default=0)
    usage_last_estimated_prompt = fields.Integer(
        string="Última estimación pre-request (tokens)", default=0
    )
    usage_metadata_json = fields.Json(string="Último usage_metadata crudo")
    usage_compaction_count = fields.Integer(default=0)
    usage_compaction_summary = fields.Text(
        string="Resumen compactado del historial antiguo",
        help="Inyectado como contexto de sistema tras compactación.",
    )
    usage_compaction_meta_json = fields.Json(string="Metadatos última compactación")

    usage_cost_usd_total = fields.Float(
        string="Coste estimado acumulado (USD)",
        digits=(16, 8),
        default=0.0,
        help="Suma de costes estimados por turno según tarifas Gemini (llm.gemini.pricing.rate).",
    )
    usage_cost_currency = fields.Char(
        string="Moneda coste",
        default="USD",
        size=8,
    )
    cost_line_ids = fields.One2many(
        "llm.thread.cost.line",
        "thread_id",
        string="Líneas de coste",
    )

    chat_work_mode = fields.Selection(
        [
            ("normal", "Respuesta normal"),
            ("deep_thinking", "Pensamiento profundo"),
            ("deep_research", "Investigación profunda"),
        ],
        string="Modo de trabajo",
        default="normal",
        help="Pensamiento profundo: mayor presupuesto de razonamiento Gemini. "
        "Investigación profunda: plan multi-paso con herramientas (orquestador).",
    )

    gemini_thinking_budget = fields.Integer(
        string="Presupuesto thinking (Gemini)",
        default=8192,
        help="Solo modo pensamiento profundo. 0 desactiva thinking extra.",
    )

    chat_work_mode_selector_enabled = fields.Boolean(
        string="Permitir selector de modo de trabajo en el chat",
        default=True,
        help=(
            "Si está activo, el usuario puede cambiar entre respuesta normal, "
            "pensamiento profundo e investigación profunda desde la barra del compositor."
        ),
    )

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        for rec in records:
            rec._usage_sync_context_window_from_model()
        return records

    def write(self, vals):
        res = super().write(vals)
        if "model_id" in vals:
            for rec in self:
                rec._usage_sync_context_window_from_model()
        return res

    def _usage_sync_context_window_from_model(self):
        self.ensure_one()
        if self.model_id and self.model_id.context_window_tokens:
            cw = self.model_id.context_window_tokens
            if self.usage_context_window != cw:
                self.with_context(skip_usage_sync=True).write({"usage_context_window": cw})

    def _get_extra_prepend_messages(self):
        """Inyecta resumen tras compactación (llama hook de llm_assistant)."""
        msgs = super()._get_extra_prepend_messages()
        if self.usage_compaction_summary:
            msgs.append(
                {
                    "role": "system",
                    "content": _(
                        "Resumen del historial anterior (compactado para ahorrar contexto):\n%s"
                    )
                    % (self.usage_compaction_summary,),
                }
            )
        return msgs

    def usage_apply_gemini_estimated_prompt(self, estimated_tokens):
        """Actualiza estimación previa al request (count_tokens)."""
        self.ensure_one()
        self.write({"usage_last_estimated_prompt": int(max(0, estimated_tokens))})
        self._usage_recompute_live_from_parts()

    def usage_apply_gemini_response(self, usage_dict):
        """Tras cada respuesta Gemini (usage_metadata normalizado)."""
        self.ensure_one()
        vals = {
            "usage_last_prompt_tokens": usage_dict.get("prompt", 0),
            "usage_last_output_tokens": usage_dict.get("output", 0),
            "usage_last_cached_tokens": usage_dict.get("cached", 0),
            "usage_last_thoughts_tokens": usage_dict.get("thoughts", 0),
            "usage_last_total_tokens": usage_dict.get("total", 0),
            "usage_metadata_json": usage_dict,
        }
        total = int(usage_dict.get("total") or 0)
        self.write(vals)
        self._usage_recompute_live_from_parts()
        if total:
            self.write(
                {
                    "usage_billable_accumulated": self.usage_billable_accumulated + total,
                }
            )
        self._usage_apply_cost_line(usage_dict)
        self._usage_maybe_compact()

    def _usage_apply_cost_line(self, usage_dict):
        """Registra coste USD del turno y línea de seguimiento."""
        self.ensure_one()
        if not self.model_id:
            return
        rate = self.env["llm.gemini.pricing.rate"].get_rate_for_llm_model(
            self.model_id
        )
        if not rate:
            return
        prompt = int(usage_dict.get("prompt") or 0)
        output = int(usage_dict.get("output") or 0)
        cached = int(usage_dict.get("cached") or 0)
        cost = (prompt / 1e6) * (rate.input_usd_per_million or 0.0)
        cost += (output / 1e6) * (rate.output_usd_per_million or 0.0)
        cost += (cached / 1e6) * (rate.cached_input_usd_per_million or 0.0)
        if cost <= 0 and (prompt + output + cached) <= 0:
            return
        prev = float(self.usage_cost_usd_total or 0.0)
        new_total = prev + cost
        self.write({"usage_cost_usd_total": new_total})
        self.env["llm.thread.cost.line"].create(
            {
                "thread_id": self.id,
                "prompt_tokens": prompt,
                "output_tokens": output,
                "cached_tokens": cached,
                "cost_usd_delta": cost,
                "cumulative_usd_total": new_total,
                "pricing_rate_id": rate.id,
                "model_name_snapshot": self.model_id.name,
            }
        )

    def _usage_recompute_live_from_parts(self):
        """Contexto vivo ≈ estimación última petición + margen (historial en servidor)."""
        self.ensure_one()
        # Aproximación: max(último total reportado, última estimación pre-flight)
        live = max(
            self.usage_last_estimated_prompt or 0,
            self.usage_last_total_tokens or 0,
            (self.usage_last_prompt_tokens or 0) + (self.usage_last_output_tokens or 0),
        )
        # Si hay resumen compactado, sumar tokens aproximados del texto
        if self.usage_compaction_summary:
            live += max(500, len(self.usage_compaction_summary) // 4)
        self.usage_live_tokens = int(live)

    def _usage_maybe_compact(self):
        """Compactación automática al superar hard limit."""
        self.ensure_one()
        limit = self.usage_context_window or self.model_id.context_window_tokens or 1_000_000
        if limit <= 0:
            return
        ratio = (self.usage_live_tokens or 0) / float(limit)
        hard = self.usage_hard_limit_ratio or 0.92
        if ratio < hard:
            return
        try:
            self._usage_run_compaction()
        except Exception as err:
            _logger.exception("Compactación contexto: %s", err)

    def _usage_run_compaction(self):
        """Genera resumen del historial antiguo y notifica en el hilo."""
        self.ensure_one()
        msgs = self.env["mail.message"].search(
            [
                ("model", "=", self._name),
                ("res_id", "=", self.id),
                ("llm_role", "in", ("user", "assistant", "tool")),
            ],
            order="id asc",
            limit=200,
        )
        if len(msgs) < 6:
            return
        # Partir: conservar últimos 4 mensajes íntegros, resumir el resto
        old = msgs[:-4]
        lines = []
        for m in old:
            role = m.llm_role or "?"
            body = (m.body or "")[:1200]
            lines.append(f"[{role}] {body}")
        blob = "\n".join(lines)
        prompt = _(
            "Resume en viñetas concisas (español) decisiones, datos Odoo y errores relevantes. "
            "Omite saludos. Texto:\n%s"
        ) % blob[:24000]

        summary = ""
        try:
            out = self.sudo().provider_id.chat(
                messages=[{"role": "user", "content": prompt}],
                model=self.model_id,
                stream=False,
            )
            if isinstance(out, dict):
                summary = (out.get("content") or "").strip()
        except Exception as err:
            _logger.warning("No se pudo resumir con el modelo: %s", err)
            summary = blob[:4000] + "…"

        if not summary:
            return

        self.write(
            {
                "usage_compaction_summary": summary,
                "usage_compaction_count": self.usage_compaction_count + 1,
                "usage_compaction_meta_json": {
                    "messages_summarized": len(old),
                    "kept_recent": 4,
                },
                "usage_live_tokens": int((self.usage_live_tokens or 0) * 0.45),
            }
        )
        self.message_post(
            body=_(
                "<p><em>El contexto antiguo fue compactado para continuar la conversación "
                "dentro del límite del modelo.</em></p>"
            ),
            message_type="comment",
            subtype_xmlid="mail.mt_note",
        )

    def get_usage_meter_payload(self):
        """JSON para el medidor web."""
        self.ensure_one()
        self._usage_sync_context_window_from_model()
        limit = self.usage_context_window or self.model_id.context_window_tokens or 1_000_000
        live = int(self.usage_live_tokens or 0)
        ratio = (live / float(limit)) if limit else 0.0
        soft = self.usage_soft_limit_ratio or 0.80
        hard = self.usage_hard_limit_ratio or 0.92
        if ratio >= hard:
            state = "critical"
        elif ratio >= soft:
            state = "warning"
        else:
            state = "normal"
        return {
            "limit": limit,
            "live": live,
            "ratio": round(ratio, 4),
            "state": state,
            "soft_ratio": soft,
            "hard_ratio": hard,
            "last": {
                "prompt": self.usage_last_prompt_tokens,
                "output": self.usage_last_output_tokens,
                "cached": self.usage_last_cached_tokens,
                "thoughts": self.usage_last_thoughts_tokens,
                "total": self.usage_last_total_tokens,
                "estimated_prompt": self.usage_last_estimated_prompt,
            },
            "billable_accumulated": self.usage_billable_accumulated,
            "compaction_count": self.usage_compaction_count,
            "work_mode": self.chat_work_mode,
            "work_mode_selector_enabled": self.chat_work_mode_selector_enabled,
            "cost_usd_total": round(self.usage_cost_usd_total or 0.0, 8),
            "cost_currency": self.usage_cost_currency or "USD",
        }

    @api.model
    def experience_meter_rpc(self, thread_id):
        """RPC seguro para el medidor web."""
        thread = self.env["llm.thread"].browse(int(thread_id))
        if not thread.exists() or thread.user_id.id != self.env.user.id:
            return {"error": "forbidden"}
        return thread.get_usage_meter_payload()

    def experience_set_work_mode(self, mode):
        """Persiste modo de trabajo (normal | deep_thinking | deep_research)."""
        self.ensure_one()
        if self.user_id.id != self.env.user.id:
            return False
        if mode not in ("normal", "deep_thinking", "deep_research"):
            return False
        self.write({"chat_work_mode": mode})
        return True
