import json
import logging
import re
from typing import Any, Dict, List, Optional

from odoo import _, api, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class LLMToolRecordCreator(models.Model):
    _inherit = "llm.tool"

    @api.model
    def _get_available_implementations(self):
        implementations = super()._get_available_implementations()
        return implementations + [("odoo_record_creator", "Odoo Record Creator")]

    def get_input_schema(self, method="execute"):
        """Refuerza el esquema JSON: con Any, Pydantic no pone type:object y los LLMs envían listas."""
        schema = super().get_input_schema(method=method)
        if self.implementation != "odoo_record_creator":
            return schema
        props = schema.setdefault("properties", {})
        if "write_values" in props:
            props["write_values"]["description"] = (
                "Obligatorio si no usa «records»: un ÚNICO objeto JSON (mapa), clave=nombre técnico "
                "del campo Odoo, valor=dato a guardar. El nombre «write_values» evita confundirlo con "
                "«fields» del retriever (lista de columnas). Prohibido enviar un array de nombres de campos. "
                "Ejemplo línea de compra: "
                '{"order_id": 123, "product_id": 45, "product_qty": 2, "price_unit": 10.5, "name": "Polo"}'
            )
        if "records" in props:
            props["records"]["description"] = (
                "Lista de objetos (cada uno como «write_values») para crear varios registros en una llamada. "
                "No mezclar con «write_values»."
            )
        if "model" in props:
            props["model"]["description"] = (
                "Nombre técnico del modelo Odoo, p. ej. purchase.order.line, res.partner, sale.order."
            )
        return schema

    def execute(self, parameters):
        """Normaliza argumentos (p. ej. Gemini envía 'fields' como lista) antes de Pydantic."""
        self.ensure_one()
        if self.implementation == "odoo_record_creator":
            raw = dict(parameters or {})
            try:
                _logger.info(
                    "odoo_record_creator: argumentos crudos antes de normalizar: %s",
                    json.dumps(raw, default=str, ensure_ascii=False),
                )
            except (TypeError, ValueError):
                _logger.info(
                    "odoo_record_creator: argumentos crudos (no JSON): %s", raw
                )
            parameters = self._normalize_odoo_record_creator_execute_params(raw)
        return super().execute(parameters)

    def _normalize_odoo_record_creator_execute_params(self, params):
        """Convierte formas inválidas pero frecuentes de LLMs en dict/listas esperadas."""
        # Parámetro oficial: write_values. Alias legacy: field_values, fields (retriever).
        if "write_values" not in params:
            if "field_values" in params:
                params["write_values"] = params.pop("field_values")
            elif "fields" in params:
                params["write_values"] = params.pop("fields")
        if "write_values" in params:
            params["write_values"] = self._normalize_record_creator_write_values_value(
                params.get("write_values")
            )
        if "records" in params and params["records"] is not None:
            params["records"] = self._normalize_record_creator_records_value(
                params.get("records")
            )
        return params

    def _normalize_record_creator_write_values_value(self, write_values):
        if write_values is None:
            return None
        if isinstance(write_values, dict):
            return write_values
        if isinstance(write_values, list):
            if not write_values:
                return {}
            if all(isinstance(x, dict) for x in write_values):
                merged = {}
                for d in write_values:
                    merged.update(d)
                return merged
            # No interpretar listas planas como [k1,v1,k2,v2]: una lista de nombres
            # de campo con longitud par se confunde con pares y produce create() inválido
            # (p. ej. product_qty → "order_id" y fallos al convertir a float).
            if all(isinstance(x, str) for x in write_values):
                raise UserError(
                    _(
                        "El modelo devolvió «write_values» (o alias «field_values»/«fields») como lista "
                        "de nombres (%(keys)s) en lugar de un objeto JSON con valores por campo. "
                        "Debe ser un objeto, por ejemplo: "
                        '{"name": "Nombre", "vat": "123"}. '
                        "Las listas de nombres de columnas son solo en odoo_record_retriever («fields»)."
                    )
                    % {
                        "keys": ", ".join(write_values[:8])
                        + ("…" if len(write_values) > 8 else "")
                    }
                )
        raise UserError(
            _(
                "El parámetro «write_values» debe ser un objeto JSON (diccionario) con los "
                "valores del registro, no %(typ)s."
            )
            % {"typ": type(write_values).__name__}
        )

    def _normalize_record_creator_records_value(self, records):
        if records is None:
            return None
        if isinstance(records, list):
            if not records:
                return []
            if all(isinstance(x, dict) for x in records):
                return records
        if isinstance(records, dict):
            return [records]
        raise UserError(
            _(
                "El parámetro «records» debe ser una lista de objetos JSON (diccionarios), "
                "no %(typ)s."
            )
            % {"typ": type(records).__name__}
        )

    # ------------------------------------------------------------------
    # Normalización many2many y reintento ante campos inválidos
    # ------------------------------------------------------------------

    def _normalize_m2m_command(self, cmd):
        """Convierte una lista/tupla con un comando ORM many2many al tuple correcto de Odoo."""
        if not cmd and cmd != 0:
            return None
        # Normalizar el tipo de comando (False → 0, bool → int)
        raw_type = cmd[0] if cmd else 0
        if raw_type is False or raw_type is None:
            raw_type = 0
        cmd_type = int(raw_type)

        if cmd_type == 6:
            # (6, 0, ids) — reemplazar todos; el LLM puede enviar el tercer elem como int o lista
            ids_raw = cmd[2] if len(cmd) > 2 else []
            if isinstance(ids_raw, (int, float)):
                ids_raw = [int(ids_raw)]
            elif isinstance(ids_raw, (list, tuple)):
                ids_raw = [int(i) for i in ids_raw if isinstance(i, (int, float))]
            else:
                ids_raw = []
            return (6, 0, ids_raw)
        elif cmd_type == 4:
            return (4, int(cmd[1]))
        elif cmd_type == 3:
            return (3, int(cmd[1]))
        elif cmd_type == 2:
            return (2, int(cmd[1]))
        elif cmd_type == 5:
            return (5,)
        elif cmd_type == 0:
            vals = cmd[2] if len(cmd) > 2 else {}
            return (0, 0, vals if isinstance(vals, dict) else {})
        elif cmd_type == 1:
            vals = cmd[2] if len(cmd) > 2 else {}
            return (1, int(cmd[1]), vals if isinstance(vals, dict) else {})
        return tuple(cmd)

    def _normalize_field_value_m2m(self, value):
        """Normaliza el valor de un campo many2many enviado por un LLM.

        Casos soportados:
        - [[6, false, [5, 6]]] → [(6, 0, [5, 6])]   (comando set, false como 0)
        - [[6, 0, 6]]          → [(6, 0, [6])]        (ID suelto como int)
        - [[4, 6]]             → [(4, 6)]              (link)
        - [5, 6, 7]            → [(6, 0, [5, 6, 7])]  (lista de IDs sin comando)
        """
        if not isinstance(value, list) or not value:
            return value

        # Detectar si es lista de listas/tuplas (comandos ORM)
        if all(isinstance(item, (list, tuple)) for item in value):
            normalized = []
            for cmd in value:
                result = self._normalize_m2m_command(cmd)
                if result is not None:
                    normalized.append(result)
            return normalized

        # Detectar si es lista de enteros: convertir a [(6, 0, ids)]
        if all(isinstance(item, (int, float)) for item in value):
            return [(6, 0, [int(i) for i in value])]

        return value

    def _normalize_write_values_m2m(self, model_name, values):
        """Aplica normalización many2many a todos los campos m2m del dict values."""
        if not values or not isinstance(values, dict):
            return values
        try:
            model_fields = self.env[model_name]._fields
        except Exception:
            return values

        normalized = {}
        for fname, fval in values.items():
            field = model_fields.get(fname)
            if field and field.type in ("many2many", "one2many") and isinstance(fval, list):
                normalized[fname] = self._normalize_field_value_m2m(fval)
            else:
                normalized[fname] = fval
        return normalized

    def _strip_invalid_field(self, values, error_msg):
        """Extrae el campo inválido del mensaje de error y lo elimina del dict.

        Devuelve (campo_eliminado | None, nuevo_dict).
        Reconoce patrones como 'Invalid field \\'xxx\\' on model'.
        """
        if not values:
            return None, values
        match = re.search(r"Invalid field ['\"]?(\w+)['\"]?", str(error_msg))
        if not match:
            return None, values
        bad_field = match.group(1)
        if bad_field in values:
            new_vals = {k: v for k, v in values.items() if k != bad_field}
            return bad_field, new_vals
        return None, values

    def _create_with_retry(self, model_obj, model_name, values):
        """Crea un registro aplicando reintento automático ante campos inválidos.

        Normaliza comandos many2many antes del primer intento.
        Si la creación falla por 'Invalid field', elimina ese campo y reintenta (máx 3 veces).
        Devuelve el recordset creado o relanza el último error.
        """
        values = self._normalize_write_values_m2m(model_name, values)
        last_err = None
        removed = []

        for _attempt in range(4):  # original + 3 reintentos
            try:
                with self.env.cr.savepoint():
                    return model_obj.create(values)
            except Exception as err:
                err_str = str(err)
                bad_field, values = self._strip_invalid_field(values, err_str)
                if bad_field:
                    removed.append(bad_field)
                    _logger.warning(
                        "odoo_record_creator: campo inválido '%s' eliminado; reintentando en %s.",
                        bad_field,
                        model_name,
                    )
                    last_err = err
                    continue
                # Error no relacionado con campo inválido → relanzar
                raise

        # Si se agotaron los reintentos con campos inválidos
        raise UserError(
            _(
                "No se pudo crear el registro en «%(model)s» después de eliminar los campos "
                "inválidos %(fields)s. Último error: %(err)s"
            )
            % {
                "model": model_name,
                "fields": str(removed),
                "err": str(last_err),
            }
        )

    def odoo_record_creator_execute(
        self,
        model: str,
        write_values: Optional[Dict[str, Any]] = None,
        records: Optional[List[Dict[str, Any]]] = None,
    ) -> dict[str, Any]:
        """
        Create one or multiple new records in the specified Odoo model

        Parameters:
            model: Nombre técnico del modelo Odoo (p. ej. purchase.order.line).
            write_values: Objeto JSON {campo: valor}; nunca una lista de nombres de campo.
                Nombre distinto a «fields» del retriever (lista de columnas); Gemini confundía «field_values».
            records: Lista de objetos {campo: valor} para varios registros (alternativa a write_values).
        """
        write_values = self._normalize_record_creator_write_values_value(write_values)
        records = (
            self._normalize_record_creator_records_value(records)
            if records is not None
            else None
        )

        if write_values is None and records is None:
            raise ValueError("Either 'write_values' or 'records' must be provided")

        if write_values is not None and records is not None:
            raise ValueError("Only one of 'write_values' or 'records' should be provided")

        _logger.info(
            "Executing Odoo Record Creator with: model=%s, write_values=%s, records=%s",
            model, write_values, records,
        )

        model_obj = self.env[model]

        if write_values is not None:
            new_record = self._create_with_retry(model_obj, model, write_values)
            result = {
                "id": new_record.id,
                "display_name": new_record.display_name,
                "message": f"Record created successfully in {model}",
            }
        else:
            # Para múltiples registros, reintentamos cada uno individualmente
            created = []
            errors = []
            for idx, rec_vals in enumerate(records):
                try:
                    new_rec = self._create_with_retry(model_obj, model, rec_vals)
                    created.append({"id": new_rec.id, "display_name": new_rec.display_name})
                except Exception as err:
                    errors.append({"index": idx, "values": rec_vals, "error": str(err)})

            result = {
                "records": created,
                "count": len(created),
                "message": f"{len(created)} records created successfully in {model}",
            }
            if errors:
                result["errors"] = errors
                result["message"] += f" ({len(errors)} failed)"

        return result
