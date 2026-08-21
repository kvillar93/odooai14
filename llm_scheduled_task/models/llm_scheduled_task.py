# -*- coding: utf-8 -*-
import json
import logging
import re
import time as _time

from dateutil.relativedelta import relativedelta

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError

_logger = logging.getLogger(__name__)

# Misma lógica que ir.cron para intervalos (alineación con nextcall)
_LLM_TASK_INTERVAL_DELTA = {
    "minutes": lambda n: relativedelta(minutes=n),
    "hours": lambda n: relativedelta(hours=n),
    "days": lambda n: relativedelta(days=n),
    "weeks": lambda n: relativedelta(days=7 * n),
    "months": lambda n: relativedelta(months=n),
}

# Herramientas obligatorias en cada hilo de tarea programada.
_REQUIRED_TASK_TOOL_NAMES = ("llm_task_status_reporter",)

# Máximo de reintentos del bucle de revisión post-ejecución cuando el
# modelo se "olvida" de enviar el correo o de cerrar con el reporter.
_MAX_REVIEW_ITERATIONS = 3

# Umbrales / señales para activar Pensamiento profundo (PP) automáticamente
# en tareas programadas complejas. Requiere llm_experience (campos
# chat_work_mode / gemini_thinking_budget en llm.thread).
_DEEP_THINKING_PROMPT_MIN_LEN = 700
_DEEP_THINKING_PLAN_MIN_STEPS = 4
_DEEP_THINKING_BUDGET_DEFAULT = 8192
_DEEP_THINKING_KEYWORDS = (
    "auditor", "informe", "análisis", "analisis", "analizar",
    "margen", "compar", "cruzar", "investig", "profund", "complej",
    "consolid", "calcular", "clasific", "ranking", "reporte",
    "excel", "pdf", "powerpoint", "artifact", "artefacto",
    "semanal", "mensual", "trimestral", "balance", "utilidad",
    "factur", "multi", "varios paso", "paso a paso", "detalle",
    "tablas", "html", "top ", "menor", "mayor", "umbrales",
)

# Reglas para inferir tools requeridas desde el prompt original. Si una
# de estas palabras aparece en el ``task_prompt``, esa tool DEBE haberse
# invocado durante la ejecución, o el bucle de revisión la pedirá.
_REQUIRED_TOOL_BY_KEYWORD = (
    (
        ("correo", "email", "e-mail", "mail", "envia", "enviar",
         "envíalo", "enviame", "envíame", "remite", "remitir",
         "notificar"),
        "llm_mail_sender",
    ),
)

# Plantilla del wrapper que se antepone/agrega al ``task_prompt`` para
# garantizar que el modelo:
#   1. Siga un plan paso a paso.
#   2. Use efectivamente las herramientas (correo, artefactos, etc.).
#   3. Reporte el estado final con ``llm_task_status_reporter``.
_TASK_PROMPT_WRAPPER = (
    "Estás ejecutando una **tarea programada automática**. No hay un humano "
    "esperando para confirmar nada: NO pidas confirmación, ejecuta TODAS "
    "las acciones necesarias hasta completar la solicitud original.\n\n"
    "REGLAS OBLIGATORIAS:\n"
    "1. Sigue el PLAN DE EJECUCIÓN paso a paso, en orden. No te detengas "
    "en mitad del plan.\n"
    "2. Usa SIEMPRE las herramientas disponibles para realizar acciones "
    "reales (consultas, creación/actualización de registros, generación "
    "de artefactos, envío de correos…). No te limites a describir lo que "
    "harías: hazlo de verdad.\n"
    "3. Si la tarea pide enviar un correo, DEBES llamar a la herramienta "
    "`llm_mail_sender` con destinatarios, asunto y cuerpo. NO digas "
    "«envíalo tú», «aquí tienes el contenido» ni «¿quieres que lo envíe?»: "
    "invoca la herramienta directamente, sin preguntar. Usa LITERALMENTE "
    "los destinatarios, asunto y demás datos extraídos del prompt; nunca "
    "los inventes ni los modifiques.\n"
    "4. Si una herramienta falla, intenta repararlo (1-2 reintentos con "
    "argumentos corregidos) o continúa con el siguiente paso si no es "
    "crítico, registrando el problema.\n"
    "5. **Como última acción**, llama OBLIGATORIAMENTE a la herramienta "
    "`llm_task_status_reporter` con `state=\"success\"` si completaste "
    "todo lo pedido o `state=\"error\"` si quedó algo sin hacer. Sin esa "
    "llamada el sistema no sabe que la tarea terminó y la marcará como "
    "colgada.\n\n"
    "%(details_block)s"
    "%(plan_block)s"
    "── INSTRUCCIÓN ORIGINAL DEL USUARIO ──────────────────────────────\n"
    "%(task_prompt)s\n"
    "──────────────────────────────────────────────────────────────────\n\n"
    "Recuerda: ejecuta los pasos del plan en orden y termina llamando a "
    "`llm_task_status_reporter`."
)

# Plantilla del bloque PLAN dentro del wrapper (se omite si no hay plan).
_PLAN_BLOCK_TEMPLATE = (
    "── PLAN DE EJECUCIÓN (síguelo en orden) ──────────────────────────\n"
    "%(plan_text)s\n"
    "──────────────────────────────────────────────────────────────────\n\n"
)

