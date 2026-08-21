# -*- coding: utf-8 -*-
"""Parches para llm_anthropic:

- Aceptar recordset de mail.message y prepend_messages (como el resto del stack).
- Formatear tools de Odoo (``llm.tool``) al esquema Anthropic.
- Traducir assistant-con-``tool_calls`` y mensajes ``tool`` al esquema
  ``tool_use`` / ``tool_result`` de Anthropic.
- Emitir ``tool_calls`` (formato OpenAI-like que espera ``_handle_streaming_response``)
  tanto en streaming como en no streaming.
- Activar Extended Thinking (``deep_thinking``) y el tool server-side
  ``web_search`` cuando procede.

Documentación de referencia:
- Tool use:            https://docs.claude.com/en/docs/agents-and-tools/tool-use/overview
- Extended thinking:   https://docs.claude.com/en/docs/build-with-claude/extended-thinking
- Web search tool:     https://docs.claude.com/en/docs/agents-and-tools/tool-use/web-search-tool
"""
import base64
import json
import logging
import re

from odoo import models, tools

_logger = logging.getLogger(__name__)


# MIME types de imagen aceptados por Anthropic (image blocks).
# Docs: https://docs.claude.com/en/docs/build-with-claude/vision
_ANTHROPIC_IMAGE_MIMES = (
    "image/jpeg",
    "image/png",
    "image/gif",
    "image/webp",
)


# Modelos Anthropic que soportan Extended Thinking (reasoning).
# Regla conservadora: Claude 3.7+ y Claude 4+ (opus/sonnet/haiku).
_ANTHROPIC_THINKING_RE = re.compile(
    r"claude-(?:3-7|opus-4|sonnet-4|haiku-4|opus-4-\d|sonnet-4-\d|haiku-4-\d|4)",
    re.I,
)

# Versión del tool server-side de web search (API directa). No funciona
# en Bedrock/Vertex; se puede sobreescribir por ``ir.config_parameter``.
_ANTHROPIC_WEB_SEARCH_TOOL_TYPE = "web_search_20250305"


