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
        thread = kwargs.get("llm_thread")
        exp_kwargs = self._experience_build_gemini_experience_kwargs(thread)
        kwargs.update(exp_kwargs)

        if thread and self.service == "gemini":
            est = self._experience_gemini_count_tokens(
                messages, model, tools, prepend_messages, kwargs
            )
            if est is not None:
                try:
                    thread.usage_apply_gemini_estimated_prompt(est)
                except Exception as err:
                    _logger.debug("usage_apply_gemini_estimated_prompt: %s", err)

        kwargs.pop("llm_thread", None)
        res = super().gemini_chat(
            messages,
            model=model,
            stream=stream,
            tools=tools,
            prepend_messages=prepend_messages,
            **kwargs,
        )

        if stream and thread:
            return self._experience_wrap_gemini_stream(res, thread)
        if not stream and thread and isinstance(res, dict):
            u = res.pop("_usage_internal", None)
            if u:
                try:
                    thread.usage_apply_gemini_response(u)
                except Exception as err:
                    _logger.debug("usage_apply_gemini_response: %s", err)
            else:
                res.pop("_usage_internal", None)
        elif isinstance(res, dict):
            res.pop("_usage_internal", None)
        return res

    def _experience_build_gemini_experience_kwargs(self, thread):
        """Pensamiento profundo / flags para llm_gemini."""
        if not thread:
            return {}
        out = {}
        if thread.chat_work_mode == "deep_thinking":
            budget = int(thread.gemini_thinking_budget or 8192)
            out["experience_thinking_budget"] = max(1, budget)
            out["experience_include_thoughts"] = False
        return out

    def _experience_gemini_count_tokens(
        self, messages, model, tools, prepend_messages, kwargs
    ):
        """Llama a count_tokens del SDK con el mismo contenido que el chat."""
        self.ensure_one()
        try:
            from google.genai import types as genai_types
        except ImportError:
            return None
        try:
            model_obj = self.get_model(model, "chat")
            client = self.gemini_get_client()
            openai_style = self._gemini_build_openai_style_message_list(
                prepend_messages, messages
            )
            if kwargs.get("system_prompt"):
                openai_style = [
                    {"role": "system", "content": kwargs["system_prompt"]}
                ] + openai_style
            contents, system_instruction = self._gemini_build_contents(openai_style)

            config_kwargs = {}
            if system_instruction:
                config_kwargs["system_instruction"] = system_instruction
            has_odoo_tools = bool(tools)
            use_gs = getattr(model_obj, "gemini_google_search_grounding", False)
            if has_odoo_tools:
                declarations = self.gemini_format_tools(tools)
                config_kwargs["tools"] = [
                    genai_types.Tool(function_declarations=declarations)
                ]
                config_kwargs["tool_config"] = self._gemini_build_tool_config_function_auto(
                    genai_types, use_gs
                )
                config_kwargs["thinking_config"] = genai_types.ThinkingConfig(
                    thinking_budget=0
                )
            exp_tb = kwargs.get("experience_thinking_budget")
            if exp_tb is not None and int(exp_tb) > 0:
                config_kwargs["thinking_config"] = genai_types.ThinkingConfig(
                    thinking_budget=int(exp_tb),
                    include_thoughts=bool(kwargs.get("experience_include_thoughts")),
                )
            if use_gs:
                config_kwargs.setdefault("tools", [])
                config_kwargs["tools"].append(
                    genai_types.Tool(google_search=genai_types.GoogleSearch())
                )
            config = (
                genai_types.GenerateContentConfig(**config_kwargs)
                if config_kwargs
                else None
            )
            resp = client.models.count_tokens(
                model=model_obj.name,
                contents=contents,
                config=config,
            )
            total = getattr(resp, "total_tokens", None)
            if total is not None:
                return int(total)
        except Exception as err:
            _logger.debug("Gemini count_tokens: %s", err)
        return None

    def _experience_wrap_gemini_stream(self, gen, thread):
        for chunk in gen:
            if isinstance(chunk, dict):
                u = chunk.pop("_usage_internal", None)
                if u:
                    try:
                        thread.usage_apply_gemini_response(u)
                    except Exception as err:
                        _logger.debug("stream usage: %s", err)
            yield chunk