# Bloque opcional con datos clave extraídos automáticamente del prompt
# (destinatarios de correo, asunto). Sirve para evitar que el modelo se
# invente direcciones o asuntos al volver a llamar a la tool en el bucle
# de revisión.
_DETAILS_BLOCK_TEMPLATE = (
    "── DATOS CLAVE EXTRAÍDOS DEL PROMPT (úsalos LITERALMENTE) ────────\n"
    "%(details_text)s\n"
    "──────────────────────────────────────────────────────────────────\n\n"
)

# Regex para extraer correos y subject del prompt original.
_EMAIL_RE = re.compile(
    r"\b[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}\b"
)
# Captura cualquier cosa entre comillas dobles tipográficas o rectas y
# comillas simples. Se queda con la cadena más larga (probablemente el
# asunto que pidió el usuario).
_QUOTED_RE = re.compile(
    r"[\"“”«»]([^\"“”«»]{3,200})[\"“”«»]"
)

# Prompt que se le pide al LLM para producir el plan inicial. La
# respuesta debe ser un único objeto JSON parseable.
_PLAN_BUILDER_SYSTEM = (
    "Eres un planificador de tareas LLM automatizadas. Recibes una "
    "instrucción que un usuario quiere ejecutar de forma recurrente con "
    "herramientas Odoo. Tu trabajo es desglosarla en una lista breve y "
    "concreta de pasos accionables, en orden, indicando qué herramienta "
    "usarás en cada uno cuando aplique.\n\n"
    "Responde ÚNICAMENTE con un JSON válido (sin markdown, sin texto "
    "adicional) con esta forma exacta:\n"
    '{"steps": [\n'
    '  {"id": 1, "description": "consulta breve en español", '
    '"tool": "nombre_tool_o_null"},\n'
    "  ...\n"
    "]}\n\n"
    "Reglas:\n"
    " - 4 a 10 pasos como máximo.\n"
    " - Cada paso debe ser concreto (qué consultar, qué calcular, qué "
    "enviar, etc.).\n"
    " - Si la tarea menciona enviar un correo, incluye un paso explícito "
    'con tool "llm_mail_sender" y otro paso final con tool '
    '"llm_task_status_reporter".\n'
    " - El último paso SIEMPRE debe ser cerrar con tool "
    '"llm_task_status_reporter".'
)


