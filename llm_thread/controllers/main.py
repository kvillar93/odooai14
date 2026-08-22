import json
import logging

from werkzeug.exceptions import BadRequest

from odoo import _, api, http, registry
from odoo.exceptions import MissingError
from odoo.http import Response, request

_logger = logging.getLogger(__name__)


class LLMThreadController(http.Controller):
    @staticmethod
    def _coerce_attachment_ids(att):
        """Normaliza attachment_ids desde JSON, form-urlencoded o lista."""
        if not att:
            return []
        if isinstance(att, str):
            raw = att.strip()
            if not raw:
                return []
            try:
                att = json.loads(raw)
            except json.JSONDecodeError:
                att = [part.strip() for part in raw.split(",") if part.strip()]
        if not isinstance(att, list):
            raise BadRequest(_("attachment_ids debe ser una lista."))
        return [
            int(x) for x in att if str(x).isdigit() or isinstance(x, int)
        ]

    @classmethod
    def _parse_generate_post(cls, user_message_body):
        """Lee message y adjuntos del POST.

        En Odoo 14, ``Content-Type: application/json`` convierte la petición
        en JsonRequest y choca con esta ruta ``type='http'``. El cliente debe
        enviar ``application/x-www-form-urlencoded``; se acepta JSON solo como
        compatibilidad si el dispatcher HTTP llega a ejecutarse.
        """
        extra_kwargs = {}
        httprequest = request.httprequest
        mimetype = (httprequest.mimetype or "").split(";")[0].strip().lower()
        if mimetype in ("application/json", "application/json-rpc"):
            raw = httprequest.get_data(cache=False, as_text=True) or ""
            if not raw.strip():
                raise BadRequest(
                    _("Cuerpo JSON vacío. Incluya message y/o attachment_ids.")
                )
            try:
                payload = json.loads(raw)
            except json.JSONDecodeError as err:
                raise BadRequest(_("JSON inválido: %s") % err) from err
            user_message_body = payload.get("message", user_message_body)
            att_ids = cls._coerce_attachment_ids(payload.get("attachment_ids"))
        else:
            params = request.params or {}
            if "message" in params:
                user_message_body = params.get("message") or user_message_body
            att_ids = cls._coerce_attachment_ids(params.get("attachment_ids"))
        if att_ids:
            extra_kwargs["attachment_ids"] = att_ids
        return user_message_body, extra_kwargs

    @http.route(
        "/llm/thread/<int:thread_id>/update",
        type="json",
        auth="user",
        methods=["POST"],
        csrf=True,
    )
    def llm_thread_update(self, thread_id, **kwargs):
        try:
            thread = request.env["llm.thread"].browse(thread_id)
            if not thread.exists():
                raise MissingError(_("LLM Thread not found."))
            thread.write(kwargs)
            return {"status": "success"}
        except Exception as e:
            return {"status": "error", "error": str(e)}

    @staticmethod
    def _safe_yield(data_to_yield):
        """Helper generator to yield data safely, handling BrokenPipeError(Disconnected user)."""
        try:
            yield data_to_yield
            return True
        except BrokenPipeError:
            return False
        except Exception:
            return False

    @classmethod
    def _llm_thread_generate(cls, dbname, uid, context, thread_id, user_message_body, **kwargs):
        """Generate LLM responses with streaming and safe yielding."""
        with api.Environment.manage():
            with registry(dbname).cursor() as cr:
                env = api.Environment(cr, uid, context)
                llm_thread = env["llm.thread"].browse(int(thread_id))
                if not llm_thread.exists():
                    yield from cls._safe_yield(
                        f"data: {json.dumps({'type': 'error', 'error': 'LLM Thread not found.'})}\n\n".encode()
                    )
                    return

                client_connected = True
                try:
                    for response in llm_thread.generate(user_message_body, **kwargs):
                        json_data = json.dumps(response, default=str)
                        success = yield from cls._safe_yield(
                            f"data: {json_data}\n\n".encode()
                        )
                        if not success:
                            client_connected = False
                            break

                except GeneratorExit:
                    client_connected = False

                except Exception as e:
                    _logger.exception(
                        "Error in llm_thread_generate for thread %s: %s",
                        thread_id, e,
                    )
                    if client_connected:
                        success = yield from cls._safe_yield(
                            f"data: {json.dumps({'type': 'error', 'error': str(e)})}\n\n".encode()
                        )
                        if not success:
                            client_connected = False

                finally:
                    if client_connected:
                        yield from cls._safe_yield(
                            f"data: {json.dumps({'type': 'done'})}\n\n".encode()
                        )

    @http.route(
        "/llm/thread/generate",
        type="http",
        auth="user",
        methods=["GET", "POST"],
        csrf=True,
    )
    def llm_thread_generate(self, thread_id, message=None, **kwargs):
        headers = {
            "Content-Type": "text/event-stream",
            "Cache-Control": "no-cache",
            "X-Accel-Buffering": "no",  # Disable nginx buffering
        }
        user_message_body = message
        extra_kwargs = {}
        if request.httprequest.method == "POST":
            user_message_body, extra_kwargs = self._parse_generate_post(
                user_message_body
            )
        return Response(
            self._llm_thread_generate(
                request.cr.dbname,
                request.env.uid,
                dict(request.env.context),
                thread_id,
                user_message_body,
                **extra_kwargs,
            ),
            direct_passthrough=True,
            headers=headers,
        )
