{
    "name": "LLM Content Generation",
    "version": "16.0.2.1.0",
    "category": "Productivity/Discuss",
    "summary": "Content generation capabilities for LLM models",
    "description": """
        Clean content generation using LLM models with the new generate() API.

        Features:
        - Uses body_json for structured generation data
        - Simple prompt rendering with context merging
        - Direct integration with main LLM module's generate() method
        - Minimal, clean code with focused functionality
        - Works with details field for schema storage
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
    ],
    "assets": {
        "web.assets_backend": [
            # JavaScript Models
            "llm_generate/static/src/models/llm_model.js",
            "llm_generate/static/src/models/llm_chat.js",
            "llm_generate/static/src/models/composer.js",
            "llm_generate/static/src/models/message.js",
            # Components
            "llm_generate/static/src/components/llm_media_form/llm_form_fields_view.js",
            "llm_generate/static/src/components/llm_media_form/llm_media_form.js",
            "llm_generate/static/src/components/llm_chat_composer/llm_chat_composer.js",
            # Templates
            "llm_generate/static/src/components/llm_media_form/llm_form_fields_view.xml",
            "llm_generate/static/src/components/llm_media_form/llm_media_form.xml",
            "llm_generate/static/src/components/llm_chat_composer/llm_chat_composer.xml",
            "llm_generate/static/src/components/message/message.xml",
            # Styles
            "llm_generate/static/src/components/llm_media_form/llm_media_form.scss",
            "llm_generate/static/src/components/message/message.scss",
        ],
    },
    "installable": True,
    "application": False,
    "auto_install": False,
    "license": "LGPL-3",
}
