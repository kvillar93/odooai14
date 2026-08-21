# -*- coding: utf-8 -*-
from odoo import models
from odoo.http import request


class IrHttp(models.AbstractModel):
    _inherit = "ir.http"

    def session_info(self):
        """Expone al frontend si el usuario actual pertenece al grupo de
        depuración de herramientas LLM. Los componentes OWL del chat LLM
        usan este flag para mostrar u ocultar las tarjetas técnicas de
        ``tool_use`` / ``tool_result``."""
        result = super().session_info()
        try:
            is_debug = bool(
                request
                and request.session
                and request.session.uid
                and self.env.user.has_group(
                    "llm_experience.group_llm_tool_debug"
                )
            )
        except Exception:
            is_debug = False
        result["llm_tool_debug"] = is_debug
        return result
