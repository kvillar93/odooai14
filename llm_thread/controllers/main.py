import json
import logging

from werkzeug.exceptions import BadRequest

from odoo import _, api, http, registry
from odoo.exceptions import MissingError
from odoo.http import Response, request

_logger = logging.getLogger(__name__)


class LLMThreadController(http.Controller):
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
    def _llm_thread_generate(cls, dbname, env, thread_id, user_message_body, **kwargs):
        """Generate LLM responses with streaming and safe yielding."""
        with registry(dbname).cursor() as cr:
            env = api.Environment(cr, env.uid, env.context)
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
                    f"Error in llm_thread_generate for thread {thread_id}: {e}"
                )
                # Lock will be automatically released by context manager

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
            raw = request.httprequest.get_data(cache=False, as_text=True) or ""
            if not raw.strip():
                raise BadRequest(
                    _("Cuerpo JSON vacío. Incluya message y/o attachment_ids.")
                )
            try:
                payload = json.loads(raw)
            except json.JSONDecodeError as err:
                raise BadRequest(_("JSON inválido: %s") % err) from err
            user_message_body = payload.get("message", user_message_body)
            att = payload.get("attachment_ids")
            if att:
                if not isinstance(att, list):
                    raise BadRequest(_("attachment_ids debe ser una lista."))
                extra_kwargs["attachment_ids"] = [
                    int(x) for x in att if str(x).isdigit() or isinstance(x, int)
                ]
        return Response(
            self._llm_thread_generate(
                request.cr.dbname,
                request.env,
                thread_id,
                user_message_body,
                **extra_kwargs,
            ),
            direct_passthrough=True,
            headers=headers,
        )
