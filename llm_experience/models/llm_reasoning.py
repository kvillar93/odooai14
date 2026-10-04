# -*- coding: utf-8 -*-
"""Niveles de esfuerzo de razonamiento comunes a todos los proveedores.

Cada proveedor traduce el nivel a su parámetro nativo:
Gemini 3+ ``thinking_level`` / Gemini 2.x ``thinking_budget`` (llm_gemini),
Anthropic ``thinking.budget_tokens`` y OpenAI ``reasoning_effort``.
"""

REASONING_EFFORT_SELECTION = [
    ("instant", "Instantáneo"),
    ("low", "Bajo"),
    ("medium", "Medio"),
    ("high", "Alto"),
    ("xhigh", "Extra alto"),
]

REASONING_EFFORTS = tuple(key for key, _label in REASONING_EFFORT_SELECTION)

DEFAULT_REASONING_EFFORT = "medium"

REASONING_EFFORT_DESCRIPTIONS = {
    "instant": "Respuesta directa, sin razonamiento previo. La más rápida.",
    "low": "Razonamiento breve. Buena para consultas simples.",
    "medium": "Equilibrio entre velocidad y calidad (recomendado).",
    "high": "Analiza con más profundidad antes de responder.",
    "xhigh": "Máximo razonamiento y verificación. Más lento y costoso.",
}

# Presupuesto de thinking de Anthropic por nivel (None = sin thinking).
ANTHROPIC_THINKING_BUDGETS = {
    "instant": None,
    "low": None,
    "medium": 4096,
    "high": 16000,
    "xhigh": 32000,
}

XHIGH_SYSTEM_HINT = (
    "Nivel de razonamiento: extra alto. Antes de responder, verifica cada dato "
    "con las herramientas disponibles, revisa los cálculos, considera "
    "alternativas y señala explícitamente cualquier incertidumbre."
)


def normalize_reasoning_effort(value):
    return value if value in REASONING_EFFORTS else DEFAULT_REASONING_EFFORT
