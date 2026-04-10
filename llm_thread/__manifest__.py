# -*- coding: utf-8 -*-
{
    "name": "Easy AI Chat",
    "summary": "Simple AI Chat for Odoo",
    "description": """
Easy AI Chat for Odoo
=====================
Chat de IA integrado con el sistema de correo de Odoo (mail), proveedores múltiples y herramientas.
    """,
    "category": "Productivity, Discuss",
    "version": "14.0.1.5.4",
    "depends": ["mail", "web", "llm", "llm_tool"],
    "author": "Apexive Solutions LLC",
    "website": "https://github.com/apexive/odoo-llm",
    "external_dependencies": {"python": ["emoji", "markdown2"]},
    "data": [
        "security/llm_thread_security.xml",
        "security/ir.model.access.csv",
        "views/llm_thread_views.xml",
        "views/menu.xml",
        "views/assets.xml",
    ],
    "qweb": [
        "static/src/llm_chat_client_action.xml",
        "static/src/components/llm_chat/llm_chat.xml",
        "static/src/components/llm_chat_thread_list/llm_chat_thread_list.xml",
        "static/src/components/llm_chat_thread/llm_chat_thread.xml",
        "static/src/components/llm_chat_container/llm_chat_container.xml",
        "static/src/components/llm_chat_sidebar/llm_chat_sidebar.xml",
        "static/src/components/llm_chat_composer/llm_chat_composer.xml",
        "static/src/components/llm_chat_composer_text_input/llm_chat_composer_text_input.xml",
        "static/src/components/llm_chat_thread_header/llm_chat_thread_header.xml",
        "static/src/components/llm_streaming_indicator/llm_streaming_indicator.xml",
        "static/src/components/llm_chatter_topbar/llm_chatter_topbar.xml",
        "static/src/components/llm_chatter/llm_chatter.xml",
        "static/src/components/message/message.xml",
        "static/src/components/llm_chat_thread_related_record/llm_chat_thread_related_record.xml",
        "static/src/systray/llm_floating_systray.xml",
    ],
    "images": [
        "static/description/banner.jpeg",
    ],
    "license": "LGPL-3",
    "installable": True,
    "application": True,
    "auto_install": False,
}
