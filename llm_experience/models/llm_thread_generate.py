# -*- coding: utf-8 -*-
import logging

from odoo import _, models

from .llm_research_orchestrator import LLMResearchOrchestrator

_logger = logging.getLogger(__name__)


class LLMThread(models.Model):
    _inherit = "llm.thread"

    def _generate_assistant_response(self, prepend_messages):
        """Investigación profunda: plan visible + mismo pipeline de generación con contexto extra."""
        self.ensure_one()
        if self.chat_work_mode != "deep_research":
            return (yield from super()._generate_assistant_response(prepend_messages))

        user_text = ""
        try:
            msgs = self.env["mail.message"].search(
                [
                    ("model", "=", self._name),
                    ("res_id", "=", self.id),
                    ("llm_role", "=", "user"),
                ],
                order="id desc",
                limit=1,
            )
            if msgs and msgs[0].body:
                from odoo.tools import html2plaintext

                user_text = html2plaintext(msgs[0].body)[:8000]
        except Exception as err:
            _logger.debug("research user text: %s", err)

        orch = LLMResearchOrchestrator(self.env)
        plan = orch.build_plan_from_prompt(self, user_text or _("(sin texto de usuario)"))

        lines = ["**%s**" % _("Plan de investigación")]
        if plan.objective:
            lines.append(_("Objetivo: %s") % plan.objective)
        for i, st in enumerate(plan.steps, 1):
            lines.append("%s. %s — %s" % (i, st.title, st.status))
        body_plan = "<p>%s</p>" % "</p><p>".join(lines)

        self.message_post(
            body=body_plan,
            message_type="comment",
            subtype_xmlid="mail.mt_note",
        )

        extra = list(prepend_messages or []) + [
            {
                "role": "system",
                "content": _(
                    "Modo investigación profunda activado. Sigue el plan anterior; "
                    "usa herramientas Odoo cuando necesites datos reales; "
                    "al final entrega un informe con secciones: resumen ejecutivo, "
                    "metodología, hallazgos, incertidumbres, conclusiones y recomendaciones."
                ),
            }
        ]
        return (yield from super()._generate_assistant_response(extra))
