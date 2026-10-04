# -*- coding: utf-8 -*-
import logging

from odoo import _, models
from odoo.tools import html2plaintext

from .llm_reasoning import XHIGH_SYSTEM_HINT
from .llm_research_orchestrator import LLMResearchOrchestrator

_logger = logging.getLogger(__name__)


class LLMThread(models.Model):
    _inherit = "llm.thread"

    def _generate_assistant_response(self, prepend_messages):
        """Cada ronda: resume el contexto si hace falta y añade instrucciones de sistema."""
        self.ensure_one()
        # Chequeo de topes mensuales (bloquea si se supera).
        self.env["llm.model.monthly.cap"].enforce_before_generate(self)

        note = self._context_preflight(prepend_messages)
        if note:
            yield {"type": "message_create", "message": note.message_format()[0]}
            # El resumen vive en los mensajes antepuestos: recalcularlos.
            prepend_messages = self.get_prepend_messages()

        extra = list(prepend_messages or [])
        current_turn = self._context_current_turn_messages()
        first_round = not current_turn

        if self.chat_work_mode == "deep_research":
            research_messages, plan_note = self._experience_research_messages(first_round)
            if plan_note:
                yield {"type": "message_create", "message": plan_note.message_format()[0]}
            extra.extend(research_messages)

        if self._experience_effective_reasoning_effort() == "xhigh":
            extra.append({"role": "system", "content": XHIGH_SYSTEM_HINT})

        hint = self._context_tool_error_hint(current_turn)
        if hint:
            extra.append(hint)

        thread = self
        if self._context_tool_rounds_exceeded(current_turn):
            thread = self.with_context(llm_tool_choice="none")
            extra.append(
                {
                    "role": "system",
                    "content": _(
                        "Se alcanzó el número máximo de rondas de herramientas "
                        "configurado para este turno. Responde ahora al usuario con "
                        "lo obtenido e indica qué quedaría pendiente."
                    ),
                }
            )
        return (
            yield from super(LLMThread, thread)._generate_assistant_response(extra)
        )

    def _experience_research_messages(self, first_round):
        """Plan de investigación: se genera una vez por turno y se reutiliza."""
        self.ensure_one()
        plan_note = False
        if first_round or not self.experience_research_plan:
            user_msg = self.env["mail.message"].search(
                self._context_base_domain() + [("llm_role", "=", "user")],
                order="id desc",
                limit=1,
            )
            user_text = html2plaintext(user_msg.body or "")[:8000] if user_msg else ""
            orch = LLMResearchOrchestrator(self.env)
            plan = orch.build_plan_from_prompt(
                self, user_text or _("(sin texto de usuario)")
            )
            lines = ["**%s**" % _("Plan de investigación")]
            if plan.objective:
                lines.append(_("Objetivo: %s") % plan.objective)
            for i, step in enumerate(plan.steps, 1):
                lines.append("%s. %s" % (i, step.title))
            self.write({"experience_research_plan": "\n".join(lines)})
            plan_note = self.message_post(
                body="<p>%s</p>" % "</p><p>".join(lines),
                message_type="comment",
                subtype_xmlid="mail.mt_note",
                author_id=self.env.ref("base.partner_root").id,
            )
        return (
            [
                {
                    "role": "system",
                    "content": _(
                        "Modo investigación profunda activado. Sigue este plan:\n%s\n"
                        "Usa herramientas Odoo cuando necesites datos reales; al final "
                        "entrega un informe con secciones: resumen ejecutivo, "
                        "metodología, hallazgos, incertidumbres, conclusiones y "
                        "recomendaciones."
                    )
                    % self.experience_research_plan,
                }
            ],
            plan_note,
        )
