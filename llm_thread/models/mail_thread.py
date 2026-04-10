# -*- coding: utf-8 -*-
"""Seguridad de notificaciones: las asignaciones tipo backend no deben enviarse a contactos externos."""

import logging

from odoo import models

_logger = logging.getLogger(__name__)

# Misma plantilla que mail/mail_activity/project usan para “asignado a…” (banner comunicación interna)
_MAIL_LAYOUT_ASSIGNMENT = "mail.mail_notification_layout"


class MailThread(models.AbstractModel):
    _inherit = "mail.thread"

    def _llm_notify_partner_ids_internal_only(self, partner_ids):
        """Conserva solo partners con al menos un usuario interno activo (share=False)."""
        if not partner_ids:
            return []
        partners = self.env["res.partner"].sudo().browse(partner_ids)
        kept = []
        for partner in partners:
            internal = partner.user_ids.filtered(lambda u: u.active and not u.share)
            if internal:
                kept.append(partner.id)
            else:
                _logger.warning(
                    "Notificación de asignación omitida para partner id=%s (%s): no es usuario interno.",
                    partner.id,
                    partner.email or partner.name or "",
                )
        return kept

    def _llm_should_filter_assignment_recipients(self, kwargs):
        """Solo filtrar el flujo estándar de asignación (model_description + plantilla interna)."""
        layout = kwargs.get("email_layout_xmlid")
        if layout and layout != _MAIL_LAYOUT_ASSIGNMENT:
            return False
        if not kwargs.get("model_description"):
            return False
        return True

    def message_notify(self, *, partner_ids=False, **kwargs):
        if partner_ids and self._llm_should_filter_assignment_recipients(kwargs):
            partner_ids = self._llm_notify_partner_ids_internal_only(list(partner_ids))
            if not partner_ids:
                _logger.warning(
                    "message_notify (asignación): sin destinatarios internos; no se envía correo."
                )
                return self.env["mail.message"]
        return super().message_notify(partner_ids=partner_ids, **kwargs)
