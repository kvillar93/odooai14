# -*- coding: utf-8 -*-
import logging

from odoo import _, api, fields, models

from .llm_reasoning import (
    ANTHROPIC_THINKING_BUDGETS,
    DEFAULT_REASONING_EFFORT,
    REASONING_EFFORT_DESCRIPTIONS,
    REASONING_EFFORT_SELECTION,
    normalize_reasoning_effort,
)

_logger = logging.getLogger(__name__)

_DEFAULT_CONTEXT_WINDOW = 1_048_576
_DEFAULT_CHARS_PER_TOKEN = 3.5


class LLMThread(models.Model):
    _inherit = "llm.thread"

    # --- Persistencia uso / contexto ---
    usage_context_window = fields.Integer(
        string="Límite de contexto (tokens)",
        default=0,
        help="Copia del límite del modelo activo; se sincroniza al cambiar modelo.",
    )
    usage_soft_limit_ratio = fields.Float(
        string="Umbral aviso (ratio, obsoleto)",
        default=0.80,
        help="Obsoleto: usar el parámetro llm_experience.warning_ratio.",
    )
    usage_hard_limit_ratio = fields.Float(
        string="Umbral compactación (ratio, obsoleto)",
        default=0.92,
        help="Obsoleto: usar el parámetro llm_experience.compaction_ratio.",
    )
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
    usage_last_request_chars = fields.Integer(
        string="Caracteres de la última petición",
        default=0,
        help="Tamaño local de la última petición; con el uso real calibra la estimación.",
    )
    usage_chars_per_token = fields.Float(
        string="Caracteres por token (calibrado)",
        default=_DEFAULT_CHARS_PER_TOKEN,
        digits=(6, 3),
    )
    usage_total_input_tokens = fields.Integer(string="Tokens de entrada (total)", default=0)
    usage_total_output_tokens = fields.Integer(string="Tokens de salida (total)", default=0)
    usage_total_thoughts_tokens = fields.Integer(
        string="Tokens de razonamiento (total)", default=0
    )
    usage_total_cached_tokens = fields.Integer(string="Tokens en caché (total)", default=0)
    usage_request_count = fields.Integer(string="Peticiones al modelo", default=0)
    usage_metadata_json = fields.Json(string="Último usage_metadata crudo")
    usage_breakdown_json = fields.Json(
        string="Composición del contexto (tokens estimados)",
        help="Sistema, resumen, herramientas e historial de la última petición.",
    )
    usage_needs_compaction = fields.Boolean(
        string="Resumir antes de la próxima petición",
        default=False,
    )
    usage_compaction_count = fields.Integer(default=0)
    usage_compaction_summary = fields.Text(
        string="Resumen compactado del historial antiguo",
        help="Inyectado como contexto de sistema tras compactación.",
    )
    usage_compaction_meta_json = fields.Json(string="Metadatos última compactación")
    usage_last_compaction_date = fields.Datetime(string="Último resumen de contexto")
    context_cutoff_message_id = fields.Integer(
        string="Corte de contexto (id de mensaje)",
        default=0,
        help="Los mensajes con id menor o igual ya están incluidos en el resumen "
        "y no se reenvían al modelo.",
    )

    usage_cost_usd_total = fields.Float(
        string="Coste estimado acumulado (USD)",
        digits=(16, 8),
        default=0.0,
        help="Suma de costes estimados por turno según tarifas (llm.gemini.pricing.rate).",
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
            ("deep_thinking", "Pensamiento profundo (obsoleto)"),
            ("deep_research", "Investigación profunda"),
        ],
        string="Modo de trabajo",
        default="normal",
        help="Investigación profunda: plan multi-paso con herramientas. "
        "El nivel de razonamiento se elige con «Esfuerzo de razonamiento».",
    )
    reasoning_effort = fields.Selection(
        REASONING_EFFORT_SELECTION,
        string="Esfuerzo de razonamiento",
        help="Cuánto razona el modelo antes de responder. Cada proveedor lo traduce "
        "a su parámetro nativo (thinking_level, thinking budget, reasoning_effort).",
    )
    experience_research_plan = fields.Text(
        string="Plan de investigación vigente",
    )

    gemini_thinking_budget = fields.Integer(
        string="Presupuesto thinking (Gemini, obsoleto)",
        default=8192,
        help="Obsoleto: el razonamiento se controla con «Esfuerzo de razonamiento».",
    )

    chat_work_mode_selector_enabled = fields.Boolean(
        string="Permitir selector de razonamiento en el chat",
        default=True,
        help=(
            "Si está activo, el usuario puede cambiar el esfuerzo de razonamiento "
            "y la investigación profunda desde la barra del compositor."
        ),
    )

    # ------------------------------------------------------------------
    # ORM
    # ------------------------------------------------------------------

    @api.model
    def _experience_map_legacy_vals(self, vals):
        """``chat_work_mode='deep_thinking'`` (código antiguo) → esfuerzo alto."""
        if vals.get("chat_work_mode") == "deep_thinking":
            vals = dict(vals, chat_work_mode="normal")
            vals.setdefault("reasoning_effort", "high")
        return vals

    @api.model_create_multi
    def create(self, vals_list):
        vals_list = [self._experience_map_legacy_vals(v) for v in vals_list]
        records = super().create(vals_list)
        for rec in records:
            rec._usage_sync_context_window_from_model()
            if not rec.reasoning_effort:
                rec.reasoning_effort = (
                    rec.model_id.default_reasoning_effort or DEFAULT_REASONING_EFFORT
                )
        return records

    def write(self, vals):
        vals = self._experience_map_legacy_vals(vals)
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
        """Inyecta el resumen acumulado del contexto anterior."""
        msgs = super()._get_extra_prepend_messages()
        if self.usage_compaction_summary:
            msgs.append(
                {
                    "role": "system",
                    "content": _(
                        "Resumen de la conversación anterior (sustituye a los mensajes "
                        "antiguos para ahorrar contexto; trátalo como información ya "
                        "conocida y continúa a partir de ella):\n%s"
                    )
                    % (self.usage_compaction_summary,),
                }
            )
        return msgs

    # ------------------------------------------------------------------
    # Parámetros
    # ------------------------------------------------------------------

    @api.model
    def _experience_param_float(self, key, default):
        try:
            value = float(
                self.env["ir.config_parameter"].sudo().get_param(key) or default
            )
        except (TypeError, ValueError):
            return default
        return value

    def _usage_context_budget(self):
        """Tokens que representan el 100 % del medidor (presupuesto de trabajo)."""
        self.ensure_one()
        model = self.model_id
        window = (model.context_window_tokens if model else 0) or _DEFAULT_CONTEXT_WINDOW
        budget = (model.context_budget_tokens if model else 0) or window
        return min(budget, window)

    def _usage_compaction_ratio(self):
        ratio = self._experience_param_float("llm_experience.compaction_ratio", 0.85)
        return min(0.98, max(0.3, ratio))

    def _usage_warning_ratio(self):
        ratio = self._experience_param_float("llm_experience.warning_ratio", 0.70)
        return min(self._usage_compaction_ratio(), max(0.1, ratio))

    def _usage_compaction_threshold(self):
        return int(self._usage_context_budget() * self._usage_compaction_ratio())

    def _experience_effective_reasoning_effort(self):
        self.ensure_one()
        return normalize_reasoning_effort(self.reasoning_effort)

    def _experience_show_thinking(self):
        """Pedir al modelo resúmenes de su razonamiento para mostrarlos en el chat."""
        self.ensure_one()
        if self._experience_effective_reasoning_effort() == "instant":
            return False
        value = (
            self.env["ir.config_parameter"]
            .sudo()
            .get_param("llm_experience.show_thinking", "1")
        )
        return str(value).strip().lower() not in ("0", "false", "no", "off", "")

    # ------------------------------------------------------------------
    # Contabilidad de uso
    # ------------------------------------------------------------------

    def usage_apply_gemini_estimated_prompt(self, estimated_tokens):
        """Compatibilidad: estimación previa al request."""
        self.ensure_one()
        self.write({"usage_last_estimated_prompt": int(max(0, estimated_tokens))})

    def usage_apply_gemini_response(self, usage_dict):
        """Compatibilidad: Gemini informa ``prompt`` con la caché incluida."""
        usage = dict(usage_dict or {})
        usage.setdefault("prompt_includes_cached", True)
        return self.usage_apply_llm_response(usage)

    @api.model
    def _usage_normalize(self, usage_dict):
        """Dict de uso unificado.

        Entrada: ``prompt``, ``cached``, ``output``, ``thoughts``, ``total`` y
        ``prompt_includes_cached`` (Gemini True; Anthropic False).
        """
        if not usage_dict:
            return None

        def _int(key):
            try:
                return int(usage_dict.get(key) or 0)
            except (TypeError, ValueError):
                return 0

        prompt = _int("prompt")
        cached = _int("cached")
        output = _int("output")
        thoughts = _int("thoughts")
        includes_cached = usage_dict.get("prompt_includes_cached", True)
        prompt_total = prompt if includes_cached else prompt + cached
        uncached = max(0, prompt - cached) if includes_cached else prompt
        total = _int("total") or (prompt_total + output + thoughts)
        if not (prompt_total or output or thoughts):
            return None
        return {
            "prompt": prompt_total,
            "uncached": uncached,
            "cached": cached,
            "output": output,
            "thoughts": thoughts,
            "total": total,
            # Lo que ocupará en la próxima petición: entrada + respuesta
            # (el razonamiento no se reenvía).
            "context": prompt_total + output,
        }

    def usage_apply_llm_response(self, usage_dict):
        """Aplica el uso de una respuesta (cualquier proveedor)."""
        self.ensure_one()
        u = self._usage_normalize(usage_dict)
        if not u:
            return
        vals = {
            "usage_total_input_tokens": self.usage_total_input_tokens + u["prompt"],
            "usage_total_output_tokens": self.usage_total_output_tokens + u["output"],
            "usage_total_thoughts_tokens": self.usage_total_thoughts_tokens + u["thoughts"],
            "usage_total_cached_tokens": self.usage_total_cached_tokens + u["cached"],
            "usage_request_count": self.usage_request_count + 1,
            "usage_billable_accumulated": self.usage_billable_accumulated + u["total"],
        }
        if not self.env.context.get("llm_compaction_call"):
            vals.update(
                {
                    "usage_last_prompt_tokens": u["prompt"],
                    "usage_last_output_tokens": u["output"],
                    "usage_last_cached_tokens": u["cached"],
                    "usage_last_thoughts_tokens": u["thoughts"],
                    "usage_last_total_tokens": u["total"],
                    "usage_metadata_json": dict(usage_dict),
                    "usage_live_tokens": u["context"],
                }
            )
            if self.usage_last_request_chars and u["prompt"] > 0:
                observed = self.usage_last_request_chars / float(u["prompt"])
                calibrated = 0.5 * (
                    self.usage_chars_per_token or _DEFAULT_CHARS_PER_TOKEN
                ) + 0.5 * observed
                vals["usage_chars_per_token"] = min(8.0, max(1.0, calibrated))
                vals["usage_last_request_chars"] = 0
            if u["context"] >= self._usage_compaction_threshold():
                vals["usage_needs_compaction"] = True
        self.write(vals)
        self._usage_apply_cost_line(u)

    def _usage_apply_cost_line(self, usage):
        """Registra coste USD del turno y línea de seguimiento.

        Coste = entrada sin caché × tarifa entrada + caché × tarifa caché
        + (salida + razonamiento) × tarifa salida.
        """
        self.ensure_one()
        if not self.model_id:
            return
        rate = self.env["llm.gemini.pricing.rate"].get_rate_for_llm_model(
            self.model_id
        )
        if not rate:
            return
        input_rate = rate.input_usd_per_million or 0.0
        cached_rate = rate.cached_input_usd_per_million or input_rate
        output_rate = rate.output_usd_per_million or 0.0
        cost = (usage["uncached"] / 1e6) * input_rate
        cost += (usage["cached"] / 1e6) * cached_rate
        cost += ((usage["output"] + usage["thoughts"]) / 1e6) * output_rate
        if cost <= 0:
            return
        new_total = float(self.usage_cost_usd_total or 0.0) + cost
        self.write({"usage_cost_usd_total": new_total})
        self.env["llm.thread.cost.line"].sudo().create(
            {
                "thread_id": self.id,
                "thread_id_snapshot": self.id,
                "thread_name_snapshot": self.name or "",
                "user_id_snapshot": self.user_id.id if self.user_id else False,
                "prompt_tokens": usage["prompt"],
                "output_tokens": usage["output"],
                "cached_tokens": usage["cached"],
                "thoughts_tokens": usage["thoughts"],
                "cost_usd_delta": cost,
                "cumulative_usd_total": new_total,
                "pricing_rate_id": rate.id,
                "model_name_snapshot": self.model_id.name,
                "provider_name_snapshot": (
                    self.provider_id.name if self.provider_id else ""
                ),
            }
        )

    # ------------------------------------------------------------------
    # Medidor web
    # ------------------------------------------------------------------

    def _experience_reasoning_note(self):
        """Aviso sobre cómo aplica el modelo actual los niveles de razonamiento."""
        self.ensure_one()
        service = self.provider_id.service if self.provider_id else ""
        name = (self.model_id.name or "").lower() if self.model_id else ""
        if service == "gemini":
            if "pro" in name:
                return _(
                    "Este modelo no permite desactivar el razonamiento: "
                    "«Instantáneo» usa el nivel mínimo disponible."
                )
            return ""
        if service == "anthropic":
            levels = [
                label
                for key, label in REASONING_EFFORT_SELECTION
                if not ANTHROPIC_THINKING_BUDGETS.get(key)
            ]
            return _("%s responden sin razonamiento extendido.") % " y ".join(levels)
        if service == "openai" and not (
            name.startswith("o") or name.startswith("gpt-5")
        ):
            return _("Este modelo no usa niveles de razonamiento.")
        return ""

    def get_usage_meter_payload(self):
        """JSON para el medidor web."""
        self.ensure_one()
        limit = self._usage_context_budget()
        live = int(self.usage_live_tokens or 0)
        ratio = (live / float(limit)) if limit else 0.0
        compaction_ratio = self._usage_compaction_ratio()
        warning_ratio = self._usage_warning_ratio()
        if ratio >= compaction_ratio or self.usage_needs_compaction:
            state = "critical"
        elif ratio >= warning_ratio:
            state = "warning"
        else:
            state = "normal"
        compaction_at = int(limit * compaction_ratio)
        effort = self._experience_effective_reasoning_effort()
        return {
            "limit": limit,
            "model_window": self.model_id.context_window_tokens if self.model_id else 0,
            "live": live,
            "ratio": round(ratio, 4),
            "state": state,
            "warning_ratio": warning_ratio,
            "compaction_ratio": compaction_ratio,
            "compaction_at": compaction_at,
            "tokens_until_compaction": max(0, compaction_at - live),
            "needs_compaction": bool(self.usage_needs_compaction),
            "last": {
                "prompt": self.usage_last_prompt_tokens,
                "output": self.usage_last_output_tokens,
                "cached": self.usage_last_cached_tokens,
                "thoughts": self.usage_last_thoughts_tokens,
                "total": self.usage_last_total_tokens,
                "estimated_prompt": self.usage_last_estimated_prompt,
            },
            "totals": {
                "input": self.usage_total_input_tokens,
                "output": self.usage_total_output_tokens,
                "thoughts": self.usage_total_thoughts_tokens,
                "cached": self.usage_total_cached_tokens,
                "requests": self.usage_request_count,
            },
            "breakdown": self._experience_breakdown_payload(),
            "billable_accumulated": self.usage_billable_accumulated,
            "compaction_count": self.usage_compaction_count,
            "last_compaction": fields.Datetime.to_string(self.usage_last_compaction_date)
            if self.usage_last_compaction_date
            else False,
            "reasoning_effort": effort,
            "reasoning_options": [
                {
                    "value": key,
                    "label": label,
                    "description": REASONING_EFFORT_DESCRIPTIONS.get(key, ""),
                }
                for key, label in REASONING_EFFORT_SELECTION
            ],
            "reasoning_note": self._experience_reasoning_note(),
            "deep_research": self.chat_work_mode == "deep_research",
            "work_mode": self.chat_work_mode,
            "work_mode_selector_enabled": self.chat_work_mode_selector_enabled,
            "model_name": self.model_id.name if self.model_id else "",
            "cost_usd_total": round(self.usage_cost_usd_total or 0.0, 8),
            "cost_currency": self.usage_cost_currency or "USD",
        }

    def _experience_breakdown_payload(self):
        """Segmentos del contexto para la barra de composición del medidor."""
        self.ensure_one()
        data = self.usage_breakdown_json or {}
        labels = [
            ("system", _("Instrucciones")),
            ("tools", _("Herramientas")),
            ("summary", _("Resumen")),
            ("history", _("Conversación")),
        ]
        total = sum(int(data.get(key) or 0) for key, _label in labels)
        if not total:
            return []
        return [
            {
                "key": key,
                "label": label,
                "tokens": int(data.get(key) or 0),
                "ratio": round(int(data.get(key) or 0) / float(total), 4),
            }
            for key, label in labels
            if data.get(key)
        ]

    @api.model
    def _experience_owned_thread(self, thread_id):
        thread = self.env["llm.thread"].browse(int(thread_id or 0))
        if not thread.exists() or thread.user_id.id != self.env.user.id:
            return None
        return thread

    @api.model
    def experience_meter_rpc(self, thread_id):
        """RPC seguro para el medidor web."""
        thread = self._experience_owned_thread(thread_id)
        if not thread:
            return {"error": "forbidden"}
        return thread.get_usage_meter_payload()

    @api.model
    def experience_set_reasoning_effort_rpc(self, thread_id, effort):
        """Guarda el esfuerzo del hilo y lo recuerda como preferencia del usuario."""
        thread = self._experience_owned_thread(thread_id)
        if not thread or effort not in dict(REASONING_EFFORT_SELECTION):
            return {"error": "forbidden"}
        thread.write({"reasoning_effort": effort})
        # Preferencia por usuario en ir.default (no en res.users): default_get la
        # aplica a los hilos nuevos y no exige columnas nuevas en una tabla que
        # se lee en cada petición (login, portal) aunque el módulo no esté actualizado.
        self.env["ir.default"].sudo().set(
            "llm.thread", "reasoning_effort", effort, user_id=self.env.user.id
        )
        return thread.get_usage_meter_payload()

    @api.model
    def experience_set_deep_research_rpc(self, thread_id, enabled):
        thread = self._experience_owned_thread(thread_id)
        if not thread:
            return {"error": "forbidden"}
        thread.write({"chat_work_mode": "deep_research" if enabled else "normal"})
        return thread.get_usage_meter_payload()

    @api.model
    def experience_compact_now_rpc(self, thread_id):
        """Resume el historial ahora (botón del medidor)."""
        thread = self._experience_owned_thread(thread_id)
        if not thread:
            return {"error": "forbidden"}
        with thread._generation_lock():
            note = thread._context_compact(reason="manual")
        payload = thread.get_usage_meter_payload()
        if note:
            payload["note_message"] = note.message_format()[0]
        else:
            payload["notice"] = _("No hay suficiente historial para resumir.")
        return payload

    @api.model
    def experience_reset_context_rpc(self, thread_id):
        """Empieza un contexto limpio en el mismo chat (sin resumen)."""
        thread = self._experience_owned_thread(thread_id)
        if not thread:
            return {"error": "forbidden"}
        with thread._generation_lock():
            note = thread._context_reset()
        payload = thread.get_usage_meter_payload()
        payload["note_message"] = note.message_format()[0]
        return payload

    def experience_set_work_mode(self, mode):
        """Compatibilidad: persiste modo de trabajo (normal | deep_research | deep_thinking)."""
        self.ensure_one()
        if self.user_id.id != self.env.user.id:
            return False
        if mode not in ("normal", "deep_thinking", "deep_research"):
            return False
        self.write({"chat_work_mode": mode})
        return True