class LLMProviderAnthropic(models.Model):
    _inherit = "llm.provider"

    # ==================================================================
    # Cliente: retries / timeout configurables
    # ==================================================================
    def anthropic_get_client(self):
        """Override para permitir ajustar ``max_retries`` y ``timeout``.

        El SDK de Anthropic ya implementa *exponential backoff con jitter*
        y respeta ``retry-after`` en los 429. El problema es que por
        defecto solo reintenta 2 veces, y con Opus-4 el ``retry-after``
        puede ser de 30-60 s, así que 2 intentos suelen bastar… pero solo
        si el primer error es esporádico.

        Subimos el default a 4 reintentos para que una ráfaga de 429s
        consecutivos no aborte la petición. Se puede seguir ajustando
        mediante ``ir.config_parameter``:

        * ``llm_experience.anthropic_max_retries``  (default 4)
        * ``llm_experience.anthropic_timeout``      (default 180 s)
        """
        from anthropic import Anthropic
        icp = self.env["ir.config_parameter"].sudo()
        try:
            max_retries = int(
                icp.get_param("llm_experience.anthropic_max_retries")
                or 4
            )
        except (TypeError, ValueError):
            max_retries = 4
        try:
            timeout = float(
                icp.get_param("llm_experience.anthropic_timeout")
                or 180.0
            )
        except (TypeError, ValueError):
            timeout = 180.0
        return Anthropic(
            api_key=self.api_key,
            max_retries=max(0, max_retries),
            timeout=timeout,
        )

    # ==================================================================
    # Prompt caching helpers
    # ==================================================================
    def _anthropic_prompt_caching_enabled(self):
        """Comprueba el ICP maestro. Default: activo.

        El prompt caching reduce drásticamente la presión sobre ITPM:
        los tokens marcados con ``cache_control`` no cuentan contra los
        *Input Tokens Per Minute* en las lecturas posteriores (TTL
        5 min por defecto, o 1 h si se fuerza). Esto es crítico con
        Opus-4, cuyo límite de ITPM es comparativamente bajo.
        """
        icp = self.env["ir.config_parameter"].sudo()
        raw = (icp.get_param("llm_experience.anthropic_prompt_caching", "1") or "1")
        return raw.strip().lower() not in ("0", "false", "no", "off", "")

    def _anthropic_apply_prompt_caching(self, params):
        """Marca system + tools + último mensaje histórico con
        ``cache_control: {"type": "ephemeral"}`` para reutilizar tokens
        cacheados entre turnos y evitar 429 de ITPM en modelos caros.

        Sigue las recomendaciones oficiales de Anthropic:
        https://platform.claude.com/docs/en/build-with-claude/prompt-caching

        Estrategia:
        * ``system``: si es string no vacío, se transforma en una lista
          con un solo bloque ``{"type": "text", "text": ..., "cache_control": ephemeral}``.
        * ``tools``: se añade ``cache_control`` al último tool del array,
          con lo que toda la sección de definiciones queda cacheada en bloque.
        * ``messages``: se añade ``cache_control`` al *último* bloque del
          penúltimo mensaje (para que el hit del caché cubra todo el
          historial de turnos anteriores cuando llegue el siguiente turno).
        """
        if not self._anthropic_prompt_caching_enabled():
            return params

        # ---------- system ----------
        system = params.get("system")
        if isinstance(system, str) and system.strip():
            params["system"] = [
                {
                    "type": "text",
                    "text": system,
                    "cache_control": {"type": "ephemeral"},
                }
            ]
        elif isinstance(system, list) and system:
            last = system[-1]
            if isinstance(last, dict):
                last.setdefault("cache_control", {"type": "ephemeral"})

        # ---------- tools ----------
        tools_list = params.get("tools")
        if isinstance(tools_list, list) and tools_list:
            last_tool = tools_list[-1]
            if isinstance(last_tool, dict):
                # Los server-side tools (web_search_*) no admiten cache_control;
                # buscamos el último tool "normal" (con input_schema).
                target = None
                for t in reversed(tools_list):
                    if isinstance(t, dict) and "input_schema" in t:
                        target = t
                        break
                if target is not None:
                    target.setdefault("cache_control", {"type": "ephemeral"})

        # ---------- messages (cachea histórico anterior al último turno) ----------
        msgs = params.get("messages")
        if isinstance(msgs, list) and len(msgs) >= 2:
            # Marcamos el último bloque del penúltimo mensaje: así el
            # siguiente turno reutiliza TODO el historial previo.
            anchor = msgs[-2]
            content = anchor.get("content") if isinstance(anchor, dict) else None
            if isinstance(content, str) and content:
                anchor["content"] = [
                    {
                        "type": "text",
                        "text": content,
                        "cache_control": {"type": "ephemeral"},
                    }
                ]
            elif isinstance(content, list) and content:
                last_block = content[-1]
                if isinstance(last_block, dict):
                    last_block.setdefault(
                        "cache_control", {"type": "ephemeral"}
                    )
        return params

    # ==================================================================
    # Formateo de tools (Odoo llm.tool → esquema Anthropic)
    # ==================================================================
    def anthropic_format_tools(self, tool_recordset):
        """Convierte un recordset ``llm.tool`` al formato tool-spec de Anthropic.

        Anthropic espera ``{"name", "description", "input_schema"}``. El
        ``input_schema`` debe ser un JSON Schema con ``type: object``.
        """
        out = []
        for tool in tool_recordset or []:
            schema = self._anthropic_resolve_tool_schema(tool)
            if not isinstance(schema, dict):
                schema = {"type": "object", "properties": {}, "required": []}
            # Anthropic exige explícitamente type=object y properties dict.
            if schema.get("type") != "object":
                schema = dict(schema)
                schema["type"] = "object"
            if not isinstance(schema.get("properties"), dict):
                schema["properties"] = {}
            spec = {
                "name": tool.name,
                "description": tool.description or "",
                "input_schema": schema,
            }
            out.append(spec)
        return out

    def _anthropic_resolve_tool_schema(self, tool):
        """Devuelve el JSON Schema del tool con los mismos fallbacks que OpenAI."""
        try:
            if getattr(tool, "input_schema", None):
                try:
                    return json.loads(tool.input_schema)
                except (TypeError, ValueError, json.JSONDecodeError):
                    _logger.warning(
                        "Anthropic: input_schema inválido en tool %s", tool.name
                    )
            if hasattr(tool, "get_input_schema"):
                schema = tool.get_input_schema() or None
                if schema:
                    return schema
        except Exception as err:
            _logger.warning(
                "Anthropic: error resolviendo schema de tool %s: %s",
                getattr(tool, "name", tool),
                err,
            )
        return {"type": "object", "properties": {}, "required": []}

    # ==================================================================
    # Formateo de mensajes (recordset / dict → lista estilo Anthropic)
    # ==================================================================
    def anthropic_format_messages(self, messages, system_prompt=None):
        """Convierte recordset mail.message y/o dicts al formato Anthropic."""
        formatted = []
        if system_prompt:
            formatted.append({"role": "system", "content": system_prompt})
        for message in messages or []:
            if isinstance(message, dict) and message.get("role"):
                formatted.append(dict(message))
                continue
            msg = self._anthropic_format_single_record(message)
            if msg:
                formatted.append(msg)
        return formatted

    def _anthropic_user_content_parts(self, record, body_text):
        """Construye content multimodal para mensajes de usuario de Anthropic.

        - Imágenes (jpeg/png/gif/webp) ⇒ bloques ``image`` con ``source`` base64.
        - PDFs ⇒ bloques ``document`` nativos (Claude 3.5+ con visión de PDF);
          si Anthropic rechaza el formato, el modelo lo tratará como documento.
        - Resto (Excel, Word, TXT, JSON, HTML, etc.) ⇒ se extrae texto con
          ``ir.attachment.llm_extract_text()`` y se añade como bloque de texto.
          Si no hay extractor disponible, se adjunta un marcador informativo.

        Retorna una lista de bloques lista para ``messages.create``. Si el
        mensaje no tiene adjuntos, devuelve ``[{"type": "text", "text": body}]``
        (o lista vacía si tampoco hay texto).
        """
        parts = []
        text_block = (body_text or "").strip()
        if text_block:
            parts.append({"type": "text", "text": body_text})

        attachments = getattr(record, "attachment_ids", False)
        if not attachments:
            return parts

        for att in attachments.sorted("id"):
            mimetype = (att.mimetype or "").lower()
            name = (att.name or "").lower()

            # ---------- Imágenes (image block) ----------
            is_image = (
                mimetype in _ANTHROPIC_IMAGE_MIMES
                or (mimetype.startswith("image/") and att.datas)
            )
            if is_image:
                try:
                    raw_b64 = att.datas
                    if isinstance(raw_b64, bytes):
                        raw_b64 = raw_b64.decode()
                    media_type = (
                        mimetype
                        if mimetype in _ANTHROPIC_IMAGE_MIMES
                        else "image/png"
                    )
                    parts.append(
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": media_type,
                                "data": raw_b64,
                            },
                        }
                    )
                except Exception as err:
                    _logger.warning(
                        "Anthropic: no se pudo incluir imagen adjunta %s: %s",
                        att.id,
                        err,
                    )
                    parts.append(
                        {
                            "type": "text",
                            "text": f"[Adjunto imagen omitido: {att.name}]",
                        }
                    )
                continue

            # ---------- PDF nativo (document block) ----------
            is_pdf = mimetype == "application/pdf" or name.endswith(".pdf")
            if is_pdf:
                try:
                    raw_bytes = att.sudo()._llm_get_raw_bytes()
                    if raw_bytes:
                        pdf_b64 = base64.b64encode(raw_bytes).decode()
                        parts.append(
                            {
                                "type": "document",
                                "source": {
                                    "type": "base64",
                                    "media_type": "application/pdf",
                                    "data": pdf_b64,
                                },
                                "title": att.name or "documento.pdf",
                            }
                        )
                        continue
                except Exception as err:
                    _logger.warning(
                        "Anthropic: no se pudo enviar PDF %s como documento "
                        "nativo, se intentará extraer texto. Error: %s",
                        att.id,
                        err,
                    )
                # Fallback: extraer texto con pypdf.
                extracted = ""
                try:
                    extracted = att.sudo().llm_extract_text() or ""
                except Exception as err:
                    _logger.warning(
                        "Anthropic: fallo extrayendo texto del PDF %s: %s",
                        att.id,
                        err,
                    )
                if extracted.strip():
                    parts.append(
                        {
                            "type": "text",
                            "text": (
                                f"--- Contenido extraído del PDF «{att.name}» ---\n"
                                f"{extracted}\n"
                                f"--- Fin del archivo ---"
                            ),
                        }
                    )
                else:
                    parts.append(
                        {
                            "type": "text",
                            "text": (
                                f"[Adjunto PDF sin texto extraíble: {att.name}]"
                            ),
                        }
                    )
                continue

            # ---------- Otros (Excel, Word, TXT, JSON, HTML…) ----------
            extracted = ""
            try:
                extracted = att.sudo().llm_extract_text() or ""
            except Exception as err:
                _logger.warning(
                    "Anthropic: fallo extrayendo texto del adjunto %s (%s): %s",
                    att.id,
                    att.name,
                    err,
                )
            if extracted.strip():
                parts.append(
                    {
                        "type": "text",
                        "text": (
                            f"--- Contenido extraído del archivo «{att.name}» "
                            f"({mimetype or 'tipo desconocido'}) ---\n"
                            f"{extracted}\n"
                            f"--- Fin del archivo ---"
                        ),
                    }
                )
            else:
                meta = (
                    f'{att.name} ({mimetype or "sin tipo"}, '
                    f'{att.file_size or 0} bytes)'
                )
                parts.append(
                    {
                        "type": "text",
                        "text": (
                            "[Archivo adjunto sin texto extraíble automáticamente "
                            "(PDF: pypdf; Excel: openpyxl; Word: python-docx; "
                            f"o use texto/imagen): {meta}]"
                        ),
                    }
                )

        return parts

    def _anthropic_format_single_record(self, record):
        """Convierte un ``mail.message`` a un dict rol/content de Anthropic."""
        try:
            body = record.body or ""
            if body:
                body = tools.html2plaintext(body)
            role = getattr(record, "llm_role", False)
            if not role:
                return None

            if role == "system":
                return {"role": "system", "content": body}

            if role == "user":
                parts = self._anthropic_user_content_parts(record, body)
                if len(parts) == 1 and parts[0].get("type") == "text":
                    return {"role": "user", "content": parts[0]["text"]}
                if parts:
                    return {"role": "user", "content": parts}
                return {"role": "user", "content": body or ""}

            if role == "assistant":
                data = getattr(record, "body_json", None) or {}
                tool_calls = data.get("tool_calls") or []
                if not tool_calls:
                    return {"role": "assistant", "content": body or ""}
                # Reconstruir bloques tool_use (necesarios para que Anthropic
                # acepte el tool_result posterior).
                blocks = []
                if body:
                    blocks.append({"type": "text", "text": body})
                for tc in tool_calls:
                    fn = tc.get("function", {}) or {}
                    args = fn.get("arguments")
                    if isinstance(args, str):
                        try:
                            args_obj = json.loads(args) if args.strip() else {}
                        except (ValueError, json.JSONDecodeError):
                            args_obj = {"_raw": args}
                    elif isinstance(args, dict):
                        args_obj = args
                    else:
                        args_obj = {}
                    blocks.append(
                        {
                            "type": "tool_use",
                            "id": tc.get("id") or "",
                            "name": fn.get("name") or "",
                            "input": args_obj,
                        }
                    )
                return {"role": "assistant", "content": blocks}

            if role == "tool":
                data = getattr(record, "body_json", None) or {}
                tool_call_id = data.get("tool_call_id") or ""
                if "result" in data:
                    raw = data["result"]
                    content_text = (
                        json.dumps(raw, ensure_ascii=False, default=str)
                        if not isinstance(raw, str)
                        else raw
                    )
                    is_error = False
                elif "error" in data:
                    content_text = str(data["error"])
                    is_error = True
                else:
                    content_text = body or ""
                    is_error = False
                if not tool_call_id:
                    # Fallback: mensaje de texto para no romper la conversación
                    return {
                        "role": "user",
                        "content": "[tool] %s" % content_text,
                    }
                result_block = {
                    "type": "tool_result",
                    "tool_use_id": tool_call_id,
                    "content": content_text,
                }
                if is_error:
                    result_block["is_error"] = True
                return {"role": "user", "content": [result_block]}

        except Exception as err:
            _logger.warning("anthropic_format_message %s: %s", record, err)
        return None

    # ==================================================================
    # Capacidades por modelo
    # ==================================================================
    def _anthropic_supports_thinking(self, model_name):
        return bool(model_name) and bool(_ANTHROPIC_THINKING_RE.search(model_name))

    def _anthropic_supports_web_search(self, model_name):
        """Claude 3.5+ / 3.7 / 4+ soportan el tool ``web_search`` (API directa)."""
        if not model_name:
            return False
        name = model_name.lower()
        if "claude-2" in name or "claude-instant" in name:
            return False
        return "claude" in name

    # ==================================================================
    # chat()
    # ==================================================================
    def anthropic_chat(self, messages, model=None, stream=False, **kwargs):
        """Envía un chat al API de Anthropic con soporte de modos + tools."""
        model = self.get_model(model, "chat")
        model_name = (model.name or "").lower()

        # ---------- Mensajes ----------
        prepend = kwargs.get("prepend_messages") or []
        formatted = list(prepend) + self.anthropic_format_messages(messages)

        system_parts = []
        chat_messages = []
        for msg in formatted:
            if not isinstance(msg, dict) or not msg.get("role"):
                continue
            if msg["role"] == "system":
                content = msg.get("content")
                if isinstance(content, list):
                    content = "\n".join(
                        str(p.get("text") or p) for p in content if p
                    )
                system_parts.append(str(content or ""))
            elif msg["role"] in ("user", "assistant"):
                chat_messages.append(
                    {"role": msg["role"], "content": msg.get("content") or ""}
                )

        # Saneado: empareja tool_use ↔ tool_result. Anthropic devuelve 400 si
        # encuentra un ``tool_result`` huérfano o un ``tool_use`` sin su
        # correspondiente ``tool_result`` en el siguiente mensaje de usuario.
        chat_messages = self._anthropic_sanitize_history(chat_messages)

        # ---------- Modo de chat ----------
        thread = kwargs.get("llm_thread")
        work_mode = "normal"
        thinking_budget = 8192
        if thread is not None:
            try:
                work_mode = (
                    getattr(thread, "chat_work_mode", "normal") or "normal"
                )
                thinking_budget = int(
                    getattr(thread, "gemini_thinking_budget", 0) or 8192
                )
            except Exception:
                pass

        # max_tokens por defecto: 4096 (configurable por ICP). 1024 era
        # insuficiente y provocaba truncation del JSON de tool_use en
        # llamadas con argumentos grandes (p. ej. odoo_record_creator).
        icp_default_max = self.env["ir.config_parameter"].sudo().get_param(
            "llm_experience.anthropic_default_max_tokens"
        )
        try:
            base_default = int(icp_default_max) if icp_default_max else 4096
        except (TypeError, ValueError):
            base_default = 4096
        max_tokens = int(kwargs.get("max_tokens") or base_default)

        params = {
            "model": model.name,
            "messages": chat_messages or [{"role": "user", "content": ""}],
            "stream": stream,
            "max_tokens": max_tokens,
        }
        if system_parts:
            params["system"] = "\n\n".join(p for p in system_parts if p)

        # ---------- Extended Thinking ----------
        if (
            work_mode == "deep_thinking"
            and self._anthropic_supports_thinking(model_name)
        ):
            budget = max(1024, int(thinking_budget or 8192))
            if params["max_tokens"] <= budget:
                params["max_tokens"] = budget + 1024
            params["thinking"] = {"type": "enabled", "budget_tokens": budget}
            _logger.info(
                "Anthropic extended thinking: modelo=%s budget=%s max_tokens=%s",
                model.name,
                budget,
                params["max_tokens"],
            )

        # ---------- Construcción de tools ----------
        tools_list = []

        # (a) Web search server-side
        if self._anthropic_supports_web_search(model_name):
            icp = self.env["ir.config_parameter"].sudo()
            enabled = (
                icp.get_param(
                    "llm_experience.anthropic_web_search_enabled", "1"
                )
                or "1"
            ).strip().lower() not in ("0", "false", "no", "off", "")
            enabled_in_mode = (
                icp.get_param(
                    "llm_experience.anthropic_web_search_enabled_%s"
                    % work_mode,
                    "1",
                )
                or "1"
            ).strip().lower() not in ("0", "false", "no", "off", "")
            if enabled and enabled_in_mode:
                default_uses = {
                    "normal": 3,
                    "deep_thinking": 3,
                    "deep_research": 10,
                }
                max_uses = int(
                    icp.get_param(
                        "llm_experience.anthropic_web_search_max_uses_%s"
                        % work_mode
                    )
                    or icp.get_param(
                        "llm_experience.anthropic_web_search_max_uses"
                    )
                    or default_uses.get(work_mode, 3)
                )
                tool_type = (
                    icp.get_param(
                        "llm_experience.anthropic_web_search_tool_type"
                    )
                    or _ANTHROPIC_WEB_SEARCH_TOOL_TYPE
                )
                tools_list.append(
                    {
                        "type": tool_type,
                        "name": "web_search",
                        "max_uses": max(1, max_uses),
                    }
                )
                _logger.info(
                    "Anthropic web_search disponible: modelo=%s modo=%s max_uses=%s",
                    model.name,
                    work_mode,
                    max_uses,
                )

        # (b) Tools de Odoo (llm.tool)
        user_tools = kwargs.get("tools")
        if user_tools:
            try:
                formatted_user_tools = self.anthropic_format_tools(user_tools)
                if formatted_user_tools:
                    tools_list.extend(formatted_user_tools)
                    _logger.info(
                        "Anthropic: %s tools Odoo enviados al modelo %s",
                        len(formatted_user_tools),
                        model.name,
                    )
            except Exception as err:
                _logger.warning(
                    "No se pudieron formatear tools de usuario para Anthropic: %s",
                    err,
                )

        if tools_list:
            params["tools"] = tools_list

        # ---------- Prompt caching ----------
        # Marca bloques estáticos (system, tools, histórico) como
        # ``cache_control: ephemeral`` para que no cuenten contra ITPM en
        # peticiones posteriores. Es la única forma práctica de evitar
        # 429 constantes con Opus-4.
        params = self._anthropic_apply_prompt_caching(params)

        # ---------- Llamada ----------
        try:
            response = self.client.messages.create(**params)
        except Exception as err:
            # Si el SDK agotó reintentos con 429, devolvemos un mensaje
            # visible al usuario en vez de un traceback críptico.
            msg = self._anthropic_friendly_error(err)
            if msg:
                yield {"role": "assistant", "content": msg}
                return
            raise

        if not stream:
            yield from self._anthropic_emit_non_streaming(response, thread=thread)
            return

        try:
            yield from self._anthropic_emit_streaming(response, thread=thread)
        except Exception as err:
            msg = self._anthropic_friendly_error(err)
            if msg:
                yield {"role": "assistant", "content": msg}
                return
            raise

    # ==================================================================
    # Errores amigables (429 / overload / timeout)
    # ==================================================================
    def _anthropic_friendly_error(self, err):
        """Devuelve un string con explicación legible si el error del SDK
        es de tipo rate-limit / overload / timeout. De lo contrario, None
        (el caller re-lanza).
        """
        from anthropic import (
            APIStatusError,
            APIConnectionError,
            APITimeoutError,
            RateLimitError,
        )
        if isinstance(err, RateLimitError):
            # Intentamos extraer retry-after si viene
            retry_after = None
            resp = getattr(err, "response", None)
            if resp is not None:
                try:
                    retry_after = resp.headers.get("retry-after")
                except Exception:
                    retry_after = None
            extra = (
                f" (reintenta en ~{retry_after}s)" if retry_after else ""
            )
            return (
                "⚠️ **Límite de peticiones alcanzado en Anthropic (429)**%s. "
                "Opus-4 tiene un tope bajo de *input tokens per minute*. "
                "Espera unos segundos y reintenta, o prueba con "
                "`claude-sonnet-4`/`claude-haiku-4` para volumen alto. "
                "También puedes activar el caching de prompt en los "
                "parámetros del sistema (ya está activo por defecto en "
                "este módulo)." % extra
            )
        if isinstance(err, APITimeoutError):
            return (
                "⚠️ **Timeout con Anthropic**. El modelo tardó más de lo "
                "permitido. Reintenta; si persiste, reduce el tamaño del "
                "prompt o sube `llm_experience.anthropic_timeout`."
            )
        if isinstance(err, APIConnectionError):
            return (
                "⚠️ **Error de red con Anthropic**. Reintenta en unos "
                "segundos; si persiste, verifica la conexión saliente."
            )
        if isinstance(err, APIStatusError):
            status = getattr(err, "status_code", None)
            # 529 = overloaded_error (transitorio)
            if status == 529:
                return (
                    "⚠️ **Anthropic está sobrecargado (529)**. Es un "
                    "problema temporal del proveedor. Reintenta en 10-30 s."
                )
        return None

    # ==================================================================
    # Post-procesamiento de la respuesta
    # ==================================================================
    def _anthropic_usage_to_dict(self, usage):
        """Convierte el objeto ``usage`` (SDK o dict) de Anthropic al
        formato unificado que consume ``usage_apply_llm_response``.

        Anthropic devuelve:
          * ``input_tokens``: tokens nuevos de entrada (no cacheados).
          * ``cache_creation_input_tokens``: tokens escritos al caché
            efímero (se cobran ~25% más que input normal).
          * ``cache_read_input_tokens``: tokens leídos del caché (se
            cobran ~10% del precio de input).
          * ``output_tokens``: tokens generados.
        """
        if usage is None:
            return None

        def _get(obj, key):
            if isinstance(obj, dict):
                return obj.get(key)
            return getattr(obj, key, None)

        try:
            input_tokens = int(_get(usage, "input_tokens") or 0)
            cache_creation = int(_get(usage, "cache_creation_input_tokens") or 0)
            cache_read = int(_get(usage, "cache_read_input_tokens") or 0)
            output_tokens = int(_get(usage, "output_tokens") or 0)
        except (TypeError, ValueError) as err:
            _logger.debug("Anthropic usage parse: %s", err)
            return None

        # Los tokens de creación de caché se facturan como input (1.25x),
        # pero aquí los agregamos al "prompt" para reflejar el consumo
        # real. El coste en ``_usage_apply_cost_line`` se calcula con el
        # precio de ``input_usd_per_million`` (aprox. equivalente al
        # 1.25x promediado en Opus-4.x / Sonnet-4.x).
        prompt = input_tokens + cache_creation
        cached = cache_read
        total = prompt + cached + output_tokens
        if total <= 0:
            return None
        return {
            "prompt": prompt,
            "cached": cached,
            "output": output_tokens,
            "thoughts": 0,
            "total": total,
        }

    def _anthropic_apply_usage_to_thread(self, thread, usage):
        """Registra el uso de tokens/coste del turno en el ``llm.thread``.

        Tolerante a errores: no debe abortar el stream si por algún
        motivo el tracking falla (p. ej. thread readonly, rate no
        encontrada, etc.).
        """
        if thread is None:
            return
        u = self._anthropic_usage_to_dict(usage)
        if not u:
            return
        try:
            # ``usage_apply_llm_response`` es el alias genérico añadido
            # en ``llm_experience`` para no estar atados a Gemini.
            if hasattr(thread, "usage_apply_llm_response"):
                thread.usage_apply_llm_response(u)
            else:
                thread.usage_apply_gemini_response(u)
            _logger.info(
                "Anthropic usage: prompt=%s cached=%s output=%s total=%s "
                "(thread=%s)",
                u["prompt"],
                u["cached"],
                u["output"],
                u["total"],
                thread.id,
            )
        except Exception as err:
            _logger.warning(
                "Anthropic: no se pudo aplicar usage al thread %s: %s",
                getattr(thread, "id", "?"),
                err,
            )

    def _anthropic_emit_non_streaming(self, response, thread=None):
        """Extrae texto + tool_use de una respuesta completa y los emite."""
        text = ""
        tool_calls = []
        try:
            for block in response.content or []:
                btype = getattr(block, "type", None)
                if btype == "text":
                    text += getattr(block, "text", "") or ""
                elif btype == "tool_use":
                    tool_calls.append(self._anthropic_tool_use_to_tool_call(block))
        except Exception as err:
            _logger.warning("Anthropic content parse (no-stream): %s", err)

        # Registrar tokens/coste aunque no haya content (puede pasar con
        # respuestas cortas o truncadas): el usage siempre viene.
        self._anthropic_apply_usage_to_thread(
            thread, getattr(response, "usage", None)
        )

        out = {"role": "assistant"}
        if text:
            out["content"] = text
        if tool_calls:
            out["tool_calls"] = tool_calls
        yield out

    def _anthropic_tool_use_to_tool_call(self, block):
        """Convierte un bloque ``tool_use`` (SDK) al formato OpenAI-like."""
        input_obj = getattr(block, "input", None)
        if input_obj is None:
            input_obj = {}
        try:
            args_str = (
                input_obj
                if isinstance(input_obj, str)
                else json.dumps(input_obj, ensure_ascii=False, default=str)
            )
        except Exception:
            args_str = "{}"
        return {
            "id": getattr(block, "id", "") or "",
            "type": "function",
            "function": {
                "name": getattr(block, "name", "") or "",
                "arguments": args_str,
            },
        }

    def _anthropic_emit_streaming(self, response, thread=None):
        """Procesa el stream SSE de Anthropic y emite chunks uniformes.

        Eventos relevantes:
          - ``message_start``: contiene ``message.usage`` con ``input_tokens``
            y ``cache_*_input_tokens`` (inicial del turno).
          - ``content_block_start`` con ``content_block.type == "tool_use"``
            registra un tool_use (id, name).
          - ``content_block_delta`` con ``delta.type == "text_delta"`` emite texto.
          - ``content_block_delta`` con ``delta.type == "input_json_delta"``
            acumula el JSON parcial de los argumentos.
          - ``message_delta``: contiene ``usage.output_tokens`` final.
          - ``thinking_delta`` se descarta (no se muestra al usuario).
        Al terminar, emite un único chunk con ``tool_calls`` agregados y
        aplica el uso total al thread para registrar coste/tokens.
        """
        tool_uses = {}  # index -> {"id", "name", "args_json"}
        usage_totals = {
            "input_tokens": 0,
            "cache_creation_input_tokens": 0,
            "cache_read_input_tokens": 0,
            "output_tokens": 0,
        }
        try:
            for chunk in response:
                ctype = getattr(chunk, "type", None)

                if ctype == "message_start":
                    msg = getattr(chunk, "message", None)
                    usage = getattr(msg, "usage", None) if msg else None
                    if usage is not None:
                        usage_totals["input_tokens"] = int(
                            getattr(usage, "input_tokens", 0) or 0
                        )
                        usage_totals["cache_creation_input_tokens"] = int(
                            getattr(usage, "cache_creation_input_tokens", 0) or 0
                        )
                        usage_totals["cache_read_input_tokens"] = int(
                            getattr(usage, "cache_read_input_tokens", 0) or 0
                        )
                        # message_start puede traer output_tokens=1/0 inicial,
                        # lo sobreescribirá message_delta al cierre.
                        usage_totals["output_tokens"] = int(
                            getattr(usage, "output_tokens", 0) or 0
                        )
                    continue

                if ctype == "message_delta":
                    usage = getattr(chunk, "usage", None)
                    if usage is not None:
                        # ``usage.output_tokens`` en ``message_delta`` es el
                        # acumulado final de la respuesta.
                        ot = getattr(usage, "output_tokens", None)
                        if ot is not None:
                            usage_totals["output_tokens"] = int(ot or 0)
                    continue

                if ctype == "content_block_start":
                    index = getattr(chunk, "index", 0)
                    block = getattr(chunk, "content_block", None)
                    btype = getattr(block, "type", None) if block else None
                    if btype == "tool_use":
                        tool_uses[index] = {
                            "id": getattr(block, "id", "") or "",
                            "name": getattr(block, "name", "") or "",
                            "args_json": "",
                        }
                    continue

                if ctype == "content_block_delta":
                    delta = getattr(chunk, "delta", None)
                    dtype = getattr(delta, "type", None) if delta else None
                    if dtype == "text_delta":
                        text = getattr(delta, "text", "") or ""
                        if text:
                            yield {"role": "assistant", "content": text}
                    elif dtype == "input_json_delta":
                        index = getattr(chunk, "index", 0)
                        if index in tool_uses:
                            tool_uses[index]["args_json"] += (
                                getattr(delta, "partial_json", "") or ""
                            )
                    elif dtype == "thinking_delta":
                        # No emitimos el chain-of-thought al usuario.
                        continue
                    continue

                # Otros eventos (ping, content_block_stop, message_stop)
                # no necesitan emitir texto.
        except Exception as err:
            _logger.warning("Anthropic stream parse: %s", err)
            yield {"error": str(err)}
            return

        # Registrar tokens/coste al terminar el stream.
        self._anthropic_apply_usage_to_thread(thread, usage_totals)

        if tool_uses:
            tool_calls = []
            truncated_tools = []
            for idx in sorted(tool_uses.keys()):
                tu = tool_uses[idx]
                args_str = tu["args_json"] or "{}"
                repaired, ok = self._anthropic_repair_tool_args(args_str)
                if not ok:
                    _logger.warning(
                        "Anthropic: JSON de tool %s no reparable; se omite. "
                        "Original (truncado): %r",
                        tu.get("name"),
                        args_str[:300],
                    )
                    truncated_tools.append(tu.get("name") or "desconocido")
                    continue
                tool_calls.append(
                    {
                        "id": tu["id"],
                        "type": "function",
                        "function": {
                            "name": tu["name"],
                            "arguments": repaired,
                        },
                    }
                )
            if truncated_tools:
                # Si TODAS las herramientas llegaron cortadas, emitimos un
                # mensaje de texto para que el pipeline no se quede sin
                # contenido y no reintente en bucle (lo que empeora el 429).
                if not tool_calls:
                    yield {
                        "role": "assistant",
                        "content": (
                            "⚠️ La respuesta del modelo llegó cortada "
                            "(herramientas: %s). Intenta de nuevo en unos "
                            "segundos o sube `llm_experience."
                            "anthropic_default_max_tokens`." % (
                                ", ".join(truncated_tools),
                            )
                        ),
                    }
                    return
            if tool_calls:
                yield {"role": "assistant", "tool_calls": tool_calls}

    # ==================================================================
    # Reparación de JSON truncado
    # ==================================================================
    def _anthropic_repair_tool_args(self, raw):
        """Intenta devolver un JSON válido a partir de una cadena posiblemente
        truncada por el stream. Devuelve ``(texto, ok)``.

        Heurística conservadora:
          * Si ya parsea, se devuelve tal cual.
          * Si no, se cierran comillas abiertas dentro de una cadena,
            se eliminan comas sobrantes y se añaden las llaves/corchetes
            faltantes al final para equilibrar.
          * Si tras la reparación sigue sin parsear, se reporta ``ok=False``.
        """
        if raw is None:
            return "{}", True
        s = raw.strip()
        if not s:
            return "{}", True
        try:
            json.loads(s)
            return s, True
        except (ValueError, json.JSONDecodeError):
            pass

        # Analizar la cadena para saber cuántas llaves / corchetes hay abiertos
        # y si la última comilla quedó sin cerrar.
        in_string = False
        escape = False
        stack = []
        for ch in s:
            if escape:
                escape = False
                continue
            if ch == "\\" and in_string:
                escape = True
                continue
            if ch == '"':
                in_string = not in_string
                continue
            if in_string:
                continue
            if ch in "{[":
                stack.append(ch)
            elif ch in "}]":
                if stack and (
                    (ch == "}" and stack[-1] == "{")
                    or (ch == "]" and stack[-1] == "[")
                ):
                    stack.pop()

        repaired = s
        if in_string:
            repaired += '"'
        # Eliminar coma colgante antes de cerrar
        repaired_stripped = repaired.rstrip()
        if repaired_stripped.endswith(","):
            repaired = repaired_stripped[:-1]
        # Eliminar clave sin valor al final (p. ej. `,"foo":`)
        repaired = re.sub(r',\s*"[^"]*"\s*:\s*$', "", repaired)
        repaired = re.sub(r'\{\s*"[^"]*"\s*:\s*$', "{", repaired)
        # Cerrar llaves/corchetes pendientes
        for opener in reversed(stack):
            repaired += "}" if opener == "{" else "]"

        try:
            json.loads(repaired)
            _logger.info(
                "Anthropic: JSON de tool reparado (len orig=%d, final=%d).",
                len(s),
                len(repaired),
            )
            return repaired, True
        except (ValueError, json.JSONDecodeError):
            return raw, False

    # ==================================================================
    # Saneado del histórico (tool_use ↔ tool_result)
    # ==================================================================
    def _anthropic_sanitize_history(self, chat_messages):
        """Normaliza la lista para que cumpla las reglas de Anthropic:

        1. Cada ``tool_use`` de un assistant debe ir seguido por un
           ``user`` con un ``tool_result`` de mismo ``tool_use_id``.
        2. No puede haber ``tool_result`` huérfanos (sin su ``tool_use``
           declarado inmediatamente antes).
        3. El primer mensaje enviado a la API debe ser ``user``.

        Cuando detectamos desalineación (típica tras un crash o
        ``max_tokens`` insuficiente en la vuelta anterior) creamos
        ``tool_result`` sintéticos con ``is_error=True`` y descartamos
        los huérfanos.
        """
        if not chat_messages:
            return chat_messages

        out = []
        pending_ids = []  # ids de tool_use del último assistant sin responder
        orphan_ids = []   # ids descartados en esta pasada (para log resumen)
        synth_count = 0   # nº de tool_result sintéticos inyectados

        def _synth_results(ids):
            return [
                {
                    "type": "tool_result",
                    "tool_use_id": tid,
                    "content": (
                        "[Resultado no disponible: la ejecución anterior "
                        "quedó incompleta.]"
                    ),
                    "is_error": True,
                }
                for tid in ids
                if tid
            ]

        for msg in chat_messages:
            role = msg.get("role")
            content = msg.get("content")

            if role == "assistant":
                if pending_ids:
                    out.append(
                        {"role": "user", "content": _synth_results(pending_ids)}
                    )
                    pending_ids = []
                ids_here = []
                if isinstance(content, list):
                    for b in content:
                        if (
                            isinstance(b, dict)
                            and b.get("type") == "tool_use"
                            and b.get("id")
                        ):
                            ids_here.append(b["id"])
                out.append(msg)
                pending_ids = ids_here
                continue

            if role != "user":
                out.append(msg)
                continue

            # role == "user"
            if isinstance(content, list):
                has_tool_result = any(
                    isinstance(b, dict) and b.get("type") == "tool_result"
                    for b in content
                )
                kept = []
                if has_tool_result:
                    for b in content:
                        if (
                            isinstance(b, dict)
                            and b.get("type") == "tool_result"
                        ):
                            tid = b.get("tool_use_id")
                            if tid and tid in pending_ids:
                                kept.append(b)
                                pending_ids.remove(tid)
                            else:
                                orphan_ids.append(tid or "<sin id>")
                                _logger.debug(
                                    "Anthropic sanitize: descarto tool_result "
                                    "huérfano %s",
                                    tid,
                                )
                        else:
                            kept.append(b)
                    # Añadir synth para pending_ids no cubiertos por este user
                    if pending_ids:
                        kept = _synth_results(pending_ids) + kept
                        synth_count += len(pending_ids)
                        pending_ids = []
                    if not kept:
                        # Anthropic rechaza text blocks vacíos.
                        kept = [{"type": "text", "text": "(sin contenido)"}]
                    out.append({"role": "user", "content": kept})
                else:
                    # User normal (texto o lista sin tool_results):
                    # cerrar antes cualquier tool_use pendiente.
                    if pending_ids:
                        out.append(
                            {
                                "role": "user",
                                "content": _synth_results(pending_ids),
                            }
                        )
                        synth_count += len(pending_ids)
                        pending_ids = []
                    out.append(msg)
            else:
                # string content
                if pending_ids:
                    out.append(
                        {"role": "user", "content": _synth_results(pending_ids)}
                    )
                    synth_count += len(pending_ids)
                    pending_ids = []
                out.append(msg)

        # Si al final queda un assistant con tool_use sin respuesta
        # (raro pero posible si el usuario borró mensajes), añadir synth.
        if pending_ids:
            out.append(
                {"role": "user", "content": _synth_results(pending_ids)}
            )
            synth_count += len(pending_ids)

        if orphan_ids or synth_count:
            _logger.info(
                "Anthropic sanitize: %s tool_result huérfano(s) descartado(s)"
                "%s, %s tool_result sintético(s) insertado(s).",
                len(orphan_ids),
                " (%s)" % ", ".join(orphan_ids[:5]) if orphan_ids else "",
                synth_count,
            )

        # Anthropic exige que el primer mensaje sea de usuario.
        # ⚠️ Si descartamos un ``assistant`` inicial que tenía ``tool_use``,
        # los ``tool_result`` que respondían a esos ``tool_use`` quedan
        # huérfanos en el siguiente mensaje user → 400. Limpiamos esos
        # huérfanos a la vez que hacemos el pop.
        #
        # 🛟 Para no perder contexto: si el assistant descartado tenía
        # texto narrativo, lo conservamos convirtiéndolo en un mensaje
        # ``user`` con un prefijo aclaratorio. Solo se pierden los
        # ``tool_use`` (que ya no se pueden responder).
        dropped_tool_use_ids = set()
        preserved_text_chunks = []
        while out and out[0].get("role") != "user":
            dropped = out.pop(0)
            content = dropped.get("content")
            if isinstance(content, list):
                for b in content:
                    if not isinstance(b, dict):
                        continue
                    btype = b.get("type")
                    if btype == "tool_use" and b.get("id"):
                        dropped_tool_use_ids.add(b["id"])
                    elif btype == "text":
                        txt = (b.get("text") or "").strip()
                        if txt:
                            preserved_text_chunks.append(txt)
            elif isinstance(content, str) and content.strip():
                preserved_text_chunks.append(content.strip())
            _logger.info(
                "Anthropic sanitize: descarto mensaje inicial rol=%s "
                "(texto preservado=%s, tool_use perdidos=%s)",
                dropped.get("role"),
                bool(preserved_text_chunks),
                len(dropped_tool_use_ids),
            )

        # Si rescatamos texto del assistant inicial descartado, lo
        # inyectamos como un mensaje user al frente para preservar el
        # contexto narrativo (no las tool calls, que ya no son válidas).
        if preserved_text_chunks:
            preserved_text = "\n\n".join(preserved_text_chunks)
            out.insert(
                0,
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": (
                                "[Contexto previo del asistente, recuperado "
                                "tras una interrupción técnica]\n\n%s"
                            )
                            % preserved_text,
                        }
                    ],
                },
            )

        # Si el (nuevo) primer mensaje es user con tool_results y alguno
        # de sus tool_use_id ya no existe en el historial restante,
        # tenemos que descartarlos: ya no hay un ``tool_use`` previo al
        # que respondan. Aplicamos esta limpieza a TODOS los mensajes
        # (no solo al primero) para protegernos también de otros saltos.
        valid_tool_use_ids = set()
        for m in out:
            if m.get("role") == "assistant" and isinstance(m.get("content"), list):
                for b in m["content"]:
                    if (
                        isinstance(b, dict)
                        and b.get("type") == "tool_use"
                        and b.get("id")
                    ):
                        valid_tool_use_ids.add(b["id"])

        cleaned_out = []
        cleaned_orphans = 0
        for idx, m in enumerate(out):
            if m.get("role") != "user" or not isinstance(m.get("content"), list):
                cleaned_out.append(m)
                continue
            new_content = []
            for b in m["content"]:
                if (
                    isinstance(b, dict)
                    and b.get("type") == "tool_result"
                ):
                    tid = b.get("tool_use_id")
                    # Solo conservamos tool_results cuyo tool_use_id
                    # esté declarado por algún assistant que ESTÁ en out
                    # *antes* de este mensaje user.
                    prev_ids = set()
                    for prev in out[:idx]:
                        if prev.get("role") == "assistant" and isinstance(
                            prev.get("content"), list
                        ):
                            for pb in prev["content"]:
                                if (
                                    isinstance(pb, dict)
                                    and pb.get("type") == "tool_use"
                                    and pb.get("id")
                                ):
                                    prev_ids.add(pb["id"])
                    if tid and tid in prev_ids:
                        new_content.append(b)
                    else:
                        cleaned_orphans += 1
                        _logger.debug(
                            "Anthropic sanitize: descarto tool_result post-pop "
                            "huérfano %s",
                            tid,
                        )
                else:
                    new_content.append(b)
            if not new_content:
                # Reemplazamos por un mensaje neutro: indica al modelo que
                # reanude la conversación tras una interrupción.
                new_content = [
                    {
                        "type": "text",
                        "text": (
                            "[Conversación reanudada tras una interrupción "
                            "técnica; continúa con la pregunta original.]"
                        ),
                    }
                ]
            cleaned_out.append({**m, "content": new_content})

        if cleaned_orphans:
            _logger.info(
                "Anthropic sanitize: limpieza post-pop eliminó %s "
                "tool_result(s) huérfano(s) por tool_use descartado.",
                cleaned_orphans,
            )

        # Pase final: eliminar bloques text vacíos (Anthropic los rechaza) y
        # asegurar que ningún `content` quede vacío.
        return [self._anthropic_normalize_content(m) for m in cleaned_out]

    def _anthropic_normalize_content(self, msg):
        """Garantiza que ``content`` no esté vacío ni contenga text blocks
        con texto en blanco. Anthropic responde 400 si encuentra
        ``{"type":"text","text":""}``.
        """
        role = msg.get("role")
        content = msg.get("content")
        placeholder = "(sin contenido)"

        if isinstance(content, list):
            cleaned = []
            for b in content:
                if not isinstance(b, dict):
                    cleaned.append(b)
                    continue
                if b.get("type") == "text":
                    txt = b.get("text")
                    if isinstance(txt, str) and txt.strip():
                        cleaned.append(b)
                    # else: descartar bloque vacío
                elif b.get("type") == "tool_result":
                    # tool_result también requiere content no vacío
                    rc = b.get("content")
                    if isinstance(rc, str) and not rc.strip():
                        b = {**b, "content": placeholder}
                    cleaned.append(b)
                else:
                    cleaned.append(b)
            if not cleaned:
                cleaned = [{"type": "text", "text": placeholder}]
            return {"role": role, "content": cleaned}

        if isinstance(content, str):
            if not content.strip():
                return {"role": role, "content": placeholder}
            return msg

        if content is None:
            return {"role": role, "content": placeholder}

        return msg
