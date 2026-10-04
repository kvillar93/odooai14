import logging

from odoo import _, api, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)



class LLMProvider(models.Model):
    _inherit = "llm.provider"

    def _llm_supports_transcription(self):
        self.ensure_one()
        return bool(self.service) and hasattr(self, f"{self.service}_transcribe_audio")

    @api.model
    def llm_transcribe_audio(self, data, mimetype, thread=None):
        """Dictado por voz: convierte audio en texto.

        Usa el proveedor del hilo si sabe transcribir; si no, el primer proveedor
        activo que lo soporte (Gemini, OpenAI…).
        """
        if not data:
            raise UserError(_("El audio está vacío."))
        providers = self.browse()
        model = None
        if thread:
            providers |= thread.sudo().provider_id
            model = thread.sudo().model_id
        providers |= self.sudo().search([("active", "=", True)], order="id")
        errors = []
        for provider in providers.sudo():
            if not provider._llm_supports_transcription():
                continue
            hint = model if model and model.provider_id == provider else None
            try:
                text = provider._dispatch("transcribe_audio", data, mimetype, model=hint)
                return (text or "").strip()
            except Exception as err:  # noqa: BLE001 - se prueba el siguiente proveedor
                _logger.warning("Transcripción con %s falló: %s", provider.name, err)
                errors.append(f"{provider.name}: {err}")
        if errors:
            raise UserError(_("No se pudo transcribir el audio. %s") % errors[-1])
        raise UserError(
            _("Ningún proveedor de IA configurado admite transcripción de voz (Gemini u OpenAI).")
        )
