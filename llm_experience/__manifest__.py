# -*- coding: utf-8 -*-
{
    "name": "Experiencia LLM (contexto, Gemini, investigación)",
    "summary": "Medidor de contexto/tokens, compactación, modos pensamiento/investigación y orquestador extensible",
    "version": "16.0.1.0.0",
    "category": "Productivity",
    "depends": [
        "mail",
        "llm",
        "llm_gemini",
        "llm_thread",
        "llm_tool",
        "llm_assistant",
    ],
    "author": "Custom",
    "license": "LGPL-3",
    "data": [
        "security/ir.model.access.csv",
        "security/llm_experience_security.xml",
        "data/llm_experience_cron.xml",
        "views/llm_thread_experience_views.xml",
    ],
    "post_init_hook": "post_init_hook",
    "assets": {
        "web.assets_backend": [
            "llm_experience/static/src/components/llm_context_meter/llm_context_meter.scss",
            "llm_experience/static/src/components/llm_context_meter/llm_context_meter.xml",
            "llm_experience/static/src/components/llm_context_meter/llm_context_meter.js",
            "llm_experience/static/src/components/llm_chat_composer_experience/llm_chat_composer_experience.xml",
            "llm_experience/static/src/components/llm_chat_composer_experience/llm_chat_composer_experience.js",
            "llm_experience/static/src/js/llm_chat_cost_patch.js",
            "llm_experience/static/src/xml/llm_chat_thread_list_cost_tooltip.xml",
        ],
    },
    "installable": True,
    "application": False,
}
