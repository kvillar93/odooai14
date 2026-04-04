# -*- coding: utf-8 -*-
import json
import logging

from odoo import _, models
from odoo.models import BaseModel

_logger = logging.getLogger(__name__)

_SKIP_X2M_NAMES = frozenset(
    {
        "message_ids",
        "message_follower_ids",
        "activity_ids",
        "rating_ids",
        "website_message_ids",
    }
)


class LLMThread(models.Model):
    _inherit = "llm.thread"

    def _get_extra_prepend_messages(self):
        """Hook: otros módulos (p. ej. conocimiento de módulos) pueden añadir mensajes aquí."""
        return []

    def get_prepend_messages(self):
        """Antepone contexto del registro vinculado y luego mensajes del prompt."""
        self.ensure_one()
        prepend = []
        prepend.extend(self._get_related_record_prepend_messages())
        prepend.extend(self._get_extra_prepend_messages())
        if self.prompt_id:
            try:
                prepend.extend(self.prompt_id.get_messages(self.get_context()))
            except Exception as e:
                _logger.error(
                    "Error getting messages from prompt '%s': %s",
                    self.prompt_id.name,
                    str(e),
                )
                self.message_post(
                    body=f"Advertencia: no se pudieron cargar mensajes del prompt "
                    f"'{self.prompt_id.name}': {str(e)}"
                )
        return prepend

    def _get_related_record_prepend_messages(self):
        """Mensajes system con snapshot del registro vinculado (chatter)."""
        self.ensure_one()
        if not self.model or not self.res_id:
            return []
        try:
            record = self.env[self.model].browse(int(self.res_id))
        except KeyError:
            _logger.warning("Modelo relacionado inexistente: %s", self.model)
            return []
        if not record.exists():
            return []
        try:
            snapshot = self._serialize_record_snapshot(
                record, depth=0, max_depth=2, visited=set()
            )
        except Exception as e:
            _logger.warning("No se pudo serializar registro relacionado: %s", e)
            return []
        text = json.dumps(snapshot, ensure_ascii=False, indent=2, default=str)
        max_chars = 120000
        if len(text) > max_chars:
            text = text[:max_chars] + "\n… [contenido truncado por tamaño]"
        instruction = _(
            "El usuario está consultando principalmente en el contexto del siguiente "
            "documento de Odoo. Interpreta las preguntas en relación con este registro "
            "salvo que indique explícitamente otro alcance.\n\n"
            "Modelo técnico: %(model)s\n"
            "ID: %(rid)s\n"
            "Nombre: %(name)s\n\n"
            "Datos estructurados (incluye relaciones hasta 2 niveles):\n"
        ) % {
            "model": self.model,
            "rid": self.res_id,
            "name": record.display_name,
        }
        return [{"role": "system", "content": instruction + text}]

    def _serialize_record_snapshot(self, record, depth, max_depth, visited):
        """Serializa registro con expansión m2o/m2m hasta max_depth."""
        if not record or not record.exists():
            return None
        key = (record._name, record.id)
        if key in visited:
            return {
                "id": record.id,
                "display_name": record.display_name,
                "_model": record._name,
                "_note": "referencia circular omitida",
            }
        visited.add(key)
        try:
            out = {
                "id": record.id,
                "display_name": record.display_name,
                "_model": record._name,
            }
            if depth >= max_depth:
                return out

            atts = self.env["ir.attachment"].search(
                [("res_model", "=", record._name), ("res_id", "=", record.id)],
                limit=40,
            )
            if atts:
                out["_adjuntos"] = [
                    {
                        "nombre": a.name,
                        "mimetype": a.mimetype,
                        "tamaño_bytes": a.file_size or 0,
                    }
                    for a in atts
                ]

            for fname, field in record._fields.items():
                if field.automatic:
                    continue
                if fname in ("id", "display_name"):
                    continue
                if field.type in ("one2many", "many2many"):
                    if fname in _SKIP_X2M_NAMES:
                        continue
                    if field.comodel_name == "mail.message":
                        continue
                    try:
                        lines = record[fname]
                    except Exception:
                        out[fname] = _("[sin acceso]")
                        continue
                    limit = 40
                    slice_lines = lines[:limit]
                    out[fname] = []
                    for line in slice_lines:
                        out[fname].append(
                            self._serialize_record_snapshot(
                                line, depth + 1, max_depth, visited
                            )
                        )
                    if len(lines) > limit:
                        out[fname].append(
                            {
                                "_nota": _("%s registros omitidos por límite")
                                % (len(lines) - limit)
                            }
                        )
                elif field.type == "many2one":
                    try:
                        rel = record[fname]
                    except Exception:
                        out[fname] = _("[sin acceso]")
                        continue
                    if rel:
                        out[fname] = self._serialize_record_snapshot(
                            rel, depth + 1, max_depth, visited
                        )
                    else:
                        out[fname] = False
                elif field.type == "binary":
                    try:
                        val = record[fname]
                    except Exception:
                        out[fname] = _("[sin acceso]")
                        continue
                    if val:
                        ln = len(val) if isinstance(val, (bytes, str)) else 0
                        out[fname] = _("[binario, %s bytes]") % ln
                    else:
                        out[fname] = False
                else:
                    try:
                        val = record[fname]
                        if isinstance(val, BaseModel):
                            if len(val) == 1:
                                out[fname] = val.display_name
                            elif len(val) > 1:
                                out[fname] = val.mapped("display_name")
                            else:
                                out[fname] = False
                        else:
                            out[fname] = val
                    except Exception as err:
                        out[fname] = _("[no accesible: %s]") % err

            return out
        finally:
            visited.discard(key)
