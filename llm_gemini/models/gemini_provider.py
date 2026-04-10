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
_GEMINI_DUMMY_THOUGHT_SIGNATURE = b"context_engineering_is_the_way to_go"


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

    def gemini_format_tools(self, tools):
        """Formatea herramientas Odoo para el nuevo SDK (usa parameters_json_schema)."""
        from google.genai import types as genai_types

        declarations = []
        for tool in tools:
            schema = tool.get_input_schema() or {}
            if not isinstance(schema, dict):
                schema = {"type": "object", "properties": {}}

            # Con parameters_json_schema enviamos el JSON Schema COMPLETO (igual que OpenAI),
            # sin necesidad de sanitizar anyOf, additionalProperties, etc.
            # Esto garantiza que Gemini recibe exactamente el mismo schema que ChatGPT.
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
        """Añade «name» al mensaje tipo tool si el registro lo tiene."""
        if not formatted or formatted.get("role") != "tool":
            return
        if not hasattr(record, "body_json"):
            return
        td = record.body_json or {}
        if td.get("tool_name"):
            formatted["name"] = td["tool_name"]

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

                tc_list = msg.get("tool_calls") or []
                if tc_list:
                    _logger.info(
                        "Gemini: assistant FunctionCall(s) en historial: %s",
                        [(tc.get("id"), (tc.get("function") or {}).get("name")) for tc in tc_list],
                    )

                contents.append(genai_types.Content(role="model", parts=parts))

            elif role == "tool":
                name = msg.get("name") or "unknown_tool"
                call_id = msg.get("tool_call_id") or ""
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

                _logger.info(
                    "Gemini: FunctionResponse name=%s, id=%s, response_keys=%s, response_snippet=%.300s",
                    name, call_id,
                    list(resp_obj.keys()) if isinstance(resp_obj, dict) else type(resp_obj).__name__,
                    json.dumps(resp_obj, ensure_ascii=False, default=str)[:300],
                )

                fr_kwargs = {"name": name, "response": resp_obj}
                if call_id:
                    fr_kwargs["id"] = call_id

                contents.append(
                    genai_types.Content(
                        role="user",
                        parts=[
                            genai_types.Part(
                                function_response=genai_types.FunctionResponse(
                                    **fr_kwargs,
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
        if not contents:
            contents = [
                genai_types.Content(role="user", parts=[genai_types.Part(text="")])
            ]

        summary = []
        for c in contents:
            rn = self._gemini_role_name(c)
            part_types = []
            for p in (c.parts or []):
                if getattr(p, "function_call", None):
                    fc = p.function_call
                    part_types.append("FC(%s,id=%s)" % (getattr(fc, "name", "?"), getattr(fc, "id", "?")))
                elif getattr(p, "function_response", None):
                    fr = p.function_response
                    resp = getattr(fr, "response", None) or {}
                    part_types.append("FR(%s,id=%s,keys=%s)" % (
                        getattr(fr, "name", "?"),
                        getattr(fr, "id", "?"),
                        list(resp.keys()) if isinstance(resp, dict) else "?",
                    ))
                elif getattr(p, "text", None):
                    part_types.append("text(%d)" % len(p.text))
                else:
                    part_types.append("other")
            summary.append("%s:[%s]" % (rn, ",".join(part_types)))
        _logger.info(
            "Gemini: resumen de contents (%d turnos): %s",
            len(contents), " | ".join(summary),
        )

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

    def _gemini_followup_matches_function_calls(self, model_c, user_c):
        """El user siguiente debe tener una function_response por cada function_call (mismos nombres)."""
        if self._gemini_role_name(user_c) != "user":
            return False
        fc_names = self._gemini_function_call_names(model_c)
        if not fc_names:
            return True
        fr_names = self._gemini_function_response_names(user_c)
        return sorted(fc_names) == sorted(fr_names) and len(fc_names) == len(fr_names)

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
        """Quita function_call del model si no sigue un user con todas las function_response.

        Si se omiten las FC del model, también se omite el siguiente turno user que solo
        traía esas function_response; si no, la API devuelve 400 por respuestas de
        herramienta huérfanas (sin function_call previo en el turno model).
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
                _logger.debug(
                    "Gemini: model con function_call al final; se omiten las llamadas"
                )
                out.append(
                    self._gemini_strip_function_calls_from_content(c, genai_types)
                )
                i += 1
                continue
            nxt = contents[i + 1]
            if self._gemini_followup_matches_function_calls(c, nxt):
                out.append(c)
                i += 1
                continue
            _logger.debug(
                "Gemini: function_call sin function_response válida a continuación; "
                "se omiten las llamadas del turno model"
            )
            out.append(self._gemini_strip_function_calls_from_content(c, genai_types))
            if (
                self._gemini_role_name(nxt) == "user"
                and self._gemini_user_is_only_function_responses(nxt)
            ):
                _logger.debug(
                    "Gemini: omitiendo turno user solo con function_response "
                    "asociado a FC omitidas"
                )
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

    def _gemini_build_tool_config_function_auto(self, genai_types, use_google_search_grounding):
        """ToolConfig para function calling Odoo; marca server-side si hay grounding combinado."""
        _tc_kwargs = {
            "function_calling_config": genai_types.FunctionCallingConfig(mode="AUTO"),
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
        - parameters_json_schema envía el schema JSON completo (anyOf, additionalProperties)
          igual que ChatGPT, evitando que el modelo confunda tipos de parámetros.
        - thinking_budget=0 desactiva el pensamiento profundo en tool calls para evitar
          que Gemini 3 Flash sobre-razone y confunda write_values con fields.
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
        use_google_search_grounding = bool(
            getattr(model_obj, "gemini_google_search_grounding", False)
        )
        deep_thinking = bool(
            kwargs.get("experience_thinking_budget") is not None
            and int(kwargs.get("experience_thinking_budget") or 0) > 0
        )

        # Construir config
        config_kwargs = {}
        if system_instruction:
            config_kwargs["system_instruction"] = system_instruction

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
            # Desactivar pensamiento profundo para tool calls (salvo modo experiencia):
            # Gemini 3 Flash con HIGH thinking confunde write_values (objeto) con fields (lista).
            # thinking_budget=0 = DISABLED según la documentación del SDK.
            config_kwargs["thinking_config"] = genai_types.ThinkingConfig(
                thinking_budget=0
            )

        # Grounding: en modelos recientes se puede combinar con function calling
        # (ver tool combinations en la documentación de Gemini API).
        if use_google_search_grounding:
            config_kwargs.setdefault("tools", [])
            config_kwargs["tools"].append(
                genai_types.Tool(google_search=genai_types.GoogleSearch())
            )
            if has_odoo_tools:
                _logger.info(
                    "Gemini: Google Search grounding activo junto con herramientas Odoo."
                )
            else:
                _logger.info("Gemini: Google Search grounding activo.")

        # AFC (Automatic Function Calling del SDK): por defecto el SDK usa 10 llamadas remotas.
        # Con pensamiento profundo lo desactivamos para no encadenar rondas AFC pesadas;
        # en el resto de casos subimos el techo (configurable en el modelo).
        AFCConfig = getattr(genai_types, "AutomaticFunctionCallingConfig", None)
        if AFCConfig and has_odoo_tools:
            if deep_thinking:
                config_kwargs["automatic_function_calling"] = AFCConfig(disable=True)
                _logger.info(
                    "Gemini: AFC desactivado (modo pensamiento profundo / experiencia)."
                )
            else:
                max_remote = int(
                    getattr(model_obj, "gemini_afc_max_remote_calls", 0) or 30
                )
                max_remote = max(1, max_remote)
                config_kwargs["automatic_function_calling"] = AFCConfig(
                    maximum_remote_calls=max_remote,
                )
                _logger.info(
                    "Gemini: AFC activo con máximo de llamadas remotas: %s", max_remote
                )

        # Módulo llm_experience: pensamiento profundo (sobrescribe thinking de tools si aplica)
        exp_tb = kwargs.get("experience_thinking_budget")
        if exp_tb is not None and int(exp_tb) > 0:
            config_kwargs["thinking_config"] = genai_types.ThinkingConfig(
                thinking_budget=int(exp_tb),
                include_thoughts=bool(kwargs.get("experience_include_thoughts")),
            )

        config = genai_types.GenerateContentConfig(**config_kwargs) if config_kwargs else None

        if stream:
            def _stream():
                try:
                    resp_iter = client.models.generate_content_stream(
                        model=model_obj.name,
                        contents=contents,
                        config=config,
                    )
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
                    # Serializar el Content completo del último chunk (preserva thought_signature)
                    if last_content:
                        try:
                            content_json = last_content.model_dump_json()
                            if content_json:
                                yield {"gemini_content_json": content_json}
                        except Exception as err:
                            _logger.debug("Gemini: no se pudo serializar streaming content: %s", err)
                    if last_usage_chunk is not None:
                        yield {
                            "_usage_internal": self._gemini_usage_metadata_dict(
                                last_usage_chunk
                            )
                        }
                except Exception as err:
                    _logger.error("Gemini: error en streaming: %s", err)
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
            _logger.error("Gemini: error en generate_content: %s", err)
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
