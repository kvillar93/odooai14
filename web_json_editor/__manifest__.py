# -*- coding: utf-8 -*-
{
    "name": "Web JSON Editor",
    "version": "14.0.1.0.0",
    "category": "Web",
    "summary": "Widget de editor JSON para Odoo",
    "description": """
        Proporciona un widget reutilizable de editor JSON para Odoo con autocompletado basado en esquema.
        Características: resaltado de sintaxis JSON, autocompletado, modos de vista, validación.
    """,
    "depends": [
        "web",
    ],
    "data": [
        "views/assets.xml",
    ],
    "qweb": [
        "static/src/fields/json_field.xml",
        "static/src/components/json_editor/json_editor.xml",
    ],
    "author": "Apexive Solutions LLC",
    "website": "https://github.com/apexive/odoo-llm",
    "installable": True,
    "application": False,
    "auto_install": False,
    "license": "LGPL-3",
}
