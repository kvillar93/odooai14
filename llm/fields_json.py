# -*- coding: utf-8 -*-
"""Campo JSON almacenado en columna TEXT — compatible con Odoo 14 (sin fields.Json en core)."""
import json

from odoo.fields import Field
from odoo.tools import ustr


class Json(Field):
    """Similar a fields.Json de Odoo 15+; persistencia como texto JSON en PostgreSQL."""

    type = "json"
    column_type = ("text", "text")
    column_cast_from = ("varchar",)

    def convert_to_column(self, value, record, values=None, validate=True):
        if value is None or value is False:
            return None
        if isinstance(value, str):
            return value
        return json.dumps(value, ensure_ascii=False, default=str)

    def convert_to_cache(self, value, record, validate=True):
        if value is None or value is False:
            return None
        if isinstance(value, str):
            s = value.strip()
            if not s:
                return None
            try:
                return json.loads(s)
            except (ValueError, TypeError):
                return None
        if isinstance(value, (dict, list)):
            return json.loads(json.dumps(value, ensure_ascii=False, default=str))
        return value

    def _ensure_parsed(self, value):
        """Garantiza que el valor sea un objeto Python (dict/list), no un string JSON."""
        if value is None or value is False:
            return False
        if isinstance(value, str):
            s = value.strip()
            if not s:
                return False
            try:
                return json.loads(s)
            except (ValueError, TypeError):
                return False
        return value

    def convert_to_record(self, value, record):
        return self._ensure_parsed(value)

    def convert_to_read(self, value, record, use_name_get=True):
        return self._ensure_parsed(value)

    def convert_to_export(self, value, record):
        if value is None or value is False:
            return ""
        if isinstance(value, (dict, list)):
            return json.dumps(value, ensure_ascii=False)
        return ustr(value)
