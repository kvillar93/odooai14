import json
import logging

from odoo import models, tools

_logger = logging.getLogger(__name__)

_IMAGE_MIMES = ("image/png", "image/jpeg", "image/jpg", "image/gif", "image/webp")


class MailMessage(models.Model):
    _inherit = "mail.message"

    def _openai_user_content_parts(self, body_text):
        """Construye content multimodal (texto + imágenes) para mensajes usuario."""
        self.ensure_one()
        parts = []
        if body_text:
            parts.append({"type": "text", "text": body_text})
        for att in self.attachment_ids.sorted("id"):
            mimetype = (att.mimetype or "").lower()
            if mimetype in _IMAGE_MIMES or (
                mimetype.startswith("image/") and att.datas
            ):
                try:
                    raw_b64 = att.datas
                    if isinstance(raw_b64, bytes):
                        raw_b64 = raw_b64.decode()
                    # datas ya está en base64 en ir.attachment
                    data_uri = f"data:{mimetype or 'image/png'};base64,{raw_b64}"
                    parts.append(
                        {
                            "type": "image_url",
                            "image_url": {"url": data_uri},
                        }
                    )
                except Exception as err:
                    _logger.warning(
                        "No se pudo incluir adjunto imagen %s en el mensaje LLM: %s",
                        att.id,
                        err,
                    )
                    parts.append(
                        {
                            "type": "text",
                            "text": f"[Adjunto imagen omitido: {att.name}]",
                        }
                    )
            else:
                extracted = att.sudo().llm_extract_text()
                if extracted and extracted.strip():
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
                        f'{att.name} ({mimetype or "sin tipo"}, {att.file_size or 0} bytes)'
                    )
                    parts.append(
                        {
                            "type": "text",
                            "text": (
                                "[Archivo adjunto sin texto extraíble automáticamente "
                                "(instale «pypdf» para PDF, o use texto/imagen): "
                                f"{meta}]"
                            ),
                        }
                    )
        return parts

    def openai_format_message(self):
        """Provider-specific formatting for OpenAI."""
        self.ensure_one()
        body = self.body
        if body:
            body = tools.html2plaintext(body)

        if self.is_llm_user_message()[self]:
            formatted_message = {"role": "user"}
            parts = self._openai_user_content_parts(body)
            if len(parts) == 1 and parts[0].get("type") == "text":
                formatted_message["content"] = parts[0]["text"]
            elif parts:
                formatted_message["content"] = parts
            else:
                formatted_message["content"] = ""
            return formatted_message

        elif self.is_llm_assistant_message()[self]:
            formatted_message = {"role": "assistant"}

            formatted_message["content"] = body

            # Add tool calls if present in body_json
            tool_calls = self.get_tool_calls()
            if tool_calls:
                formatted_message["tool_calls"] = [
                    {
                        "id": tc["id"],
                        "type": tc.get("type", "function"),
                        "function": {
                            "name": tc["function"]["name"],
                            "arguments": tc["function"]["arguments"],
                        },
                    }
                    for tc in tool_calls
                ]

            return formatted_message

        elif self.is_llm_tool_message()[self]:
            tool_data = self.body_json
            if not tool_data:
                _logger.warning(
                    f"OpenAI Format: Skipping tool message {self.id}: no tool data found."
                )
                return None

            tool_call_id = tool_data.get("tool_call_id")
            if not tool_call_id:
                _logger.warning(
                    f"OpenAI Format: Skipping tool message {self.id}: missing tool_call_id."
                )
                return None

            # Get result content
            if "result" in tool_data:
                content = json.dumps(tool_data["result"])
            elif "error" in tool_data:
                content = json.dumps({"error": tool_data["error"]})
            else:
                content = ""

            formatted_message = {
                "role": "tool",
                "tool_call_id": tool_call_id,
                "content": content,
            }
            return formatted_message
        else:
            return None
