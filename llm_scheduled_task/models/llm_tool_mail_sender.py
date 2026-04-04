# -*- coding: utf-8 -*-
import html
import json
import logging
import re
from typing import Any, Optional

from odoo import _, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

# Validación básica de dirección (no sustituye un validador completo RFC)
_EMAIL_PART = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


class LLMToolMailSender(models.Model):
    """Implementación llm_mail_sender (registrada en llm_tool_scheduled_task._get_available_implementations)."""

    _inherit = "llm.tool"

    def _llm_mail_split_addresses(self, raw: str):
        """Separa direcciones por coma, punto y coma o saltos de línea."""
        if not raw or not str(raw).strip():
            return []
        parts = re.split(r"[,;\n\r]+", str(raw))
        return [p.strip() for p in parts if p.strip()]

    def _llm_mail_validate_addresses(self, addresses):
        bad = [a for a in addresses if not _EMAIL_PART.match(a)]
        if bad:
            raise UserError(
                _("Direcciones de correo no válidas: %s")
                % ", ".join(bad[:5])
            )

    def _llm_mail_body_to_html(self, body: str, is_html: bool) -> str:
        text = (body or "").strip()
        if not text:
            raise UserError(_("El cuerpo del correo está vacío."))
        if is_html:
            return text
        return "<div>%s</div>" % html.escape(text).replace("\n", "<br/>")

    def _llm_mail_parse_attachment_ids(self, raw: Optional[str]):
        if not raw or not str(raw).strip():
            return []
        raw = str(raw).strip()
        if raw.startswith("["):
            try:
                data = json.loads(raw)
            except json.JSONDecodeError as e:
                raise UserError(_("attachment_ids no es un JSON válido: %s") % e) from e
            if not isinstance(data, list):
                raise UserError(_("attachment_ids debe ser una lista de IDs numéricos."))
            return [int(x) for x in data if str(x).isdigit()]
        return [int(x.strip()) for x in raw.split(",") if x.strip().isdigit()]

    def _llm_mail_resolve_email_from(self, email_from: Optional[str]) -> str:
        """Remitente: solo administradores pueden fijar un remitente arbitrario."""
        user = self.env.user
        company = self.env.company
        default = user.email_formatted or company.email_formatted
        if not default:
            raise UserError(
                _(
                    "No hay dirección de correo de remitente: configura el correo del usuario "
                    "o el de la compañía."
                )
            )
        if email_from and str(email_from).strip():
            candidate = str(email_from).strip()
            if user.has_group("base.group_system"):
                return candidate
            # Usuario normal: solo si coincide con su correo o el de la compañía
            if user.email and candidate.lower() == user.email.lower():
                return candidate
            if company.email and candidate.lower() == company.email.lower():
                return candidate
        return default

    def llm_mail_sender_execute(
        self,
        to_emails: str,
        subject: str,
        body: str,
        is_html: bool = False,
        cc_emails: Optional[str] = None,
        reply_to: Optional[str] = None,
        email_from: Optional[str] = None,
        attachment_ids: Optional[str] = None,
    ) -> dict[str, Any]:
        """
        to_emails: Destinatarios (To), separados por coma, punto y coma o salto de línea.
        subject: Asunto del correo.
        body: Cuerpo del mensaje. Si is_html es False, se escapa y se convierte a HTML seguro.
        is_html: True si el cuerpo ya es HTML confiable generado por ti.
        cc_emails: Opcional. Copia (Cc), mismo formato que to_emails.
        reply_to: Opcional. Cabecera Reply-To (una dirección).
        email_from: Opcional. Remitente; solo administradores pueden usar un valor distinto al correo del usuario/compañía.
        attachment_ids: Opcional. Lista de IDs de ir.attachment separados por coma o JSON [1,2,3]. Deben ser accesibles por el usuario.
        """
        self.ensure_one()

        if not subject or not str(subject).strip():
            raise UserError(_("El asunto (subject) es obligatorio."))

        to_list = self._llm_mail_split_addresses(to_emails)
        if not to_list:
            raise UserError(_("Debes indicar al menos un destinatario en to_emails."))
        self._llm_mail_validate_addresses(to_list)

        cc_list = self._llm_mail_split_addresses(cc_emails) if cc_emails else []
        if cc_list:
            self._llm_mail_validate_addresses(cc_list)

        body_html = self._llm_mail_body_to_html(body, is_html)
        email_from_final = self._llm_mail_resolve_email_from(email_from)

        att_ids = self._llm_mail_parse_attachment_ids(attachment_ids)
        if att_ids:
            Attachment = self.env["ir.attachment"].sudo()
            atts = Attachment.browse(att_ids)
            missing = atts.filtered(lambda a: not a.exists())
            if missing:
                raise UserError(_("Adjuntos inexistentes: %s") % missing.ids)
            # Comprobar que el usuario puede leer los adjuntos (sin sudo en check)
            atts_user = self.env["ir.attachment"].browse(att_ids)
            for att in atts_user:
                try:
                    att.check("read")
                except Exception as err:
                    raise UserError(
                        _("No tienes permiso para usar el adjunto id=%s: %s")
                        % (att.id, err)
                    ) from err

        mail_vals = {
            "subject": str(subject).strip(),
            "body_html": body_html,
            "email_to": ", ".join(to_list),
            "email_cc": ", ".join(cc_list) if cc_list else False,
            "email_from": email_from_final,
            "reply_to": str(reply_to).strip() if reply_to and str(reply_to).strip() else False,
        }
        if att_ids:
            mail_vals["attachment_ids"] = [(6, 0, att_ids)]

        Mail = self.env["mail.mail"].sudo()
        mail = Mail.create(mail_vals)
        mail.send()

        mail.invalidate_recordset(["state", "failure_reason"])
        ok = mail.state == "sent"
        return {
            "ok": ok,
            "mail_id": mail.id,
            "estado": mail.state,
            "destinatarios": mail_vals["email_to"],
            "asunto": mail_vals["subject"],
            "mensaje": (
                _("Correo enviado correctamente (estado: sent).")
                if ok
                else _(
                    "El correo no se envió correctamente. Estado: %(state)s. Motivo: %(reason)s"
                )
                % {"state": mail.state, "reason": mail.failure_reason or _("(sin detalle)")}
            ),
        }
