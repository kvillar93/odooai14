# -*- coding: utf-8 -*-
{
    "name": "LLM Google Gemini",
    "summary": "Proveedor Google Gemini para chat y tools",
    "version": "16.0.1.2.0",
    "depends": ["llm", "llm_tool", "llm_openai"],
    "external_dependencies": {"python": ["google-genai"]},
    "data": [
        "views/llm_model_views.xml",
    ],
    "license": "LGPL-3",
    "installable": True,
}
