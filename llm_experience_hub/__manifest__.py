# -*- coding: utf-8 -*-
{
    "name": "Hub seguimiento costes LLM Experience",
    "summary": "Sincroniza desde instancias cliente el resumen de costes de llm_experience (cada 6 h).",
    "version": "14.0.1.0.0",
    "category": "Productivity",
    "depends": ["base"],
    "author": "Custom",
    "license": "LGPL-3",
    "data": [
        "security/ir.model.access.csv",
        "data/llm_experience_hub_cron.xml",
        "views/llm_experience_hub_views.xml",
    ],
    "installable": True,
    "application": True,
}
