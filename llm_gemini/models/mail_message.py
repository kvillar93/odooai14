# -*- coding: utf-8 -*-
from odoo import models


class MailMessage(models.Model):
    _inherit = "mail.message"

    def gemini_format_message(self):
        """Formato similar a OpenAI para reutilizar historial."""
        return self.openai_format_message()
