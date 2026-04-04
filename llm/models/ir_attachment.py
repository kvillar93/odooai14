# -*- coding: utf-8 -*-
"""Extracción de texto de adjuntos para el contexto LLM."""

import base64
import io
import logging

from odoo import models
from odoo.tools import html2plaintext

_logger = logging.getLogger(__name__)

# Límite por archivo para no saturar el contexto del modelo
MAX_LLM_TEXT_CHARS = 200000


class IrAttachment(models.Model):
    _inherit = "ir.attachment"

    def _llm_get_raw_bytes(self):
        self.ensure_one()
        if self.raw:
            return self.raw
        if self.datas:
            if isinstance(self.datas, bytes):
                return self.datas
            return base64.b64decode(self.datas)
        return b""

    def llm_extract_text(self):
        """Devuelve texto plano extraído del adjunto para enviarlo al modelo, o cadena vacía."""
        self.ensure_one()
        raw = self._llm_get_raw_bytes()
        if not raw:
            return ""
        mimetype = (self.mimetype or "").lower()
        name = (self.name or "").lower()

        try:
            if mimetype == "text/html" or name.endswith((".html", ".htm")):
                return html2plaintext(
                    raw.decode("utf-8", errors="replace")
                )[:MAX_LLM_TEXT_CHARS]

            if mimetype.startswith("text/") or mimetype == "application/json":
                return raw.decode("utf-8", errors="replace")[:MAX_LLM_TEXT_CHARS]

            # PDF
            if mimetype == "application/pdf" or name.endswith(".pdf"):
                return self._llm_extract_pdf_text(raw)

            # Word .docx
            if "wordprocessingml" in mimetype or name.endswith(".docx"):
                return self._llm_extract_docx_text(raw)

        except Exception as err:
            _logger.warning(
                "No se pudo extraer texto del adjunto %s (%s): %s",
                self.id,
                self.name,
                err,
            )
        return ""

    def _llm_extract_pdf_text(self, raw_bytes):
        try:
            from pypdf import PdfReader
        except ImportError:
            try:
                from PyPDF2 import PdfReader
            except ImportError:
                _logger.warning(
                    "Instale el paquete Python 'pypdf' para extraer texto de PDFs en el chat LLM."
                )
                return ""
        try:
            reader = PdfReader(io.BytesIO(raw_bytes))
            chunks = []
            for page in reader.pages:
                chunks.append(page.extract_text() or "")
            text = "\n".join(chunks).strip()
            return text[:MAX_LLM_TEXT_CHARS]
        except Exception as err:
            _logger.warning("Error leyendo PDF adjunto: %s", err)
            return ""

    def _llm_extract_docx_text(self, raw_bytes):
        try:
            import docx
        except ImportError:
            _logger.debug("python-docx no instalado; omitiendo .docx")
            return ""
        try:
            document = docx.Document(io.BytesIO(raw_bytes))
            return "\n".join(p.text for p in document.paragraphs)[:MAX_LLM_TEXT_CHARS]
        except Exception as err:
            _logger.warning("Error leyendo DOCX: %s", err)
            return ""
