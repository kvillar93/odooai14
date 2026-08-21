# -*- coding: utf-8 -*-
import functools
import json
import logging
import uuid

from odoo import _, api, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

# Dummy thought_signature para tool calls reconstruidos desde la base de datos.
# Documentado en https://ai.google.dev/gemini-api/docs/gemini-3#thought_signatures
# Esta cadena específica activa el bypass de validación estricta al migrar historial.
# Documentación Google: debe ser exactamente esta cadena (guiones bajos, sin espacios).
# Un typo aquí provoca 400 INVALID_ARGUMENT «Corrupted thought signature».
_GEMINI_DUMMY_THOUGHT_SIGNATURE = b"context_engineering_is_the_way_to_go"

# Keywords JSON Schema que la API Gemini (Developer) suele rechazar con 400
# INVALID_ARGUMENT / "Unknown name …". Ver OpenAPI subset de Schema.
# No incluir nombres de parámetros de usuario: solo se eliminan como keywords.
_GEMINI_UNSUPPORTED_SCHEMA_KEYS = frozenset(
    {
        "$anchor",
        "$comment",
        "$defs",
        "$dynamicAnchor",
        "$dynamicRef",
        "$id",
        "$ref",
        "$schema",
        "$vocabulary",
        "additionalProperties",
        "const",
        "contentEncoding",
        "contentMediaType",
        "contentSchema",
        "definitions",
        "dependencies",
        "dependentRequired",
        "dependentSchemas",
        "else",
        "examples",
        "if",
        "nullable",
        "patternProperties",
        "propertyNames",
        "readOnly",
        "then",
        "unevaluatedItems",
        "unevaluatedProperties",
        "writeOnly",
    }
)

# Mapas cuyas claves son nombres definidos por el usuario (parámetros), no keywords.
_GEMINI_USER_NAMED_KEY_MAPS = frozenset(
    {
        "properties",
        "$defs",
        "definitions",
        "patternProperties",
        "dependentSchemas",
    }
)


@functools.lru_cache(maxsize=1)
def _gemini_tool_config_extended_class():
    """Amplía ToolConfig del SDK con include_server_side_tool_invocations.

    La API de Gemini lo exige al combinar herramientas integradas (p. ej. Google Search)
    con function calling; versiones como google-genai 1.47 no declaran el campo en
    ToolConfig, pero una subclase Pydantic se serializa bien en el JSON de la petición.
    """
    from typing import Optional

    from pydantic import Field
    from google.genai import types as genai_types

    class GeminiToolConfigExtended(genai_types.ToolConfig):
        include_server_side_tool_invocations: Optional[bool] = Field(
            default=None,
            description=(
                "Requerido por la API al combinar herramientas de servidor con "
                "function calling."
            ),
        )

    return GeminiToolConfigExtended


