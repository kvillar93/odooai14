# -*- coding: utf-8 -*-
"""
Interfaz base reutilizable para seguimiento de uso de contexto/tokens por conector.

Los concretos (p. ej. Gemini) llaman a los métodos de registro tras count_tokens / respuesta.
"""
import logging
from abc import ABC, abstractmethod

_logger = logging.getLogger(__name__)


class LLMUsageTrackerBase(ABC):
    """Contrato para integrar otros proveedores además de Gemini."""

    @abstractmethod
    def estimate_request_tokens(self, provider, model_record, request_payload):
        """Devuelve estimación entera de tokens del request antes de enviar."""

    @abstractmethod
    def parse_response_usage(self, raw_response):
        """Extrae dict normalizado con claves: prompt, output, cached, thoughts, total."""


def gemini_usage_dict_from_response(response):
    """Convierte usage_metadata de google-genai a dict unificado."""
    out = {
        "prompt": 0,
        "cached": 0,
        "output": 0,
        "thoughts": 0,
        "total": 0,
    }
    um = getattr(response, "usage_metadata", None)
    if not um:
        return out
    try:
        out["prompt"] = int(getattr(um, "prompt_token_count", None) or 0)
        out["cached"] = int(getattr(um, "cached_content_token_count", None) or 0)
        out["output"] = int(getattr(um, "candidates_token_count", None) or 0)
        out["thoughts"] = int(getattr(um, "thoughts_token_count", None) or 0)
        out["total"] = int(getattr(um, "total_token_count", None) or 0)
    except (TypeError, ValueError) as err:
        _logger.debug("Gemini usage_metadata parse: %s", err)
    return out


def gemini_usage_dict_from_stream_chunk(chunk):
    """Algunos chunks finales exponen usage_metadata."""
    um = getattr(chunk, "usage_metadata", None)
    if not um:
        return None
    fake = type("R", (), {"usage_metadata": um})()
    return gemini_usage_dict_from_response(fake)
