# -*- coding: utf-8 -*-
"""Enlaces post-instalación / migración: herramienta web_fetch en asistentes demo."""


def _link_web_fetch_to_demo_assistants(env):
    tool = env.ref("llm_tool.llm_tool_web_fetch", raise_if_not_found=False)
    if not tool:
        return
    for xmlid in (
        "llm_assistant.llm_assistant_creator",
        "llm_assistant.llm_assistant_website_builder",
    ):
        assistant = env.ref(xmlid, raise_if_not_found=False)
        if assistant and tool not in assistant.tool_ids:
            assistant.write({"tool_ids": [(4, tool.id)]})


def post_init_hook(cr, registry):
    from odoo import SUPERUSER_ID, api

    env = api.Environment(cr, SUPERUSER_ID, {})
    _link_web_fetch_to_demo_assistants(env)
