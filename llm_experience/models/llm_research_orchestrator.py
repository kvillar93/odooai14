# -*- coding: utf-8 -*-
"""
Orquestador de investigación profunda (extensible a otros proveedores).

Fases: análisis → plan visible → ejecución por pasos con herramientas → informe.
La implementación completa puede delegar en APIs tipo «Deep Research» o en bucles Gemini + tools.
"""
import json
import logging
from dataclasses import dataclass, field

from odoo import _

_logger = logging.getLogger(__name__)


@dataclass
class ResearchPlanStep:
    title: str = ""
    status: str = "pending"  # pending | running | done | error
    detail: str = ""


@dataclass
class ResearchPlan:
    objective: str = ""
    steps: list = field(default_factory=list)


class LLMResearchOrchestrator:
    """Fachada reutilizable; amplíe con pasos agentic o backend especializado."""

    def __init__(self, env):
        self.env = env

    def build_plan_from_prompt(self, thread, user_text):
        """Genera un plan numerado (v1: una llamada corta al modelo del hilo)."""
        prompt = _(
            "Devuelve SOLO un JSON con forma "
            '{"objective":"...","steps":["paso1","paso2",...]} '
            "en español, máximo 6 pasos, para investigar: %s"
        ) % (user_text[:2000],)
        try:
            out = thread.sudo().provider_id.chat(
                messages=[{"role": "user", "content": prompt}],
                model=thread.model_id,
                stream=False,
            )
            raw = (out or {}).get("content") or ""
            start = raw.find("{")
            end = raw.rfind("}") + 1
            if start >= 0 and end > start:
                data = json.loads(raw[start:end])
                steps = [
                    ResearchPlanStep(title=s, status="pending")
                    for s in data.get("steps") or []
                ]
                return ResearchPlan(
                    objective=data.get("objective") or "", steps=steps
                )
        except Exception as err:
            _logger.warning("Research plan JSON: %s", err)
        return ResearchPlan(
            objective=user_text[:200],
            steps=[
                ResearchPlanStep(title=_("Analizar el objetivo"), status="pending"),
                ResearchPlanStep(title=_("Recopilar fuentes internas (Odoo)"), status="pending"),
                ResearchPlanStep(title=_("Sintetizar informe"), status="pending"),
            ],
        )
