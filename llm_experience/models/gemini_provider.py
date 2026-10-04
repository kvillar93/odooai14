# -*- coding: utf-8 -*-
import logging

from odoo import models

_logger = logging.getLogger(__name__)


class LLMProvider(models.Model):
    _inherit = "llm.provider"

    def gemini_chat(
        self,
        messages,
        model=None,
        stream=False,
        tools=None,
        prepend_messages=None,
        **kwargs,
    ):
        """Añade el esfuerzo de razonamiento del hilo y registra el uso de tokens.

        La estimación previa se hace localmente en el hilo
        (``_context_preflight``): ``count_tokens`` de la Gemini API no admite
        ``system_instruction`` y añadía una llamada HTTP por ronda.
        """
        thread = kwargs.pop("llm_thread", None)
        if thread is not None and not kwargs.get("reasoning_effort"):
            kwargs["reasoning_effort"] = thread._experience_effective_reasoning_effort()
        if (
            stream
            and thread is not None
            and not thread.env.context.get("llm_compaction_call")
            and "experience_include_thoughts" not in kwargs
        ):
            kwargs["experience_include_thoughts"] = thread._experience_show_thinking()

        res = super().gemini_chat(
            messages,
            model=model,
            stream=stream,
            tools=tools,
            prepend_messages=prepend_messages,
            **kwargs,
        )

        if stream:
            return self._experience_wrap_gemini_stream(res, thread)
        if isinstance(res, dict):
            usage = res.pop("_usage_internal", None)
            if usage and thread is not None:
                self._experience_apply_usage(thread, usage)
        return res

    def _experience_apply_usage(self, thread, usage):
        try:
            thread.usage_apply_llm_response(usage)
        except Exception as err:
            _logger.warning("No se pudo registrar el uso de tokens: %s", err)

    def _experience_wrap_gemini_stream(self, gen, thread):
        for chunk in gen:
            if isinstance(chunk, dict):
                usage = chunk.pop("_usage_internal", None)
                if usage:
                    if thread is not None:
                        self._experience_apply_usage(thread, usage)
                    # Uso de esta petición para mostrarlo en el mensaje.
                    chunk["usage_info"] = {
                        key: usage.get(key, 0)
                        for key in ("prompt", "cached", "output", "thoughts")
                    }
            yield chunk
