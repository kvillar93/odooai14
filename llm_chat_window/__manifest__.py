# -*- coding: utf-8 -*-
{
    "name": "Ventanas de chat LLM",
    "summary": "Menús con chat preconfigurado (modelo, tools, asistente) y cabecera bloqueada",
    "version": "14.0.1.1.0",
    "category": "Productivity",
    "depends": ["llm_assistant", "llm_thread"],
    "data": [
        "security/ir.model.access.csv",
        "views/llm_chat_window_views.xml",
        "views/llm_chat_window_menu_wizard_views.xml",
        "data/menu.xml",
    ],
    "license": "LGPL-3",
    "installable": True,
    "application": False,
}