class LLMProvider(models.Model):
    _inherit = "llm.provider"

    @api.model
    def _get_available_services(self):
        return super()._get_available_services() + [("gemini", "Google Gemini")]

    # ------------------------------------------------------------------
    # Cliente SDK
    # ------------------------------------------------------------------

    def gemini_get_client(self):
        """Devuelve un cliente google.genai (nuevo SDK 1.x)."""
        try:
            from google import genai as genai_module
        except ImportError as e:
            raise UserError(
                _("Instale google-genai: pip install google-genai. Error: %s") % e
            ) from e
        return genai_module.Client(api_key=self.api_key)

    # ------------------------------------------------------------------
    # Utilidades de modelo
    # ------------------------------------------------------------------

    def _gemini_short_name(self, resource_name):
        """Convierte 'models/gemini-1.5-flash' en 'gemini-1.5-flash'."""
        if not resource_name:
            return ""
        s = str(resource_name).strip()
        if s.startswith("models/"):
            return s.split("/", 1)[1]
        return s

    def gemini_models(self, model_id=None):
        """Lista modelos disponibles en Google AI (Gemini)."""
        self.ensure_one()
        if not self.api_key:
            raise UserError(_("Configure la API key del proveedor Gemini."))

        client = self.gemini_get_client()
        want = None
        if model_id:
            want = self._gemini_short_name(model_id)
            if not want and model_id:
                want = str(model_id).strip()

        found_one = False
        try:
            for m in client.models.list():
                short = self._gemini_short_name(m.name)
                if want:
                    if short != want and m.name != model_id and m.name != f"models/{want}":
                        continue
                    found_one = True
                    yield self._gemini_parse_model(m, short)
                    break
                methods = self._gemini_supported_methods(m)
                if not any(x in methods for x in ("generateContent", "embedContent")):
                    continue
                yield self._gemini_parse_model(m, short)
        except Exception as err:
            _logger.warning("Gemini: error al listar modelos: %s", err)

        if want and not found_one:
            _logger.warning("Gemini: no se encontró '%s' en list_models.", model_id)

    def _gemini_supported_methods(self, m):
        """Lista métodos soportados (google-genai usa supported_actions; el API REST: supportedGenerationMethods)."""
        raw = (
            getattr(m, "supported_actions", None)
            or getattr(m, "supported_generation_methods", None)
            or []
        )
        return [str(x) for x in raw] if raw else []

    def _gemini_parse_model(self, m, short_name=None):
        """Convierte un objeto Model de la API al formato esperado por llm.fetch.models."""
        if short_name is None:
            short_name = self._gemini_short_name(m.name)
        methods = self._gemini_supported_methods(m)
        low = short_name.lower()

        capabilities = []
        if "embedContent" in methods and "generateContent" not in methods:
            capabilities = ["embedding"]
        elif "generateContent" in methods:
            capabilities = ["chat"]
            if "embedding" not in low and not low.startswith("text-embedding"):
                capabilities.append("multimodal")
        elif "embedContent" in methods:
            capabilities.append("embedding")
        else:
            capabilities = ["chat"]

        return {
            "name": short_name,
            "details": {
                "id": short_name,
                "capabilities": capabilities,
                "display_name": getattr(m, "display_name", None) or short_name,
                "description": getattr(m, "description", None) or "",
                "supported_generation_methods": methods,
                "resource_name": m.name,
            },
        }

    # ------------------------------------------------------------------
    # Formateo de herramientas (tools)
    # ------------------------------------------------------------------

    def _gemini_sanitize_schema(self, schema):
        """Limpia un JSON Schema para FunctionDeclaration de Gemini.

        Pydantic/OpenAI generan ``additionalProperties``, ``anyOf`` con
        ``{type: null}``, ``$defs``, etc. La API Gemini Developer suele
        responder 400 INVALID_ARGUMENT (a veces solo «Request contains an
        invalid argument») si esos keywords llegan en
        ``parameters_json_schema``.

        - Elimina keywords no soportados (p. ej. additionalProperties).
        - Aplana Optional típico: anyOf[X, null] → X + nullable=True.
        - No borra nombres de parámetros que coincidan con keywords
          (solo limpia dentro de ``properties`` / mapas de usuario).
        """
        if isinstance(schema, list):
            return [self._gemini_sanitize_schema(item) for item in schema]
        if not isinstance(schema, dict):
            return schema

        # Optional[T] de Pydantic: {"anyOf": [T, {"type": "null"}], "default": null}
        any_of = schema.get("anyOf")
        if isinstance(any_of, list) and len(any_of) >= 2:
            non_null = []
            has_null = False
            for opt in any_of:
                if isinstance(opt, dict) and opt.get("type") == "null" and len(opt) <= 2:
                    # {"type": "null"} o {"type": "null", "title": "..."}
                    has_null = True
                else:
                    non_null.append(opt)
            if has_null and len(non_null) == 1 and isinstance(non_null[0], dict):
                merged = dict(non_null[0])
                for keep in ("description", "title"):
                    if keep in schema and keep not in merged:
                        merged[keep] = schema[keep]
                # No usar ``nullable``: algunos modelos/aliases lo rechazan en
                # parameters_json_schema. El parámetro queda opcional al no
                # estar en ``required``.
                return self._gemini_sanitize_schema(merged)

        out = {}
        for key, value in schema.items():
            if key in _GEMINI_USER_NAMED_KEY_MAPS and isinstance(value, dict):
                out[key] = {
                    child_key: self._gemini_sanitize_schema(child_val)
                    for child_key, child_val in value.items()
                }
                continue
            if key in _GEMINI_UNSUPPORTED_SCHEMA_KEYS:
                continue
            if key == "default" and value is None:
                # default: null suele sobrar tras aplanar Optional
                continue
            out[key] = self._gemini_sanitize_schema(value)

        # Si quedó type:null suelto, descartarlo (parámetro opcional sin tipo null).
        if out.get("type") == "null" and len(out) <= 2:
            return {"type": "string", "description": out.get("description") or ""}

        # Gemini Developer a veces rechaza ``nullable`` en function params.
        out.pop("nullable", None)
        return out

    def gemini_format_tools(self, tools):
        """Formatea herramientas Odoo para el nuevo SDK (usa parameters_json_schema)."""
        from google.genai import types as genai_types

        declarations = []
        for tool in tools:
            schema = tool.get_input_schema() or {}
            if not isinstance(schema, dict):
                schema = {"type": "object", "properties": {}}

            # Sanitizar: Gemini no acepta el JSON Schema completo de Pydantic/OpenAI
            # (additionalProperties, anyOf+null, $defs, …) → 400 INVALID_ARGUMENT.
            schema = self._gemini_sanitize_schema(schema)
            if not isinstance(schema, dict) or schema.get("type") not in (
                None,
                "object",
                "OBJECT",
            ):
                # FunctionDeclaration exige object en la raíz.
                schema = {
                    "type": "object",
                    "properties": schema.get("properties", {})
                    if isinstance(schema, dict)
                    else {},
                }
            elif "type" not in schema:
                schema = dict(schema)
                schema["type"] = "object"

            decl = genai_types.FunctionDeclaration(
                name=tool.name,
                description=tool.description or "",
                parameters_json_schema=schema,
            )
            declarations.append(decl)

            # Log para comparar schema de write_values con OpenAI
            if tool.name == "odoo_record_creator":
                try:
                    wv = (schema.get("properties") or {}).get("write_values")
                    _logger.info(
                        "Gemini: herramienta odoo_record_creator; write_values en schema=%s",
                        json.dumps(wv, ensure_ascii=False) if wv is not None else None,
                    )
                except (TypeError, AttributeError):
                    pass

        return declarations

    # ------------------------------------------------------------------
    # Conversión de mensajes OpenAI → Gemini Contents
    # ------------------------------------------------------------------

    def gemini_format_messages(self, messages, system_prompt=None):
        """Lista de mensajes en formato OpenAI-like para compatibilidad interna."""
        formatted = []
        if system_prompt:
            formatted.append({"role": "system", "content": system_prompt})
        for message in messages:
            if isinstance(message, dict) and message.get("role"):
                formatted.append(dict(message))
                continue
            fm = self._dispatch("format_message", record=message)
            if fm:
                formatted.append(fm)
        return formatted

    def _gemini_enrich_tool_message_from_record(self, formatted, record):
        """Añade «name» y «tool_call_id» al mensaje tipo tool desde body_json.

        El formato OpenAI no incluye ``name``; Gemini exige el nombre de la
        función en ``FunctionResponse`` y el mismo ``id`` que el ``FunctionCall``.
        """
        if not formatted or formatted.get("role") != "tool":
            return
        if not hasattr(record, "body_json"):
            return
        td = record.body_json or {}
        name = td.get("tool_name")
        if not name:
            fn = (td.get("tool_call") or {}).get("function") or {}
            name = fn.get("name")
        if name:
            formatted["name"] = name
        tcid = td.get("tool_call_id") or (td.get("tool_call") or {}).get("id")
        if tcid:
            formatted["tool_call_id"] = tcid

    def _gemini_build_openai_style_message_list(self, prepend_messages, messages):
        """Crea la lista de mensajes OpenAI-like con gemini_content_json enriquecido."""
        out = []
        for m in prepend_messages or []:
            if isinstance(m, dict) and m.get("role"):
                out.append(dict(m))
                continue
            fm = self._dispatch("format_message", record=m)
            if fm:
                self._gemini_enrich_tool_message_from_record(fm, m)
                if fm.get("role") == "assistant" and hasattr(m, "body_json"):
                    bj = m.body_json or {}
                    # Soporta nuevo campo gemini_content_json y legado gemini_model_content_b64
                    snap = bj.get("gemini_content_json") or bj.get("gemini_model_content_b64")
                    if snap:
                        fm["gemini_content_json"] = snap
                out.append(fm)
        for msg in messages or []:
            if isinstance(msg, dict) and msg.get("role"):
                out.append(dict(msg))
                continue
            fm = self._dispatch("format_message", record=msg)
            if fm:
                self._gemini_enrich_tool_message_from_record(fm, msg)
                if fm.get("role") == "assistant" and hasattr(msg, "body_json"):
                    bj = msg.body_json or {}
                    snap = bj.get("gemini_content_json") or bj.get("gemini_model_content_b64")
                    if snap:
                        fm["gemini_content_json"] = snap
                out.append(fm)
        return out

    def _gemini_user_content_to_parts(self, content):
        """Convierte content de un mensaje user a partes Gemini (texto o multimodal)."""
        import base64
        from google.genai import types as genai_types

        if content is None:
            return [genai_types.Part(text="")]
        if isinstance(content, str):
            return [genai_types.Part(text=content)]
        if isinstance(content, list):
            parts = []
            for p in content:
                if not isinstance(p, dict):
                    continue
                if p.get("type") == "text":
                    parts.append(genai_types.Part(text=p.get("text") or ""))
                elif p.get("type") == "image_url":
                    url = (p.get("image_url") or {}).get("url") or ""
                    if url.startswith("data:"):
                        try:
                            header, b64 = url.split(",", 1)
                            mime = header.split(";")[0].split(":", 1)[1]
                            raw = base64.b64decode(b64)
                            parts.append(
                                genai_types.Part(
                                    inline_data=genai_types.Blob(
                                        mime_type=mime, data=raw
                                    )
                                )
                            )
                        except (ValueError, IndexError, TypeError) as err:
                            _logger.debug("Gemini: no se pudo decodificar imagen: %s", err)
                            parts.append(genai_types.Part(text="[imagen no incluida]"))
                    else:
                        parts.append(
                            genai_types.Part(
                                text="[imagen remota omitida; use data URI base64]"
                            )
                        )
            return parts if parts else [genai_types.Part(text="")]
        return [genai_types.Part(text=str(content))]

    def _gemini_build_contents(self, openai_messages):
        """Convierte lista OpenAI-like → (contents: list[types.Content], system_instruction: str|None).

        Para mensajes assistant con tool_calls reconstruidos desde BD, inyecta el dummy
        thought_signature requerido por Gemini 3 Flash para funciones calling estricto.
        Si hay gemini_content_json guardado, lo restaura directamente preservando thought_signature real.
        """
        from google.genai import types as genai_types

        system_chunks = []
        contents = []

        for msg in openai_messages or []:
            role = msg.get("role")

            if role == "system":
                c = msg.get("content")
                if isinstance(c, str):
                    system_chunks.append(c)
                elif isinstance(c, list):
                    for p in c:
                        if isinstance(p, dict) and p.get("type") == "text":
                            system_chunks.append(p.get("text") or "")
                continue

            elif role == "user":
                parts = self._gemini_user_content_to_parts(msg.get("content"))
                contents.append(genai_types.Content(role="user", parts=parts))

            elif role == "assistant":
                # Intentar restaurar desde contenido JSON guardado (nuevo SDK - preserva thought_signature real)
                stored_json = msg.get("gemini_content_json")
                if stored_json:
                    try:
                        restored = genai_types.Content.model_validate_json(stored_json)
                        contents.append(restored)
                        continue
                    except Exception as err:
                        _logger.debug(
                            "Gemini: no se pudo restaurar content JSON (se usará dummy sig): %s", err
                        )

                # Construir manualmente con dummy thought_signature para function_calls históricos
                parts = []
                content_text = msg.get("content")
                if content_text and isinstance(content_text, str) and content_text.strip():
                    parts.append(genai_types.Part(text=content_text))

                for tc in msg.get("tool_calls") or []:
                    fn = tc.get("function") or {}
                    name = fn.get("name") or ""
                    args_raw = fn.get("arguments", "{}")
                    if isinstance(args_raw, str):
                        try:
                            args_dict = json.loads(args_raw) if args_raw.strip() else {}
                        except json.JSONDecodeError:
                            args_dict = {}
                    else:
                        args_dict = args_raw if isinstance(args_raw, dict) else {}

                    call_id = tc.get("id") or str(uuid.uuid4())
                    # Dummy thought_signature es necesario para Gemini 3 en function calling
                    parts.append(
                        genai_types.Part(
                            function_call=genai_types.FunctionCall(
                                name=name,
                                args=args_dict,
                                id=call_id,
                            ),
                            thought_signature=_GEMINI_DUMMY_THOUGHT_SIGNATURE,
                        )
                    )

                if not parts:
                    parts.append(genai_types.Part(text=""))

                contents.append(genai_types.Content(role="model", parts=parts))

            elif role == "tool":
                name = msg.get("name") or "unknown_tool"
                tool_call_id = (msg.get("tool_call_id") or "").strip() or None
                raw = msg.get("content")
                if isinstance(raw, str):
                    try:
                        resp_obj = json.loads(raw) if raw.strip() else {}
                    except json.JSONDecodeError:
                        resp_obj = {"result": raw}
                else:
                    resp_obj = raw if raw is not None else {}
                if not isinstance(resp_obj, dict):
                    resp_obj = {"result": resp_obj}

                fr_kwargs = {
                    "name": name,
                    "response": resp_obj,
                }
                # Gemini 3+ exige el mismo id que el function_call previo.
                if tool_call_id:
                    fr_kwargs["id"] = tool_call_id

                contents.append(
                    genai_types.Content(
                        role="user",
                        parts=[
                            genai_types.Part(
                                function_response=genai_types.FunctionResponse(
                                    **fr_kwargs
                                )
                            )
                        ],
                    )
                )

        system_instruction = "\n\n".join(system_chunks) if system_chunks else None
        if not contents:
            contents = [
                genai_types.Content(role="user", parts=[genai_types.Part(text="")])
            ]
        else:
            contents = self._gemini_normalize_model_turn_parts_order(
                contents, genai_types
            )
            contents = self._gemini_merge_consecutive_function_response_users(
                contents, genai_types
            )
            contents = self._gemini_strip_invalid_function_calls(contents, genai_types)
            contents = self._gemini_strip_orphan_function_responses(contents)
            contents = self._gemini_fix_consecutive_model_turns(contents, genai_types)
            contents = self._gemini_ensure_contents_end_with_user(contents, genai_types)
        if not contents:
            contents = [
                genai_types.Content(role="user", parts=[genai_types.Part(text="")])
            ]
        return contents, system_instruction

    def _gemini_role_name(self, content):
        """Normaliza role de types.Content (str o enum) a 'user' | 'model' | otro."""
        r = getattr(content, "role", None)
        if r is None:
            return ""
        val = getattr(r, "value", None)
        if isinstance(val, str):
            return val.lower()
        name = getattr(r, "name", None)
        if isinstance(name, str):
            return name.lower()
        s = str(r).lower()
        if "model" in s and "user" not in s:
            return "model"
        if "user" in s:
            return "user"
        return s

    def _gemini_content_has_function_call(self, content):
        """True si alguna parte del Content es function_call."""
        for p in content.parts or []:
            if getattr(p, "function_call", None):
                return True
        return False

    def _gemini_function_call_names(self, content):
        """Nombres de cada function_call en orden (puede haber duplicados)."""
        names = []
        for p in content.parts or []:
            fc = getattr(p, "function_call", None)
            if fc:
                names.append(getattr(fc, "name", "") or "")
        return names

    def _gemini_function_response_names(self, content):
        """Nombres de cada function_response en orden."""
        names = []
        for p in content.parts or []:
            fr = getattr(p, "function_response", None)
            if fr:
                names.append(getattr(fr, "name", "") or "")
        return names

    def _gemini_user_is_only_function_responses(self, content):
        """True si cada parte del turno user es function_response (mensajes tool)."""
        if not content.parts:
            return False
        for p in content.parts:
            if not getattr(p, "function_response", None):
                return False
        return True

    def _gemini_function_call_ids(self, content):
        """IDs de cada function_call (puede haber vacíos)."""
        ids = []
        for p in content.parts or []:
            fc = getattr(p, "function_call", None)
            if fc:
                ids.append((getattr(fc, "id", None) or "").strip())
        return ids

    def _gemini_function_response_ids(self, content):
        """IDs de cada function_response."""
        ids = []
        for p in content.parts or []:
            fr = getattr(p, "function_response", None)
            if fr:
                ids.append((getattr(fr, "id", None) or "").strip())
        return ids

    def _gemini_followup_matches_function_calls(self, model_c, user_c):
        """El user siguiente debe responder cada function_call (por id o por nombre)."""
        if self._gemini_role_name(user_c) != "user":
            return False
        fc_names = self._gemini_function_call_names(model_c)
        if not fc_names:
            return True
        fr_names = self._gemini_function_response_names(user_c)
        if len(fc_names) != len(fr_names):
            return False
        fc_ids = self._gemini_function_call_ids(model_c)
        fr_ids = self._gemini_function_response_ids(user_c)
        # Preferir match por id cuando ambos lados los traen.
        if fc_ids and fr_ids and all(fc_ids) and all(fr_ids):
            return sorted(fc_ids) == sorted(fr_ids)
        return sorted(fc_names) == sorted(fr_names)

    def _gemini_synthetic_function_response_parts(self, model_c, genai_types):
        """Parts function_response de error para cerrar function_calls sin respuesta."""
        parts = []
        for p in model_c.parts or []:
            fc = getattr(p, "function_call", None)
            if not fc:
                continue
            name = getattr(fc, "name", None) or "unknown_tool"
            fc_id = (getattr(fc, "id", None) or "").strip() or None
            fr_kwargs = {
                "name": name,
                "response": {
                    "error": (
                        "Resultado de herramienta no disponible en el historial; "
                        "se insertó una respuesta sintética para continuar."
                    )
                },
            }
            if fc_id:
                fr_kwargs["id"] = fc_id
            parts.append(
                genai_types.Part(
                    function_response=genai_types.FunctionResponse(**fr_kwargs)
                )
            )
        return parts

    def _gemini_ensure_contents_end_with_user(self, contents, genai_types):
        """La API Gemini rechaza peticiones que terminan en turno ``model``.

        Error típico: ``Requests ending with a model turn are not supported.``
        Si el último turno es model con function_call sin FR, cerramos con
        FR sintéticas. Si es solo texto (turno previo completo), no debería
        ocurrir al generar; como red de seguridad se omite ese model final
        vacío/placeholder o se añade un ancla user mínima.
        """
        if not contents:
            return [
                genai_types.Content(
                    role="user", parts=[genai_types.Part(text=" ")]
                )
            ]
        last = contents[-1]
        if self._gemini_role_name(last) != "model":
            return contents

        if self._gemini_content_has_function_call(last):
            fr_parts = self._gemini_synthetic_function_response_parts(
                last, genai_types
            )
            if fr_parts:
                _logger.warning(
                    "Gemini: historial terminaba en model con function_call sin "
                    "respuesta; se insertan %s function_response sintéticas.",
                    len(fr_parts),
                )
                return list(contents) + [
                    genai_types.Content(role="user", parts=fr_parts)
                ]

        # Model solo texto al final: quitar turnos model trailing vacíos;
        # si queda model con texto real, añadir ancla user (mejor que 400).
        out = list(contents)
        while out and self._gemini_role_name(out[-1]) == "model":
            parts = list(out[-1].parts or [])
            only_empty = all(
                (getattr(p, "text", None) or "").strip() == ""
                and not getattr(p, "function_call", None)
                for p in parts
            ) if parts else True
            if only_empty:
                _logger.warning(
                    "Gemini: se omite turno model vacío al final del historial."
                )
                out.pop()
                continue
            _logger.warning(
                "Gemini: historial terminaba en turno model; se añade ancla user."
            )
            out.append(
                genai_types.Content(
                    role="user",
                    parts=[genai_types.Part(text="Continúa con la solicitud.")],
                )
            )
            break
        if not out:
            out = [
                genai_types.Content(
                    role="user", parts=[genai_types.Part(text=" ")]
                )
            ]
        return out

    def _gemini_strip_function_calls_from_content(self, content, genai_types):
        """Quita partes function_call; si queda vacío, deja un Part con texto vacío."""
        parts = []
        for p in content.parts or []:
            if getattr(p, "function_call", None):
                continue
            parts.append(p)
        if not parts:
            parts = [genai_types.Part(text="")]
        return genai_types.Content(role=content.role, parts=parts)

    def _gemini_normalize_model_turn_parts_order(self, contents, genai_types):
        """Pone texto/otras partes antes que function_call en cada turno model.

        Gemini 3 suele exigir que las llamadas a función vayan al final del turno;
        un ``gemini_content_json`` restaurado podría traer otro orden y provocar 400.
        """
        out = []
        for c in contents:
            if self._gemini_role_name(c) != "model":
                out.append(c)
                continue
            parts = list(c.parts or [])
            fc_parts = [p for p in parts if getattr(p, "function_call", None)]
            non_fc = [p for p in parts if not getattr(p, "function_call", None)]
            if not fc_parts or not non_fc:
                out.append(c)
                continue
            out.append(
                genai_types.Content(role=c.role, parts=non_fc + fc_parts)
            )
        return out

    def _gemini_merge_consecutive_function_response_users(self, contents, genai_types):
        """Junta varios turnos user solo con function_response tras un model con FC.

        OpenAI usa un mensaje tool por herramienta; Gemini suele esperar un único
        turno user con todas las partes function_response antes del siguiente rol.
        """
        if not contents:
            return contents
        out = []
        i = 0
        n = len(contents)
        while i < n:
            c = contents[i]
            out.append(c)
            i += 1
            if not (
                self._gemini_role_name(c) == "model"
                and self._gemini_content_has_function_call(c)
            ):
                continue
            merged_parts = []
            while i < n:
                nxt = contents[i]
                if self._gemini_role_name(nxt) != "user":
                    break
                if not self._gemini_user_is_only_function_responses(nxt):
                    break
                merged_parts.extend(list(nxt.parts or []))
                i += 1
            if merged_parts:
                out.append(
                    genai_types.Content(role="user", parts=merged_parts)
                )
        return out

    def _gemini_strip_invalid_function_calls(self, contents, genai_types):
        """Quita o completa function_call del model según haya function_response.

        Si el model con FC está al final (aún sin FR en historial), **no** se
        deja el turno model solo: se añaden FR sintéticas. De lo contrario la
        API responde ``Requests ending with a model turn are not supported``.
        """
        if not contents:
            return contents
        out = []
        i = 0
        n = len(contents)
        while i < n:
            c = contents[i]
            if self._gemini_role_name(c) != "model":
                out.append(c)
                i += 1
                continue
            if not self._gemini_content_has_function_call(c):
                out.append(c)
                i += 1
                continue
            if i + 1 >= n:
                _logger.warning(
                    "Gemini: model con function_call al final del historial; "
                    "se cierran con function_response sintéticas."
                )
                out.append(c)
                fr_parts = self._gemini_synthetic_function_response_parts(
                    c, genai_types
                )
                if fr_parts:
                    out.append(
                        genai_types.Content(role="user", parts=fr_parts)
                    )
                i += 1
                continue
            nxt = contents[i + 1]
            if self._gemini_followup_matches_function_calls(c, nxt):
                out.append(c)
                i += 1
                continue
            _logger.warning(
                "Gemini: function_call sin function_response válida a continuación "
                "(fc=%s fr=%s); se cierran con respuestas sintéticas.",
                self._gemini_function_call_names(c),
                self._gemini_function_response_names(nxt)
                if self._gemini_role_name(nxt) == "user"
                else None,
            )
            out.append(c)
            fr_parts = self._gemini_synthetic_function_response_parts(c, genai_types)
            if fr_parts:
                out.append(genai_types.Content(role="user", parts=fr_parts))
            # Si el siguiente era solo FR huérfanas/incorrectas, saltarlo.
            if (
                self._gemini_role_name(nxt) == "user"
                and self._gemini_user_is_only_function_responses(nxt)
            ):
                i += 2
            else:
                i += 1
        return out

    def _gemini_strip_orphan_function_responses(self, contents):
        """Elimina turnos user solo con function_response sin model previo con FC coincidente.

        Red de seguridad tras límites de contexto, mensajes omitidos o datos incoherentes.
        """
        if not contents:
            return contents
        out = []
        for c in contents:
            if not (
                self._gemini_role_name(c) == "user"
                and self._gemini_user_is_only_function_responses(c)
            ):
                out.append(c)
                continue
            if not out:
                _logger.debug(
                    "Gemini: omitiendo function_response al inicio del historial"
                )
                continue
            prev = out[-1]
            if self._gemini_role_name(prev) != "model":
                _logger.debug(
                    "Gemini: omitiendo function_response sin turno model previo"
                )
                continue
            if not self._gemini_content_has_function_call(prev):
                _logger.debug(
                    "Gemini: omitiendo function_response sin FC en el model previo"
                )
                continue
            if not self._gemini_followup_matches_function_calls(prev, c):
                _logger.debug(
                    "Gemini: omitiendo function_response sin coincidencia con FC previas"
                )
                continue
            out.append(c)
        return out

    def _gemini_fix_consecutive_model_turns(self, contents, genai_types):
        """Evita 400 INVALID_ARGUMENT por dos turnos ``model`` seguidos (Gemini 3+).

        Inserta un turno user mínimo (espacio) entre dos ``model`` consecutivos y,
        si hace falta, uno antes del primer ``model``. No se inserta entre un
        ``model`` con function_call y el ``user`` con function_response que debe
        ir justo después (eso lo garantiza ``_gemini_strip_invalid_function_calls``
        y la fusión de respuestas de herramienta).
        """
        if not contents:
            return contents
        out = []
        for c in contents:
            if out:
                r_prev = self._gemini_role_name(out[-1])
                r_cur = self._gemini_role_name(c)
                if r_prev == "model" and r_cur == "model":
                    _logger.debug(
                        "Gemini: turno user sintético entre dos turnos model consecutivos"
                    )
                    out.append(
                        genai_types.Content(
                            role="user",
                            parts=[genai_types.Part(text=" ")],
                        )
                    )
            out.append(c)
        if self._gemini_role_name(out[0]) == "model":
            _logger.debug(
                "Gemini: turno user sintético antes del primer turno model del historial"
            )
            out.insert(
                0,
                genai_types.Content(
                    role="user",
                    parts=[genai_types.Part(text=" ")],
                ),
            )
        return out

    # ------------------------------------------------------------------
    # Conversión de respuestas Gemini → formato interno
    # ------------------------------------------------------------------

    def _gemini_fc_to_openai(self, fc):
        """Convierte un FunctionCall del nuevo SDK al formato tool_calls de llm_assistant."""
        args_dict = {}
        try:
            args = getattr(fc, "args", None)
            if args is None:
                args_dict = {}
            elif isinstance(args, dict):
                args_dict = dict(args)
            else:
                args_dict = dict(args)
        except (TypeError, ValueError):
            args_dict = {}

        try:
            args_preview = json.dumps(args_dict, ensure_ascii=False)
        except (TypeError, ValueError):
            args_preview = str(args_dict)

        if getattr(fc, "name", None) == "odoo_record_creator":
            _logger.info(
                "Gemini function_call odoo_record_creator: args=%s",
                args_preview[:4000],
            )

        return {
            "id": (getattr(fc, "id", None) or "").strip() or str(uuid.uuid4()),
            "type": "function",
            "function": {
                "name": getattr(fc, "name", "") or "",
                "arguments": json.dumps(args_dict, ensure_ascii=False),
            },
        }

    def _gemini_response_to_dict(self, response):
        """Extrae content, tool_calls y gemini_content_json de una respuesta no-streaming."""
        if not response.candidates:
            return {"content": "", "error": "Sin candidatos en la respuesta Gemini"}

        cand = response.candidates[0]
        parts = cand.content.parts if cand.content else []
        texts = []
        tool_calls = []

        for part in parts:
            if part.text:
                texts.append(part.text)
            fc = getattr(part, "function_call", None)
            if fc and getattr(fc, "name", None):
                tool_calls.append(self._gemini_fc_to_openai(fc))

        out = {"content": "\n".join(texts)}
        if tool_calls:
            out["tool_calls"] = tool_calls

        # Serializar el Content completo para preservar thought_signature real
        try:
            content_json = cand.content.model_dump_json()
            if content_json:
                out["gemini_content_json"] = content_json
        except Exception as err:
            _logger.debug("Gemini: no se pudo serializar content: %s", err)

        return out

    # ------------------------------------------------------------------
    # Chat principal
    # ------------------------------------------------------------------

    def _gemini_model_supports_tool_combination(self, model_name):
        """Combinar Google Search + function calling (tool context circulation).

        Documentación Google: preview en modelos Gemini 3+. Desde jul/2026 el
        alias ``gemini-flash-latest`` suele apuntar a Gemini 3.x Flash, así que
        también lo habilitamos; si la API rechaza la mezcla, el caller puede
        reintentar sin grounding.
        """
        name = (model_name or "").lower().strip()
        if not name:
            return False
        if "gemini-3" in name:
            return True
        # Aliases que rotan hacia la Flash «current» (a menudo 3.x).
        if name in (
            "gemini-flash-latest",
            "gemini-pro-latest",
            "models/gemini-flash-latest",
            "models/gemini-pro-latest",
        ):
            return True
        return False

    def _gemini_model_allows_thinking_budget_zero(self, model_name):
        """True si el modelo acepta ``thinking_budget=0`` (desactivar thinking).

        - Flash 2.5 clásico: sí.
        - Pro / varios alias ``*-latest`` / Gemini 3+: no; 0 → 400 INVALID_ARGUMENT.
        Ante la duda devolvemos False y **omitimos** el ThinkingConfig.
        """
        name = (model_name or "").lower().strip()
        if not name:
            return False
        if "pro" in name:
            return False
        # Alias inestables: gemini-flash-latest puede apuntar a 3.x Flash
        # que ya no admite 0. Mejor no enviar budget=0.
        if "latest" in name or "gemini-3" in name:
            return False
        if "flash" in name and "2.5" in name:
            return True
        if "flash-lite" in name or "flash_lite" in name:
            return True
        return False

    def _gemini_clamp_thinking_budget(self, model_name, budget):
        """Ajusta el presupuesto al rango válido del modelo (o None para omitir).

        ``None`` → no enviar ThinkingConfig (dejar default del modelo).
        Entero >= 1 → thinking activo (mín. 128 en familias Pro).
        ``0`` → solo si el modelo lo admite; si no, se omite (None).
        """
        if budget is None:
            return None
        try:
            budget = int(budget)
        except (TypeError, ValueError):
            return None
        name = (model_name or "").lower().strip()
        if budget <= 0:
            if self._gemini_model_allows_thinking_budget_zero(name):
                return 0
            return None
        # Pro no admite 0; el mínimo documentado es 128.
        if "pro" in name and budget < 128:
            return 128
        return budget

    def _gemini_build_thinking_config(
        self, genai_types, model_name, budget, include_thoughts=False
    ):
        """Construye ThinkingConfig o None si debe omitirse."""
        clamped = self._gemini_clamp_thinking_budget(model_name, budget)
        if clamped is None:
            return None
        kwargs = {"thinking_budget": clamped}
        if include_thoughts and clamped > 0:
            kwargs["include_thoughts"] = True
        return genai_types.ThinkingConfig(**kwargs)

    def _gemini_build_tool_config_function_auto(self, genai_types, use_google_search_grounding):
        """ToolConfig para function calling Odoo; marca server-side si hay grounding combinado.

        Con ``include_server_side_tool_invocations`` la API **no** admite
        ``mode=AUTO``: exige ``VALIDATED`` (ver Gemini tool combination docs).
        Usar AUTO provoca 400 INVALID_ARGUMENT.
        """
        mode = "VALIDATED" if use_google_search_grounding else "AUTO"
        _tc_kwargs = {
            "function_calling_config": genai_types.FunctionCallingConfig(mode=mode),
        }
        if use_google_search_grounding:
            _tc_kwargs["include_server_side_tool_invocations"] = True
            mf = getattr(genai_types.ToolConfig, "model_fields", None) or {}
            if "include_server_side_tool_invocations" in mf:
                return genai_types.ToolConfig(**_tc_kwargs)
            return _gemini_tool_config_extended_class()(**_tc_kwargs)
        return genai_types.ToolConfig(**_tc_kwargs)

    def gemini_chat(
        self,
        messages,
        model=None,
        stream=False,
        tools=None,
        prepend_messages=None,
        **kwargs,
    ):
        """Chat con Gemini usando el nuevo SDK google-genai (1.x).

        Ventajas frente al SDK anterior:
        - parameters_json_schema con schema sanitizado (sin additionalProperties /
          anyOf+null de Pydantic) para evitar 400 INVALID_ARGUMENT.
        - ThinkingConfig solo se envía con presupuestos válidos por modelo:
          ``thinking_budget=0`` provoca 400 en Pro / alias ``*-latest`` / Gemini 3+.
        - thought_signature se maneja automáticamente al restaurar Content serializado.
        """
        from google import genai as genai_module
        from google.genai import types as genai_types

        model_obj = self.get_model(model, "chat")
        client = self.gemini_get_client()

        openai_style = self._gemini_build_openai_style_message_list(
            prepend_messages, messages
        )
        system_prompt_kw = kwargs.get("system_prompt")
        if system_prompt_kw:
            openai_style = [
                {"role": "system", "content": system_prompt_kw}
            ] + openai_style

        contents, system_instruction = self._gemini_build_contents(openai_style)

        has_odoo_tools = bool(tools)
        want_google_search = bool(
            getattr(model_obj, "gemini_google_search_grounding", False)
        )

        # Combinar Google Search + tools Odoo: Gemini 3+ / alias latest.
        use_google_search_grounding = want_google_search
        if want_google_search and has_odoo_tools:
            if not self._gemini_model_supports_tool_combination(model_obj.name):
                _logger.warning(
                    "Gemini: el modelo «%s» no soporta combinar Google Search "
                    "con herramientas Odoo (solo Gemini 3+ / alias latest). "
                    "Se desactiva grounding en esta petición.",
                    model_obj.name,
                )
                use_google_search_grounding = False

        # Construir config
        config_kwargs = {}
        if system_instruction:
            config_kwargs["system_instruction"] = system_instruction

        declarations = None
        if has_odoo_tools:
            declarations = self.gemini_format_tools(tools)
            tool_names = [t.name for t in tools]
            _logger.info(
                "Gemini: petición con function calling, herramientas=%s", tool_names
            )
            config_kwargs["tools"] = [
                genai_types.Tool(function_declarations=declarations)
            ]
            config_kwargs["tool_config"] = self._gemini_build_tool_config_function_auto(
                genai_types, use_google_search_grounding
            )

        # Grounding: en Gemini 3+ / latest se combina con function calling
        # (mode=VALIDATED + include_server_side_tool_invocations).
        if use_google_search_grounding:
            config_kwargs.setdefault("tools", [])
            config_kwargs["tools"].append(
                genai_types.Tool(google_search=genai_types.GoogleSearch())
            )
            if has_odoo_tools:
                _logger.info(
                    "Gemini: Google Search grounding activo junto con herramientas Odoo "
                    "(mode=VALIDATED)."
                )
            else:
                _logger.info("Gemini: Google Search grounding activo.")

        # AFC del SDK ejecuta callables Python y reescribe ``contents``.
        # Con tools Odoo las ejecutamos nosotros en generate_messages: AFC
        # activo provoca bucles rotos («Requests ending with a model turn…»).
        AFCConfig = getattr(genai_types, "AutomaticFunctionCallingConfig", None)
        if AFCConfig and has_odoo_tools:
            config_kwargs["automatic_function_calling"] = AFCConfig(disable=True)
            _logger.info(
                "Gemini: AFC desactivado (tools Odoo se ejecutan en el hilo)."
            )

        # Pensamiento: solo si hay presupuesto válido para este modelo.
        exp_tb = kwargs.get("experience_thinking_budget")
        if exp_tb is not None and int(exp_tb) > 0:
            thinking_cfg = self._gemini_build_thinking_config(
                genai_types,
                model_obj.name,
                int(exp_tb),
                include_thoughts=bool(kwargs.get("experience_include_thoughts")),
            )
            if thinking_cfg is not None:
                config_kwargs["thinking_config"] = thinking_cfg
                _logger.info(
                    "Gemini: thinking_budget=%s (modelo=%s).",
                    thinking_cfg.thinking_budget,
                    model_obj.name,
                )
            else:
                _logger.warning(
                    "Gemini: no se pudo aplicar thinking_budget=%s al modelo «%s»; "
                    "se omite ThinkingConfig.",
                    exp_tb,
                    model_obj.name,
                )

        def _drop_google_search_from_config_kwargs(ck):
            """Quita grounding y vuelve tool_config a AUTO (solo function calling)."""
            tools_list = list(ck.get("tools") or [])
            ck["tools"] = [
                t
                for t in tools_list
                if not getattr(t, "google_search", None)
            ]
            if has_odoo_tools and declarations is not None:
                ck["tool_config"] = self._gemini_build_tool_config_function_auto(
                    genai_types, False
                )
            elif "tool_config" in ck:
                ck.pop("tool_config", None)
            return ck

        def _is_tool_combination_reject(err):
            msg = str(err or "").lower()
            return any(
                s in msg
                for s in (
                    "cannot be combined",
                    "can not be combined",
                    "tool combination",
                    "built-in tools",
                    "google_search",
                    "include_server_side_tool_invocations",
                )
            )

        config = (
            genai_types.GenerateContentConfig(**config_kwargs)
            if config_kwargs
            else None
        )

        if stream:
            def _consume_stream(resp_iter):
                seen_fc_keys = set()
                last_content = None
                last_usage_chunk = None
                for chunk in resp_iter:
                    um = getattr(chunk, "usage_metadata", None)
                    if um:
                        last_usage_chunk = chunk
                    if not chunk.candidates:
                        continue
                    cand = chunk.candidates[0]
                    if not cand.content:
                        continue
                    last_content = cand.content
                    for part in cand.content.parts:
                        if part.text:
                            yield {"content": part.text}
                        fc = getattr(part, "function_call", None)
                        if fc and getattr(fc, "name", None):
                            key = (getattr(fc, "id", "") or "", fc.name)
                            if key in seen_fc_keys:
                                continue
                            seen_fc_keys.add(key)
                            yield {"tool_calls": [self._gemini_fc_to_openai(fc)]}
                if last_content:
                    try:
                        content_json = last_content.model_dump_json()
                        if content_json:
                            yield {"gemini_content_json": content_json}
                    except Exception as err:
                        _logger.debug(
                            "Gemini: no se pudo serializar streaming content: %s", err
                        )
                if last_usage_chunk is not None:
                    yield {
                        "_usage_internal": self._gemini_usage_metadata_dict(
                            last_usage_chunk
                        )
                    }

            def _stream():
                nonlocal config, config_kwargs, use_google_search_grounding
                try:
                    resp_iter = client.models.generate_content_stream(
                        model=model_obj.name,
                        contents=contents,
                        config=config,
                    )
                    yield from _consume_stream(resp_iter)
                except Exception as err:
                    if (
                        use_google_search_grounding
                        and has_odoo_tools
                        and _is_tool_combination_reject(err)
                    ):
                        _logger.warning(
                            "Gemini: la API rechazó combinar Google Search con tools "
                            "(%s). Reintento sin grounding.",
                            err,
                        )
                        use_google_search_grounding = False
                        config_kwargs = _drop_google_search_from_config_kwargs(
                            dict(config_kwargs)
                        )
                        config = genai_types.GenerateContentConfig(**config_kwargs)
                        try:
                            resp_iter = client.models.generate_content_stream(
                                model=model_obj.name,
                                contents=contents,
                                config=config,
                            )
                            yield from _consume_stream(resp_iter)
                            return
                        except Exception as err2:
                            _logger.error(
                                "Gemini: error en streaming (reintento): %s",
                                err2,
                                exc_info=True,
                            )
                            yield {"error": str(err2)}
                            return
                    _logger.error(
                        "Gemini: error en streaming: %s",
                        err,
                        exc_info=True,
                    )
                    yield {"error": str(err)}

            return _stream()

        # No streaming
        try:
            response = client.models.generate_content(
                model=model_obj.name,
                contents=contents,
                config=config,
            )
        except Exception as err:
            if (
                use_google_search_grounding
                and has_odoo_tools
                and _is_tool_combination_reject(err)
            ):
                _logger.warning(
                    "Gemini: la API rechazó combinar Google Search con tools "
                    "(%s). Reintento sin grounding.",
                    err,
                )
                config_kwargs = _drop_google_search_from_config_kwargs(
                    dict(config_kwargs)
                )
                config = genai_types.GenerateContentConfig(**config_kwargs)
                try:
                    response = client.models.generate_content(
                        model=model_obj.name,
                        contents=contents,
                        config=config,
                    )
                except Exception as err2:
                    _logger.error(
                        "Gemini: error en generate_content (reintento): %s",
                        err2,
                        exc_info=True,
                    )
                    raise UserError(_("Error en Gemini API: %s") % err2) from err2
            else:
                _logger.error(
                    "Gemini: error en generate_content: %s",
                    err,
                    exc_info=True,
                )
                raise UserError(_("Error en Gemini API: %s") % err) from err

        out = self._gemini_response_to_dict(response)
        out["_usage_internal"] = self._gemini_usage_metadata_dict(response)
        return out

    def _gemini_usage_metadata_dict(self, response_or_chunk):
        """Unifica usage_metadata del SDK (respuesta o chunk de stream) en dict simple."""
        out = {
            "prompt": 0,
            "cached": 0,
            "output": 0,
            "thoughts": 0,
            "total": 0,
        }
        um = getattr(response_or_chunk, "usage_metadata", None)
        if not um:
            return out
        try:
            out["prompt"] = int(getattr(um, "prompt_token_count", None) or 0)
            out["cached"] = int(getattr(um, "cached_content_token_count", None) or 0)
            out["output"] = int(getattr(um, "candidates_token_count", None) or 0)
            out["thoughts"] = int(getattr(um, "thoughts_token_count", None) or 0)
            out["total"] = int(getattr(um, "total_token_count", None) or 0)
        except (TypeError, ValueError):
            pass
        return out