class LLMScheduledTask(models.Model):
    _name = "llm.scheduled.task"
    _description = "Tarea Programada LLM"
    _order = "name"
    _inherit = ["mail.thread", "mail.activity.mixin"]

    # ─────────────────────────────────────────────────
    # Campos básicos
    # ─────────────────────────────────────────────────
    name = fields.Char("Nombre", required=True, tracking=True)
    active = fields.Boolean("Activo", default=True)
    state = fields.Selection(
        [("active", "Activo"), ("paused", "Pausado")],
        string="Estado",
        default="active",
        tracking=True,
    )
    task_prompt = fields.Text(
        "Instrucción del LLM",
        required=True,
        help=(
            "Describe qué debe hacer el LLM cada vez que se ejecute la tarea. "
            "Puedes referenciar herramientas (odoo_record_retriever, llm_artifact_builder, etc.) "
            "y solicitar acciones concretas como enviar reportes, verificar registros o notificar.\n\n"
            "Ejemplo: 'Consulta las órdenes de venta pendientes de los últimos 7 días, "
            "genera un resumen y envíalo por correo a ventas@empresa.com'."
        ),
    )
    notes = fields.Text(
        "Notas",
        help="Comentarios o documentación interna sobre el propósito de la tarea.",
    )
    user_id = fields.Many2one(
        "res.users",
        "Propietario",
        default=lambda self: self.env.user,
        required=True,
        tracking=True,
    )

    # ─────────────────────────────────────────────────
    # Configuración del LLM
    # ─────────────────────────────────────────────────
    assistant_id = fields.Many2one(
        "llm.assistant",
        "Asistente",
        tracking=True,
        help="Asistente LLM a usar. Si se configura, define automáticamente el proveedor, modelo y herramientas.",
    )
    provider_id = fields.Many2one(
        "llm.provider",
        "Proveedor LLM",
        tracking=True,
    )
    model_id = fields.Many2one(
        "llm.model",
        "Modelo LLM",
        domain="[('provider_id', '=', provider_id)]",
        tracking=True,
    )
    tool_ids = fields.Many2many(
        "llm.tool",
        string="Herramientas disponibles",
        help="Herramientas que el LLM puede usar durante la ejecución.",
    )

    # ─────────────────────────────────────────────────
    # Programación
    # ─────────────────────────────────────────────────
    interval_number = fields.Integer(
        "Cada",
        default=1,
        required=True,
    )
    interval_type = fields.Selection(
        [
            ("minutes", "Minutos"),
            ("hours", "Horas"),
            ("days", "Días"),
            ("weeks", "Semanas"),
            ("months", "Meses"),
        ],
        string="Unidad",
        default="days",
        required=True,
        tracking=True,
    )
    next_run = fields.Datetime(
        "Primera / próxima ejecución",
        required=True,
        default=fields.Datetime.now,
        help="Fecha y hora de la primera ejecución. Después se repetirá según el intervalo.",
        tracking=True,
    )

    # ─────────────────────────────────────────────────
    # Relaciones técnicas
    # ─────────────────────────────────────────────────
    cron_id = fields.Many2one(
        "ir.cron",
        "Cron Job",
        readonly=True,
        copy=False,
        ondelete="set null",
    )
    thread_id = fields.Many2one(
        "llm.thread",
        "Último chat de ejecución",
        readonly=True,
        copy=False,
        ondelete="set null",
        help="Apunta al hilo de la última ejecución. Cada corrida crea un chat nuevo para no mezclar contexto.",
    )

    # ─────────────────────────────────────────────────
    # Estadísticas
    # ─────────────────────────────────────────────────
    log_ids = fields.One2many(
        "llm.scheduled.task.log",
        "task_id",
        string="Ejecuciones",
        readonly=True,
    )
    log_count = fields.Integer(
        "Ejecuciones",
        compute="_compute_log_count",
    )
    last_run = fields.Datetime(
        "Última ejecución",
        compute="_compute_last_run",
        store=True,
    )
    last_state = fields.Selection(
        [("running", "Ejecutando"), ("success", "Exitoso"), ("error", "Error")],
        string="Último resultado",
        compute="_compute_last_run",
        store=True,
    )

    # ─────────────────────────────────────────────────
    # Computed
    # ─────────────────────────────────────────────────
    @api.depends("log_ids")
    def _compute_log_count(self):
        for task in self:
            task.log_count = len(task.log_ids)

    @api.depends("log_ids.execution_date", "log_ids.state")
    def _compute_last_run(self):
        for task in self:
            last = task.log_ids.sorted("execution_date", reverse=True)[:1]
            if last:
                task.last_run = last.execution_date
                task.last_state = last.state
            else:
                task.last_run = False
                task.last_state = False

    # ─────────────────────────────────────────────────
    # Onchange
    # ─────────────────────────────────────────────────
    @api.onchange("assistant_id")
    def _onchange_assistant_id(self):
        if self.assistant_id:
            self.provider_id = self.assistant_id.provider_id
            self.model_id = self.assistant_id.model_id
            self.tool_ids = self.assistant_id.tool_ids

    # ─────────────────────────────────────────────────
    # Constraints
    # ─────────────────────────────────────────────────
    @api.constrains("interval_number")
    def _check_interval_number(self):
        for task in self:
            if task.interval_number < 1:
                raise ValidationError(_("El intervalo debe ser mayor o igual a 1."))

    @api.constrains("provider_id", "model_id", "assistant_id")
    def _check_llm_config(self):
        for task in self:
            if not task.assistant_id and not task.provider_id:
                raise ValidationError(
                    _(
                        "Debes configurar un Asistente o un Proveedor/Modelo LLM "
                        "para la tarea «%(name)s»."
                    )
                    % {"name": task.name}
                )

    # ─────────────────────────────────────────────────
    # ORM Hooks
    # ─────────────────────────────────────────────────
    @api.model_create_multi
    def create(self, vals_list):
        tasks = super().create(vals_list)
        for task in tasks:
            task._sync_cron()
        return tasks

    def write(self, vals):
        res = super().write(vals)
        cron_fields = {
            "state", "interval_number", "interval_type", "next_run", "name",
        }
        if cron_fields.intersection(vals):
            for task in self:
                task._sync_cron()
        return res

    def unlink(self):
        for task in self:
            if task.cron_id:
                task.cron_id.sudo().unlink()
            threads = task.log_ids.mapped("thread_id")
            if task.thread_id:
                threads |= task.thread_id
            if threads:
                threads.sudo().unlink()
        return super().unlink()

    # ─────────────────────────────────────────────────
    # Cron management
    # ─────────────────────────────────────────────────
    def _sync_cron(self):
        """Crea o actualiza el ir.cron vinculado a esta tarea."""
        self.ensure_one()
        cron_vals = {
            "name": _("LLM Tarea: %s") % self.name,
            "active": self.state == "active",
            "interval_number": self.interval_number,
            "interval_type": self.interval_type,
            "nextcall": self.next_run or fields.Datetime.now(),
        }
        if self.cron_id:
            self.cron_id.sudo().write(cron_vals)
        else:
            ir_model = (
                self.env["ir.model"]
                .sudo()
                .search([("model", "=", "llm.scheduled.task")], limit=1)
            )
            if not ir_model:
                _logger.warning(
                    "No se encontró el modelo llm.scheduled.task en ir.model. "
                    "El cron no se creará."
                )
                return
            cron_vals.update({
                "model_id": ir_model.id,
                "state": "code",
                "code": f"model.browse({self.id})._do_execute()",
                "numbercall": -1,
                "doall": False,
                "user_id": self.user_id.id or self.env.user.id,
            })
            cron = self.env["ir.cron"].sudo().create(cron_vals)
            # Usar sudo() para evitar que el check de write_date falle
            self.sudo().write({"cron_id": cron.id})

    # ─────────────────────────────────────────────────
    # Thread management
    # ─────────────────────────────────────────────────
    def _resolve_required_task_tools(self, base_tool_ids):
        """Garantiza que las herramientas obligatorias (status reporter, etc.)
        estén disponibles en el hilo de la tarea, aunque el asistente no las
        tenga marcadas explícitamente.
        """
        Tool = self.env["llm.tool"].sudo()
        ids = list(base_tool_ids or [])
        existing = set(ids)
        for tool_name in _REQUIRED_TASK_TOOL_NAMES:
            extra = Tool.search([("name", "=", tool_name)], limit=1)
            if extra and extra.id not in existing:
                ids.append(extra.id)
                existing.add(extra.id)
        return ids

    def _create_execution_thread(self, log):
        """Crea un chat nuevo por ejecución (sin historial de corridas anteriores)."""
        self.ensure_one()
        thread_vals = {
            "name": _("[Tarea] %s — ejecución %s") % (self.name, log.id),
            "is_scheduled_task": True,
            "user_id": self.user_id.id,
        }
        if self.assistant_id:
            tool_ids = self._resolve_required_task_tools(
                self.assistant_id.tool_ids.ids
            )
            thread_vals.update({
                "assistant_id": self.assistant_id.id,
                "provider_id": self.assistant_id.provider_id.id,
                "model_id": self.assistant_id.model_id.id,
                "tool_ids": [(6, 0, tool_ids)],
            })
        else:
            tool_ids = self._resolve_required_task_tools(self.tool_ids.ids)
            thread_vals.update({
                "provider_id": self.provider_id.id,
                "model_id": self.model_id.id,
                "tool_ids": [(6, 0, tool_ids)],
            })

        # PP automático si el prompt ya se ve complejo (antes del plan).
        needs_pp, reasons = self._task_needs_deep_thinking()
        if needs_pp and "chat_work_mode" in self.env["llm.thread"]._fields:
            thread_vals["chat_work_mode"] = "deep_thinking"
            if "gemini_thinking_budget" in self.env["llm.thread"]._fields:
                thread_vals["gemini_thinking_budget"] = (
                    _DEEP_THINKING_BUDGET_DEFAULT
                )

        thread = self.env["llm.thread"].sudo().create(thread_vals)
        self.sudo().write({"thread_id": thread.id})
        log.sudo().write({"thread_id": thread.id})
        if needs_pp and getattr(thread, "chat_work_mode", None) == "deep_thinking":
            _logger.info(
                "LLM Tarea «%s»: PP activado al crear el hilo (%s).",
                self.name,
                "; ".join(reasons) or "heurística",
            )
        return thread

    # ─────────────────────────────────────────────────
    # Pensamiento profundo automático (tareas complejas)
    # ─────────────────────────────────────────────────
    def _task_needs_deep_thinking(self, plan_dict=None):
        """Detecta si la tarea es lo bastante compleja para forzar PP.

        Criterios (cualquiera basta):
        - Prompt largo (>= ``_DEEP_THINKING_PROMPT_MIN_LEN``).
        - Palabras clave de análisis / multi-paso / reportes.
        - Varias tools obligatorias inferidas del prompt.
        - Plan con muchos pasos (>= ``_DEEP_THINKING_PLAN_MIN_STEPS``).

        Devuelve ``(bool, list[str])`` con los motivos detectados.
        """
        self.ensure_one()
        reasons = []
        prompt = (self.task_prompt or "").strip()
        prompt_lower = prompt.lower()

        if len(prompt) >= _DEEP_THINKING_PROMPT_MIN_LEN:
            reasons.append("prompt largo (%d chars)" % len(prompt))

        hits = [kw for kw in _DEEP_THINKING_KEYWORDS if kw in prompt_lower]
        if hits:
            reasons.append("keywords: %s" % ", ".join(hits[:5]))

        # Refuerzo informativo cuando ya hay señales de complejidad y además
        # hay tools de acción (mail, etc.): ayuda al log de diagnóstico.
        required = self._required_tools_from_prompt(plan_dict)
        action_tools = required - {"llm_task_status_reporter"}
        if action_tools and reasons:
            reasons.append(
                "tools de acción: %s" % ", ".join(sorted(action_tools))
            )

        steps = (plan_dict or {}).get("steps") or []
        if len(steps) >= _DEEP_THINKING_PLAN_MIN_STEPS:
            reasons.append("plan con %d pasos" % len(steps))

        return (bool(reasons), reasons)

    def _apply_deep_thinking_to_thread(self, thread, plan_dict=None):
        """Activa PP en el hilo si la heurística lo indica y aún no está.

        No-op si ``llm_experience`` no está instalado (sin el campo).
        """
        self.ensure_one()
        if "chat_work_mode" not in thread._fields:
            return False
        needs_pp, reasons = self._task_needs_deep_thinking(plan_dict)
        if not needs_pp:
            return False
        if thread.chat_work_mode == "deep_thinking":
            return True
        vals = {"chat_work_mode": "deep_thinking"}
        if "gemini_thinking_budget" in thread._fields:
            current = int(thread.gemini_thinking_budget or 0)
            if current <= 0:
                vals["gemini_thinking_budget"] = _DEEP_THINKING_BUDGET_DEFAULT
        thread.sudo().write(vals)
        _logger.info(
            "LLM Tarea «%s»: PP forzado en hilo %s (%s).",
            self.name,
            thread.id,
            "; ".join(reasons),
        )
        return True

    def _build_execution_prompt(self, plan_text="", details=None):
        """Devuelve el prompt envuelto con las instrucciones de cierre.

        Antepone reglas que obligan al asistente a:
        - seguir un plan paso a paso,
        - usar realmente las herramientas (no solo describirlas),
        - no pedir confirmación humana,
        - cerrar la ejecución llamando a ``llm_task_status_reporter``.

        :param plan_text: Plan textual generado por ``_build_task_plan``;
            si está vacío, el bloque PLAN se omite.
        :param details: Dict con datos clave extraídos del prompt
            (correos, asunto, etc.). Si está vacío, el bloque se omite.
        """
        self.ensure_one()
        plan_block = ""
        if plan_text and plan_text.strip():
            plan_block = _PLAN_BLOCK_TEMPLATE % {"plan_text": plan_text.strip()}
        details_block = ""
        details_text = self._format_task_details(details or {})
        if details_text:
            details_block = _DETAILS_BLOCK_TEMPLATE % {
                "details_text": details_text,
            }
        return _TASK_PROMPT_WRAPPER % {
            "task_prompt": (self.task_prompt or "").strip(),
            "plan_block": plan_block,
            "details_block": details_block,
        }

    # ─────────────────────────────────────────────────
    # Extracción de datos clave del prompt (correos, asunto)
    # ─────────────────────────────────────────────────
    def _extract_task_details(self):
        """Extrae datos literales del ``task_prompt`` que el modelo no
        debe inventar al invocar herramientas (correos, asuntos, etc.).

        Es deterministico (regex) para garantizar exactitud — el LLM
        no participa, así no inventa.
        """
        self.ensure_one()
        text = (self.task_prompt or "").strip()
        details = {}
        emails = list(dict.fromkeys(_EMAIL_RE.findall(text)))
        if emails:
            details["mail_to"] = emails
        # Subject: cogemos la cadena entrecomillada más larga
        quoted = _QUOTED_RE.findall(text)
        if quoted:
            quoted_clean = [q.strip() for q in quoted if q.strip()]
            if quoted_clean:
                details["mail_subject"] = max(quoted_clean, key=len)
        return details

    def _format_task_details(self, details):
        """Convierte el dict de detalles a líneas legibles para el prompt."""
        if not details:
            return ""
        lines = []
        if details.get("mail_to"):
            lines.append(
                "• Destinatarios del correo (`to_emails`): "
                + ", ".join(details["mail_to"])
            )
        if details.get("mail_subject"):
            lines.append(
                "• Asunto del correo (`subject`): «%s»"
                % details["mail_subject"]
            )
        return "\n".join(lines)

    # ─────────────────────────────────────────────────
    # Planificación inicial (estilo "todo list")
    # ─────────────────────────────────────────────────
    def _resolve_planner_provider_model(self):
        """Devuelve (provider, model) usables para planificación / revisión."""
        self.ensure_one()
        provider = self.provider_id or self.assistant_id.provider_id
        model = self.model_id or self.assistant_id.model_id
        return provider, model

    def _build_task_plan(self):
        """Pide al LLM un plan en JSON (lista de pasos) a partir del prompt.

        Devuelve ``(plan_text, plan_dict)``:
          * ``plan_text``: Lista en markdown lista para inyectar al wrapper.
          * ``plan_dict``: Estructura interna ``{"steps": [...]}`` o ``{}``
            si no se pudo generar.
        Tolerante a fallos: si el LLM responde algo no parseable, se hace
        un mejor esfuerzo y, si todo falla, se devuelve un plan vacío.
        """
        self.ensure_one()
        provider, model = self._resolve_planner_provider_model()
        if not provider or not model:
            return "", {}

        original_prompt = (self.task_prompt or "").strip()
        if not original_prompt:
            return "", {}

        messages = [
            {"role": "system", "content": _PLAN_BUILDER_SYSTEM},
            {
                "role": "user",
                "content": (
                    "INSTRUCCIÓN A EJECUTAR:\n%s\n\n"
                    "Devuelve únicamente el JSON con los pasos."
                )
                % original_prompt[:6000],
            },
        ]

        text = ""
        try:
            chunks = provider.sudo().chat(
                messages, model=model, stream=False
            )
            for chunk in chunks or []:
                if isinstance(chunk, dict):
                    text += str(chunk.get("content") or "")
                else:
                    text += str(chunk or "")
        except Exception as err:
            _logger.warning(
                "Planificador LLM falló para tarea «%s»: %s",
                self.name,
                err,
            )
            return "", {}

        plan_dict = self._parse_plan_json(text)
        if not plan_dict.get("steps"):
            return "", {}

        plan_text = self._format_plan_text(plan_dict)
        return plan_text, plan_dict

    def _parse_plan_json(self, text):
        """Extrae el primer objeto JSON de la respuesta y normaliza pasos."""
        if not text:
            return {}
        match = re.search(r"\{[\s\S]*\}", text)
        if not match:
            return {}
        try:
            data = json.loads(match.group(0))
        except Exception:
            return {}
        steps = data.get("steps") if isinstance(data, dict) else None
        if not isinstance(steps, list):
            return {}
        cleaned = []
        for idx, step in enumerate(steps, start=1):
            if not isinstance(step, dict):
                continue
            desc = str(step.get("description") or "").strip()
            if not desc:
                continue
            tool = step.get("tool")
            if isinstance(tool, str):
                tool = tool.strip() or None
            else:
                tool = None
            cleaned.append({
                "id": int(step.get("id") or idx),
                "description": desc,
                "tool": tool,
            })
        # Garantizamos que el último paso sea el reporter
        if cleaned and (cleaned[-1].get("tool") != "llm_task_status_reporter"):
            cleaned.append({
                "id": (cleaned[-1]["id"] or len(cleaned)) + 1,
                "description": (
                    "Cerrar la ejecución llamando a llm_task_status_reporter "
                    "con state=success o error y un resumen breve."
                ),
                "tool": "llm_task_status_reporter",
            })
        return {"steps": cleaned}

    def _format_plan_text(self, plan_dict):
        lines = []
        for step in plan_dict.get("steps", []):
            tool_part = f" → `{step['tool']}`" if step.get("tool") else ""
            lines.append(f"{step['id']}. {step['description']}{tool_part}")
        return "\n".join(lines)

    # ─────────────────────────────────────────────────
    # Detección de pasos faltantes / bucle de revisión
    # ─────────────────────────────────────────────────
    def _required_tools_from_prompt(self, plan_dict=None):
        """Devuelve el conjunto de tools que DEBEN haberse invocado para
        considerar la tarea completa. Combina:

        * Heurística por palabras clave en ``task_prompt``.
        * Tools listadas explícitamente en el plan generado.
        * Tools obligatorias del sistema (status reporter).
        """
        self.ensure_one()
        required = {"llm_task_status_reporter"}
        prompt_lower = (self.task_prompt or "").lower()
        for keywords, tool_name in _REQUIRED_TOOL_BY_KEYWORD:
            if any(kw in prompt_lower for kw in keywords):
                required.add(tool_name)
        if plan_dict and isinstance(plan_dict, dict):
            for step in plan_dict.get("steps", []):
                tool = step.get("tool")
                if tool:
                    required.add(tool)
        return required

    def _tools_actually_called(self, thread):
        """Lista de tools efectivamente invocadas en el hilo (por nombre)."""
        Message = self.env["mail.message"].sudo()
        tool_msgs = Message.search(
            [
                ("model", "=", "llm.thread"),
                ("res_id", "=", thread.id),
                ("llm_role", "=", "tool"),
            ]
        )
        called = set()
        for msg in tool_msgs:
            data = msg.body_json or {}
            name = data.get("tool_name") or (
                (data.get("tool_call") or {}).get("function") or {}
            ).get("name")
            if name:
                called.add(name)
        return called

    def _build_review_reminder(self, missing_tools, log, details=None):
        """Construye el mensaje de recordatorio para el bucle de revisión.

        Importante: incluye SIEMPRE los datos clave extraídos del prompt
        (destinatarios, asunto) y un recordatorio LITERAL de la
        instrucción original. Sin eso, el modelo a veces inventa correos
        nuevos al ejecutar `llm_mail_sender` en la fase de revisión.
        """
        bullets = "\n".join(f"- `{t}`" for t in sorted(missing_tools))
        details = details or {}

        details_text = self._format_task_details(details)
        details_block = ""
        if details_text:
            details_block = (
                "── DATOS CLAVE (úsalos LITERALMENTE, no los reinventes) ──\n"
                f"{details_text}\n"
                "──────────────────────────────────────────────────────────\n\n"
            )

        original_prompt = (self.task_prompt or "").strip()
        original_block = ""
        if original_prompt:
            original_block = (
                "── INSTRUCCIÓN ORIGINAL DEL USUARIO (recordatorio) ───────\n"
                f"{original_prompt}\n"
                "──────────────────────────────────────────────────────────\n\n"
            )

        # Mensaje concreto, agresivo e imperativo: el modelo debe actuar
        # con tools, no responder con texto.
        body = (
            "🔁 **REVISIÓN DE TAREA INCOMPLETA**\n\n"
            "Has generado una respuesta pero el sistema detecta que aún "
            "NO se han invocado todas las herramientas requeridas para "
            "completar la tarea programada.\n\n"
            "Herramientas que faltan por llamar:\n"
            f"{bullets}\n\n"
        )
        body += original_block
        body += details_block
        body += (
            "Acciones obligatorias AHORA:\n"
            "1. Si falta `llm_mail_sender`: invócalo YA usando "
            "EXACTAMENTE los destinatarios y el asunto indicados arriba "
            "(no inventes ni cambies direcciones de correo). El cuerpo "
            "lo construyes con los datos que ya obtuviste en pasos "
            "anteriores.\n"
            "2. Si falta `llm_task_status_reporter`: cierra la "
            "ejecución llamándolo con `state=\"success\"` o "
            "`state=\"error\"` y un resumen breve.\n\n"
            "NO respondas con texto explicativo: ejecuta directamente "
            "las herramientas. NO pidas confirmación. NO digas «aquí "
            "tienes…» sin invocar antes la tool. Si por alguna razón no "
            "puedes completar un paso, llama a `llm_task_status_reporter` "
            "con `state=\"error\"` explicando el motivo."
        )
        return body

    def _run_review_loop(self, thread, log, plan_dict, details=None):
        """Tras la primera generación, fuerza al modelo a completar las
        tools pendientes invocando ``thread.generate`` con un recordatorio.

        Repite hasta ``_MAX_REVIEW_ITERATIONS`` veces o hasta que el
        log se cierre vía ``llm_task_status_reporter``.
        """
        self.ensure_one()
        required = self._required_tools_from_prompt(plan_dict)
        task_user = self.user_id or self.env.user
        thread_as_user = thread.with_user(task_user)
        if details is None:
            details = self._extract_task_details()

        for attempt in range(1, _MAX_REVIEW_ITERATIONS + 1):
            log.invalidate_cache()
            if log.state in ("success", "error"):
                return
            called = self._tools_actually_called(thread)
            missing = required - called
            if not missing:
                # Todo lo requerido se llamó, pero el reporter no cerró
                # el log: añadimos sólo el reporter al recordatorio.
                if "llm_task_status_reporter" in called:
                    return
                missing = {"llm_task_status_reporter"}

            _logger.info(
                "LLM Tarea «%s»: revisión #%s — tools faltantes=%s",
                self.name,
                attempt,
                sorted(missing),
            )
            reminder = self._build_review_reminder(missing, log, details)
            try:
                for _chunk in thread_as_user.generate(reminder):
                    pass
            except Exception as err:
                _logger.warning(
                    "LLM Tarea «%s»: revisión #%s falló: %s",
                    self.name,
                    attempt,
                    err,
                )
                break
            log.sudo().write({"review_iterations": attempt})
            log.invalidate_cache()
            if log.state in ("success", "error"):
                return

    # ─────────────────────────────────────────────────
    # Actions
    # ─────────────────────────────────────────────────
    def action_run_now(self):
        """Ejecuta la tarea manualmente de inmediato."""
        self.ensure_one()
        # Evita solape con ir.cron: la próxima llamada programada queda después de ahora + intervalo
        self._postpone_next_scheduled_run()
        self._do_execute()
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("Tarea ejecutada"),
                "message": _("La tarea «%s» se ejecutó. Revisa los logs para ver el resultado.") % self.name,
                "type": "success",
                "sticky": False,
                "next": {"type": "ir.actions.act_window_close"},
            },
        }

    def action_pause(self):
        return self.write({"state": "paused"})

    def action_activate(self):
        return self.write({"state": "active"})

    def action_view_logs(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": _("Ejecuciones: %s") % self.name,
            "res_model": "llm.scheduled.task.log",
            "view_mode": "tree,form",
            "domain": [("task_id", "=", self.id)],
            "context": {"default_task_id": self.id},
        }

    def action_view_thread(self):
        """Abre el chat de la última ejecución (si existe)."""
        self.ensure_one()
        if not self.thread_id:
            return False
        return {
            "type": "ir.actions.act_window",
            "name": _("Chat de tarea: %s") % self.name,
            "res_model": "llm.thread",
            "res_id": self.thread_id.id,
            "view_mode": "form",
            "target": "current",
            "context": {"show_task_threads": True},
        }

    def _llm_scheduled_task_advisory_key(self):
        """Clave bigint estable para pg_try_advisory_lock (una por tarea)."""
        return int((0x4C4D5354 << 32) | (self.id & 0xFFFFFFFF))

    def _postpone_next_scheduled_run(self):
        """Adelanta next_run / nextcall del cron para no disparar en paralelo con ejecución manual."""
        self.ensure_one()
        if self.state != "active" or not self.interval_type:
            return
        n = self.interval_number or 1
        delta_fn = _LLM_TASK_INTERVAL_DELTA.get(self.interval_type)
        if not delta_fn:
            return
        now = fields.Datetime.now()
        candidate = now + delta_fn(n)
        # No adelantar una próxima ejecución ya programada más lejana (p. ej. next_run en el futuro)
        current = self.next_run or candidate
        next_time = max(candidate, current)
        if next_time != self.next_run:
            self.write({"next_run": next_time})

    # ─────────────────────────────────────────────────
    # Ejecución del LLM
    # ─────────────────────────────────────────────────
    def _do_execute(self):
        """
        Núcleo de la ejecución:
        1. Crea un log y un chat nuevo (un hilo por ejecución).
        2. Postea el prompt como mensaje de usuario.
        3. Ejecuta el bucle LLM completo (incluyendo tool calls).
        4. Registra el resultado en llm.scheduled.task.log.
        """
        self.ensure_one()

        lock_id = self._llm_scheduled_task_advisory_key()
        lock_held = None
        try:
            self.env.cr.execute("SELECT pg_try_advisory_lock(%s)", (lock_id,))
            row = self.env.cr.fetchone()
            lock_held = bool(row and row[0])
        except Exception as err:
            _logger.warning(
                "LLM Tarea id=%s: pg_try_advisory_lock no disponible (%s); "
                "se ejecuta sin bloqueo antiduplicado.",
                self.id,
                err,
            )
            lock_held = None

        if lock_held is False:
            _logger.warning(
                "LLM Tarea '%s' (id=%s): ejecución omitida (ya hay otra corrida en curso).",
                self.name,
                self.id,
            )
            return

        _logger.info(
            "LLM Tarea '%s' (id=%s): iniciando ejecución.", self.name, self.id
        )

        try:
            start_ts = _time.time()

            log = (
                self.env["llm.scheduled.task.log"]
                .sudo()
                .create({
                    "task_id": self.id,
                    "execution_date": fields.Datetime.now(),
                    "state": "running",
                })
            )
            self.env.cr.commit()

            thread = self._create_execution_thread(log)

            try:
                msg_domain = [
                    ("model", "=", "llm.thread"),
                    ("res_id", "=", thread.id),
                ]
                msg_before = self.env["mail.message"].sudo().search_count(
                    msg_domain
                )

                task_user = self.user_id or self.env.user
                thread_as_user = thread.with_user(task_user)

                # 1. Planificación inicial (estilo "todo list"). Si el
                # provider no logra producir un plan parseable, seguimos
                # ejecutando igualmente: el wrapper sin plan es el
                # comportamiento previo.
                plan_text, plan_dict = self._build_task_plan()
                if plan_text:
                    log.sudo().write({
                        "plan_text": plan_text,
                        "plan_json": plan_dict,
                    })
                    self.env.cr.commit()

                # 1.a. Tras el plan: si hay muchos pasos u otras señales,
                # forzar PP (también cubre el caso en que el prompt corto
                # no lo activó al crear el hilo).
                self._apply_deep_thinking_to_thread(thread, plan_dict)
                # Refrescar el proxy with_user por si cambió el modo.
                thread_as_user = thread.with_user(task_user)

                # 1.b. Datos clave (correos, asunto, etc.) extraídos del
                # prompt de forma determinista. Se inyectan tanto en el
                # wrapper inicial como en cualquier recordatorio de
                # revisión, evitando que el modelo invente direcciones
                # de correo o asuntos al volver a ejecutar la tool.
                task_details = self._extract_task_details()
                if task_details:
                    _logger.info(
                        "LLM Tarea '%s': datos clave extraídos del prompt: %s",
                        self.name,
                        task_details,
                    )

                # 2. Ejecución principal con el prompt envuelto + plan.
                wrapped_prompt = self._build_execution_prompt(
                    plan_text, details=task_details
                )
                for _chunk in thread_as_user.generate(wrapped_prompt):
                    pass

                # 3. Bucle de revisión: si quedan tools pendientes
                # (típicamente llm_mail_sender o llm_task_status_reporter)
                # forzamos al modelo a cerrarlas hasta N veces.
                self._run_review_loop(
                    thread, log, plan_dict, details=task_details
                )

                msg_after = self.env["mail.message"].sudo().search_count(
                    msg_domain
                )
                duration = _time.time() - start_ts

                # Refrescamos el log: si el asistente llamó a
                # ``llm_task_status_reporter`` durante la ejecución, el log ya
                # estará en ``success`` o ``error`` con un resumen propio del
                # propio modelo. En ese caso respetamos esa decisión.
                log.invalidate_cache()
                if log.state in ("success", "error"):
                    log.sudo().write({
                        "duration_seconds": duration,
                        "message_count": max(0, msg_after - msg_before),
                    })
                    _logger.info(
                        "LLM Tarea '%s': cerrada por el propio asistente "
                        "(state=%s, revisiones=%s) en %.1f s "
                        "(%d mensajes generados).",
                        self.name,
                        log.state,
                        log.review_iterations,
                        duration,
                        max(0, msg_after - msg_before),
                    )
                else:
                    # El asistente no llamó al reporter (modelo pequeño,
                    # se quedó corto, etc.). Hacemos el diagnóstico IA
                    # de respaldo como hasta ahora.
                    ai_state, ai_summary = "unknown", ""
                    try:
                        ai_state, ai_summary = log._diagnose_with_ai()
                    except Exception as diag_err:
                        _logger.warning(
                            "LLM Tarea '%s': diagnóstico post-ejecución falló: %s",
                            self.name,
                            diag_err,
                        )

                    if ai_state == "error":
                        final_state = "error"
                        final_msg = _(
                            "Diagnóstico IA (sin reporter): la tarea terminó en error. %s"
                        ) % ai_summary
                    elif ai_state == "success":
                        final_state = "success"
                        final_msg = _(
                            "Diagnóstico IA (sin reporter): la tarea se completó correctamente. %s"
                        ) % ai_summary
                    else:
                        final_state = "success"
                        final_msg = (
                            _("Sin diagnóstico IA concluyente — %s") % ai_summary
                            if ai_summary
                            else _(
                                "El asistente no llamó a llm_task_status_reporter "
                                "y el diagnóstico IA no fue concluyente. Se asume éxito."
                            )
                        )

                    write_vals = {
                        "state": final_state,
                        "duration_seconds": duration,
                        "message_count": max(0, msg_after - msg_before),
                    }
                    if final_msg:
                        write_vals["error_message"] = final_msg
                    log.sudo().write(write_vals)
                    _logger.info(
                        "LLM Tarea '%s': completada en %.1f s (%d mensajes "
                        "generados, diagnóstico IA=%s).",
                        self.name,
                        duration,
                        max(0, msg_after - msg_before),
                        ai_state,
                    )
            except Exception as exc:
                duration = _time.time() - start_ts
                _logger.exception(
                    "LLM Tarea '%s' (id=%s): error durante la ejecución.",
                    self.name,
                    self.id,
                )
                log.sudo().write({
                    "state": "error",
                    "error_message": str(exc),
                    "duration_seconds": duration,
                })
                self.env.cr.commit()
            finally:
                self.sudo().write({"state": self.state})
        finally:
            if lock_held is True:
                try:
                    self.env.cr.execute(
                        "SELECT pg_advisory_unlock(%s)", (lock_id,)
                    )
                except Exception as err:
                    _logger.warning(
                        "LLM Tarea id=%s: pg_advisory_unlock: %s",
                        self.id,
                        err,
                    )
