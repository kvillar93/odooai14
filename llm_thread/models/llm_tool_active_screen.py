import logging
from typing import Any

from lxml import etree

from odoo import _, api, models
from odoo.tools import html2plaintext

_logger = logging.getLogger(__name__)

_SKIP_FIELDS = frozenset(
    {
        "message_ids",
        "message_follower_ids",
        "activity_ids",
        "website_message_ids",
        "rating_ids",
        "message_main_attachment_id",
    }
)
_MAX_X2M_ITEMS = 15
_MAX_TEXT_CHARS = 2000


class LLMToolActiveScreen(models.Model):
    _inherit = "llm.tool"

    @api.model
    def _get_available_implementations(self):
        implementations = super()._get_available_implementations()
        return implementations + [("odoo_active_screen", "Odoo Active Screen")]

    def odoo_active_screen_execute(
        self, include_data: bool = True, limit: int = 20
    ) -> dict[str, Any]:
        """Lee la pantalla de Odoo que el usuario tiene abierta ahora mismo.

        Parameters:
            include_data: Incluir los datos del registro abierto o de los registros listados
            limit: Máximo de registros a devolver en vistas de lista/kanban
        """
        thread = self._active_screen_thread()
        screen = (thread.screen_context_json if thread else None) or {}
        if not screen:
            return {
                "error": _(
                    "No hay información de la pantalla activa: el usuario no está "
                    "usando el chat flotante sobre una vista de Odoo."
                )
            }
        out = {
            "titulo": screen.get("title"),
            "accion": screen.get("action_name"),
            "modelo": screen.get("model"),
            "tipo_vista": screen.get("view_type"),
            "registro_id": screen.get("res_id"),
            "ruta": screen.get("breadcrumbs"),
            "url": screen.get("url"),
            "texto_visible": screen.get("visible_text"),
        }
        model_name = screen.get("model")
        if not include_data or not model_name or model_name not in self.env:
            return out
        Model = self.env[model_name]
        limit = max(1, min(int(limit or 20), 200))
        try:
            res_id = int(screen.get("res_id") or 0)
            if res_id:
                record = Model.browse(res_id).exists()
                if record:
                    names = self._active_screen_view_fields(Model, "form")
                    out["registro"] = self._active_screen_record_values(record, names)
            elif screen.get("domain") is not None:
                domain = screen.get("domain") or []
                names = self._active_screen_view_fields(
                    Model, screen.get("view_type") or "tree"
                )
                out["total_registros"] = Model.search_count(domain)
                records = Model.search(domain, limit=limit)
                out["registros"] = [
                    self._active_screen_record_values(rec, names[:12]) for rec in records
                ]
        except Exception as err:
            _logger.info("odoo_active_screen: no se pudieron leer datos: %s", err)
            out["aviso"] = _("No se pudieron leer los datos del modelo: %s") % err
        return out

    def _active_screen_thread(self):
        message = self.env.context.get("message")
        if not message or message.model != "llm.thread":
            return None
        return self.env["llm.thread"].browse(message.res_id).exists()

    @api.model
    def _active_screen_view_fields(self, Model, view_type):
        """Nombres de campo visibles en la vista por defecto del tipo indicado."""
        view_type = {"list": "tree"}.get(view_type, view_type)
        if view_type not in ("form", "tree", "kanban"):
            view_type = "tree"
        try:
            if hasattr(Model, "get_view"):
                arch = Model.get_view(view_type=view_type)["arch"]
            else:
                arch = Model.fields_view_get(view_type=view_type)["arch"]
            root = etree.fromstring(arch.encode() if isinstance(arch, str) else arch)
            names = []
            for node in root.xpath("//field[not(ancestor::field)]"):
                name = node.get("name")
                if (
                    name in Model._fields
                    and name not in names
                    and node.get("invisible") not in ("1", "True")
                ):
                    names.append(name)
            if names:
                return names
        except Exception as err:
            _logger.debug("odoo_active_screen: vista %s no legible: %s", view_type, err)
        return [
            name
            for name, field in Model._fields.items()
            if field.store and not field.automatic
        ][:30]

    @api.model
    def _active_screen_record_values(self, record, field_names):
        values = {"id": record.id, "display_name": record.display_name}
        for name in field_names:
            field = record._fields.get(name)
            if not field or name in _SKIP_FIELDS or field.type == "binary":
                continue
            try:
                value = record[name]
            except Exception:
                continue
            if field.type == "many2one":
                values[name] = value.display_name if value else False
            elif field.type in ("one2many", "many2many"):
                values[name] = {
                    "total": len(value),
                    "primeros": value[:_MAX_X2M_ITEMS].mapped("display_name"),
                }
            elif field.type == "html":
                values[name] = html2plaintext(value or "")[:_MAX_TEXT_CHARS]
            elif field.type in ("text", "char") and value:
                values[name] = str(value)[:_MAX_TEXT_CHARS]
            elif field.type in ("date", "datetime") and value:
                values[name] = str(value)
            elif field.type == "selection" and value:
                values[name] = dict(field._description_selection(self.env)).get(
                    value, value
                )
            else:
                values[name] = value
        return values
