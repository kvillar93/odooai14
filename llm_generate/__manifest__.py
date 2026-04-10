# -*- coding: utf-8 -*-
{
    "name": "LLM Content Generation",
    "version": "14.0.2.1.0",
    "category": "Productivity/Discuss",
    "summary": "Generación de contenido con modelos LLM (API generate)",
    "description": """
Generación de contenido mediante modelos LLM y la API generate().

Características:
- Uso de body_json para datos estructurados
- Integración con el módulo llm y el chat de hilos
- Formulario de medios según esquema del modelo o del prompt
    """,
    "author": "Apexive Solutions LLC",
    "website": "https://github.com/apexive/odoo-llm",
    "depends": [
        "llm",
        "llm_thread",
        "llm_assistant",
        "web_json_editor",
    ],
    "data": [
        "data/llm_tool_data.xml",
        "views/llm_model_views.xml",
        "views/assets.xml",
    ],
    "qweb": [
        "static/src/components/llm_media_form/llm_form_fields_view.xml",
        "static/src/components/llm_media_form/llm_media_form.xml",
        "static/src/components/llm_chat_composer/llm_chat_composer.xml",
        "static/src/components/message/message.xml",
    ],
    "installable": True,
    "application": False,
    "auto_install": False,
    "license": "LGPL-3",
}
