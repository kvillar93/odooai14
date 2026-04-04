{
    "name": "LLM Tareas Programadas",
    "version": "16.0.1.0.0",
    "category": "Productivity",
    "summary": "Automatiza tareas LLM mediante prompts y cron jobs",
    "description": """
LLM Tareas Programadas
=======================
Permite crear tareas que ejecutan un prompt LLM de forma recurrente (diaria, semanal, mensual…).

Características:
- Configuración de tareas mediante prompt de lenguaje natural.
- Integración con asistentes LLM, herramientas y proveedores existentes.
- Scheduler basado en ir.cron: diario, semanal, mensual y más.
- Un chat dedicado por tarea (reutilizable en cada ciclo).
- Log de ejecuciones con estado, duración y mensajes generados.
- Botón de acceso desde el formulario de llm.thread.
- Menú propio dentro del módulo LLM.
    """,
    "author": "Custom",
    "website": "",
    "depends": ["mail", "llm", "llm_tool", "llm_thread", "llm_assistant"],
    "data": [
        "security/llm_scheduled_task_security.xml",
        "security/ir.model.access.csv",
        "data/llm_tool_scheduled_task_data.xml",
        "data/llm_tool_mail_sender_data.xml",
        "views/llm_scheduled_task_views.xml",
        "views/llm_thread_inherit_views.xml",
        "views/menu.xml",
    ],
    "installable": True,
    "application": False,
    "auto_install": False,
    "license": "LGPL-3",
    "assets": {
        "web.assets_backend": [
            "llm_scheduled_task/static/src/components/llm_chat_sidebar/llm_chat_sidebar.js",
            "llm_scheduled_task/static/src/components/llm_chat_sidebar/llm_chat_sidebar.xml",
        ],
    },
}
