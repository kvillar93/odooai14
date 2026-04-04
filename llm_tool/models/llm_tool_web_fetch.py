# -*- coding: utf-8 -*-
import logging
from urllib.parse import urlparse

import requests

from odoo import api, models
from odoo.tools import html2plaintext

_logger = logging.getLogger(__name__)


class LLMToolWebFetch(models.Model):
    _inherit = "llm.tool"

    @api.model
    def _get_available_implementations(self):
        implementations = super()._get_available_implementations()
        return implementations + [("web_fetch", "Consulta web (HTTP GET)")]

    def web_fetch_execute(self, url: str, max_chars: int = 50000) -> dict:
        """Descarga una URL pública (GET) y devuelve texto legible para el modelo."""
        self.ensure_one()
        url = (url or "").strip()
        if not url:
            return {"error": "URL vacía."}
        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https"):
            return {"error": "Solo se permiten URLs http o https."}
        host = (parsed.hostname or "").lower()
        if host in ("localhost", "127.0.0.1", "::1") or host.endswith(".local"):
            return {"error": "URL no permitida (host local o loopback)."}

        max_chars = int(max(2000, min(max_chars, 500000)))

        try:
            resp = requests.get(
                url,
                timeout=30,
                headers={
                    "User-Agent": "Odoo-LLM-web_fetch/1.0",
                    "Accept": (
                        "text/html,application/xhtml+xml,application/json,"
                        "text/plain;q=0.9,*/*;q=0.8"
                    ),
                },
                allow_redirects=True,
            )
        except requests.RequestException as err:
            return {"error": str(err)}

        if len(resp.content) > 5 * 1024 * 1024:
            return {"error": "Respuesta demasiado grande (máx. 5 MB)."}

        ct = (resp.headers.get("Content-Type") or "").lower()
        text = resp.text

        if "html" in ct:
            text = html2plaintext(text)
        elif "json" not in ct:
            try:
                text = resp.content.decode(resp.encoding or "utf-8", errors="replace")
            except Exception:
                text = resp.text

        if len(text) > max_chars:
            text = text[:max_chars] + "\n… [contenido truncado]"

        return {
            "url": resp.url,
            "status_code": resp.status_code,
            "content_type": ct,
            "content": text,
        }
