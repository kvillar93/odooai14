# -*- coding: utf-8 -*-
import logging

from odoo import SUPERUSER_ID, api

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    """Añade web_fetch a los asistentes demo si el registro existe (tras actualizar llm_tool)."""
    env = api.Environment(cr, SUPERUSER_ID, {})
    tool = env.ref("llm_tool.llm_tool_web_fetch", raise_if_not_found=False)
    if not tool:
        _logger.info(
            "llm_assistant 16.0.1.5.5: llm_tool.llm_tool_web_fetch no encontrado; "
            "actualice el módulo llm_tool y vuelva a actualizar llm_assistant."
        )
        return
    for xmlid in (
        "llm_assistant.llm_assistant_creator",
        "llm_assistant.llm_assistant_website_builder",
    ):
        assistant = env.ref(xmlid, raise_if_not_found=False)
        if assistant and tool not in assistant.tool_ids:
            assistant.write({"tool_ids": [(4, tool.id)]})
            _logger.info(
                "llm_assistant 16.0.1.5.5: herramienta web_fetch enlazada a %s", xmlid
            )
