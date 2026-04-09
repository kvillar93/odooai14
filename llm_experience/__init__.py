# -*- coding: utf-8 -*-
import secrets

from odoo import SUPERUSER_ID, api

from . import controllers
from . import models


def post_init_hook(cr, registry):
    """Genera token de sincronización para el hub si no existe."""
    env = api.Environment(cr, SUPERUSER_ID, {})
    icp = env["ir.config_parameter"].sudo()
    if not (icp.get_param("llm_experience.hub_sync_token") or "").strip():
        icp.set_param("llm_experience.hub_sync_token", secrets.token_hex(24))
