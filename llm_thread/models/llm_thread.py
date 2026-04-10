import contextlib
import html as _html_lib
import json
import logging
import re

import emoji
import markdown2

# Detecta bloques ```echarts ... ``` en el texto del LLM (JSON en una o varias líneas)
_ECHARTS_BLOCK_RE = re.compile(r"```echarts\n(.*?)\n```", re.DOTALL)

from odoo import _, api, fields, models
from odoo.addons.base.models.ir_model import MODULE_UNINSTALL_FLAG
from odoo.exceptions import UserError
from psycopg2 import OperationalError

_logger = logging.getLogger(__name__)





class RelatedRecordProxy:
    """
    A proxy object that provides clean access to related record fields in Jinja templates.
    Usage in templates: {{ related_record.get_field('field_name', 'default_value') }}
    When called directly, returns JSON with model name, id, and display name.
    """

    def __init__(self, record):
        self._record = record

    def get_field(self, field_name, default=""):
        """
        Get a field value from the related record.

        Args:
            field_name (str): The field name to access
            default: Default value if field doesn't exist or is empty

        Returns:
            The field value, or default if not available
        """
        if not self._record:
            return default

        try:
            if hasattr(self._record, field_name):
                value = getattr(self._record, field_name)

                # Handle different field types
                if value is None:
                    return default
                elif isinstance(value, bool):
                    return value  # Keep as boolean for Jinja
                elif hasattr(value, "name"):  # Many2one field
                    return value.name
                elif hasattr(value, "mapped"):  # Many2many/One2many field
                    return value.mapped("name")
                else:
                    return value
            else:
                _logger.debug(
                    "Field '%s' not found on record %s", field_name, self._record
                )
                return default

        except Exception as e:
            _logger.error(
                "Error getting field '%s' from record: %s", field_name, str(e)
            )
            return default

    def __getattr__(self, name):
        """Allow direct attribute access as fallback"""
        return self.get_field(name)

    def __bool__(self):
        """Return True if we have a record"""
        return bool(self._record)

    def __str__(self):
        """When called by itself, return JSON of model name, id, and display name"""
        if not self._record:
            return json.dumps({"model": None, "id": None, "display_name": None})

        return json.dumps(
            {
                "model": self._record._name,
                "id": self._record.id,
                "display_name": getattr(
                    self._record, "display_name", str(self._record)
                ),
            }
        )

    def __repr__(self):
        """Same as __str__ for consistency"""
        return self.__str__()


class LLMThread(models.Model):
    _name = "llm.thread"
    _description = "LLM Chat Thread"
    _inherit = ["mail.thread"]
    _order = "write_date DESC"

    name = fields.Char(
        string="Title",
        required=True,
    )
    user_id = fields.Many2one(
        "res.users",
        string="User",
        default=lambda self: self.env.user,
        required=True,
        ondelete="restrict",
    )
    provider_id = fields.Many2one(
        "llm.provider",
        string="Provider",
        required=True,
        ondelete="restrict",
    )
    model_id = fields.Many2one(
        "llm.model",
        string="Model",
        required=True,
        domain="[('provider_id', '=', provider_id), ('model_use', 'in', ['chat', 'multimodal'])]",
        ondelete="restrict",
    )
    active = fields.Boolean(default=True)

    # Updated fields for related record reference
    model = fields.Char(
        string="Related Document Model", help="Technical name of the related model"
    )
    res_id = fields.Many2oneReference(
        string="Related Document ID",
        model_field="model",
        help="ID of the related record",
    )



    tool_ids = fields.Many2many(
        "llm.tool",
        string="Available Tools",
        help="Tools that can be used by the LLM in this thread",
    )
    
    attachment_ids = fields.Many2many(
        'ir.attachment',
        string='All Thread Attachments',
        compute='_compute_attachment_ids',
        store=True,
        help='All attachments from all messages in this thread'
    )
    
    attachment_count = fields.Integer(
        string='Attachment Count',
        compute='_compute_attachment_count',
        store=True,
        help='Total number of attachments in this thread'
    )

    title_auto_generated = fields.Boolean(
        string="Título autogenerado",
        default=False,
        help="Si está activo, el título puede actualizarse automáticamente con el primer mensaje.",
    )

    chat_window_id = fields.Integer(
        string="ID ventana de chat (llm.chat.window)",
        index=True,
        help="Si el módulo llm_chat_window está instalado, referencia la ventana preconfigurada.",
    )
    hide_thread_settings = fields.Boolean(
        string="Ocultar ajustes de cabecera",
        default=False,
    )

    @api.model_create_multi
    def create(self, vals_list):
        """Set default title if not provided"""
        needs_unique_name = []

        for vals in vals_list:
            # Herramientas marcadas como default en llm.tool (si no vienen ya en vals)
            if not vals.get("tool_ids"):
                default_tools = self.env["llm.tool"].search(
                    [("active", "=", True), ("default", "=", True)]
                )
                if default_tools:
                    vals["tool_ids"] = [(6, 0, default_tools.ids)]

            if not vals.get("name"):
                # If linked to a record, use its display name
                if vals.get("model") and vals.get("res_id"):
                    try:
                        record = self.env[vals["model"]].browse(vals["res_id"])
                        if record.exists():
                            vals["name"] = f"AI Chat - {record.display_name}"
                        else:
                            # Record doesn't exist, use technical format
                            vals["name"] = f"AI Chat - {vals['model']}#{vals['res_id']}"
                    except Exception:
                        # Model doesn't exist or access error, use technical format
                        vals["name"] = f"AI Chat - {vals['model']}#{vals['res_id']}"
                else:
                    # Generic name - will add unique ID after creation
                    vals["name"] = "New Chat"
                    needs_unique_name.append(True)
            else:
                needs_unique_name.append(False)

        records = super().create(vals_list)

        # Update generic thread names to include unique ID y marcar título como autogenerable
        for record, needs_update in zip(records, needs_unique_name):
            if needs_update:
                record.write(
                    {
                        "name": f"New Chat #{record.id}",
                        "title_auto_generated": True,
                    }
                )

        return records

    def write(self, vals):
        """Si el usuario renombra a un título no genérico, bloquear futuros reemplazos automáticos."""
        if vals.get("name") is not None:
            name = str(vals["name"]).strip() if vals.get("name") else ""
            if name and not self._thread_name_is_generic_placeholder(name):
                if "title_auto_generated" not in vals:
                    vals["title_auto_generated"] = False
        return super().write(vals)

    @api.depends('message_ids.attachment_ids')
    def _compute_attachment_ids(self):
        """Compute all attachments from all messages in this thread."""
        for thread in self:
            # Get all attachments from all messages in this thread
            all_attachments = thread.message_ids.mapped('attachment_ids')
            thread.attachment_ids = [(6, 0, all_attachments.ids)]
    
    @api.depends('attachment_ids')
    def _compute_attachment_count(self):
        """Compute the total number of attachments in this thread."""
        for thread in self:
            thread.attachment_count = len(thread.attachment_ids)

    # ============================================================================
    # MESSAGE POST OVERRIDES - Clean integration with mail.thread
    # ============================================================================

    @api.returns("mail.message", lambda value: value.id)
    def message_post(self, *, llm_role=None, message_type="comment", **kwargs):
        """Override to handle LLM-specific message types and metadata.

        Args:
            llm_role (str): The LLM role ('user', 'assistant', 'tool', 'system')
                           If provided, will automatically set the appropriate subtype
        """

        # Convert LLM role to subtype_xmlid if provided
        if llm_role:
            _, role_to_id = self.env["mail.message"].get_llm_roles()
            if llm_role in role_to_id:
                # Get the xmlid from the role
                subtype_xmlid = f"llm.mt_{llm_role}"
                kwargs["subtype_xmlid"] = subtype_xmlid

        # Handle LLM-specific subtypes and email_from generation
        if not kwargs.get("author_id") and not kwargs.get("email_from"):
            kwargs["email_from"] = self._get_llm_email_from(
                kwargs.get("subtype_xmlid"), kwargs.get("author_id"), llm_role
            )

        # Convert markdown to HTML if needed (except for tool messages which use body_json)
        if kwargs.get("body") and llm_role != "tool":
            kwargs["body"] = self._process_llm_body(kwargs["body"])

        # Create the message using standard mail.thread flow
        return super().message_post(message_type=message_type, **kwargs)

    def _get_llm_email_from(self, subtype_xmlid, author_id, llm_role=None):
        """Generate appropriate email_from for LLM messages (texto legible, sin nombres técnicos)."""
        if author_id:
            return None  # Let standard flow handle it

        company_name = "Odoo"

        if subtype_xmlid == "llm.mt_tool" or llm_role == "tool":
            # Nombre genérico para mensajes de herramienta
            label = _("Herramientas")
            return label if not company_name else f"{company_name} · {label}"

        if subtype_xmlid == "llm.mt_assistant" or llm_role == "assistant":
            return f"{company_name} AI".strip() if company_name else "AI"

        if subtype_xmlid == "llm.mt_system" or llm_role == "system":
            return f"{company_name} AI".strip() if company_name else "AI"

        return None

    def _process_llm_body(self, body):
        """Process body content for LLM messages (markdown to HTML conversion).

        Los bloques ```echarts se interceptan ANTES de markdown2 porque markdown2
        no preserva el nombre del lenguaje en la clase del elemento <code>.
        Se convierten a <div class="o_llm_echarts_raw"> con el JSON como texto
        (HTML-escapado) para sobrevivir tanto markdown2 como el sanitizador de Odoo.
        """
        if not body:
            return body

        def _echarts_to_div(m):
            json_content = m.group(1).strip()
            # html.escape convierte " → &quot; etc.; textContent en JS los restaura
            safe_json = _html_lib.escape(json_content)
            return f'\n<div class="o_llm_echarts_raw">{safe_json}</div>\n'

        body = _ECHARTS_BLOCK_RE.sub(_echarts_to_div, body)

        # :bar_chart:, :white_check_mark:, etc. → Unicode (mejor presentación en el chat)
        body = emoji.emojize(str(body), language="alias")

        return markdown2.markdown(
            body,
            extras=["tables", "fenced-code-blocks", "break-on-newline"],
        )

    # ============================================================================
    # STREAMING MESSAGE CREATION
    # ============================================================================

    def message_post_from_stream(
        self, stream, llm_role, placeholder_text="…", **kwargs
    ):
        """Create and update a message from a streaming response.

        Args:
            stream: Generator yielding chunks of response data
            llm_role (str): The LLM role ('user', 'assistant', 'tool', 'system')
            placeholder_text (str): Text to show while streaming

        Returns:
            message: The created/updated message record
        """
        message = None
        accumulated_content = ""

        for chunk in stream:
            # Initialize message on first content
            if message is None and chunk.get("content"):
                message = self.message_post(
                    body=placeholder_text, llm_role=llm_role, author_id=False, **kwargs
                )
                yield {"type": "message_create", "message": message.message_format()[0]}

            # Handle content streaming
            if chunk.get("content"):
                accumulated_content += chunk["content"]
                message.write({"body": self._process_llm_body(accumulated_content)})
                yield {"type": "message_chunk", "message": message.message_format()[0]}

            # Handle errors
            if chunk.get("error"):
                yield {"type": "error", "error": chunk["error"]}
                return message

        # Final update for assistant message
        if message and accumulated_content:
            message.write({"body": self._process_llm_body(accumulated_content)})
            yield {"type": "message_update", "message": message.message_format()[0]}

        return message

    # ============================================================================
    # GENERATION FLOW - Refactored to use message_post with roles
    # ============================================================================

    @api.model
    def _thread_name_is_generic_placeholder(self, name):
        """Nombres que el cliente envía como placeholder (EN/ES) o el formato estándar New Chat #id."""
        if name is None:
            return True
        stripped = str(name).strip()
        if not stripped:
            return True
        if re.match(r"^New Chat #\d+$", stripped, re.IGNORECASE):
            return True
        # create() / JS envían "Nuevo chat", "New chat", etc.; deben poder renombrarse por IA
        if stripped.lower() in {"nuevo chat", "new chat"}:
            return True
        return False

    def _is_default_thread_title(self):
        """True si el nombre sigue siendo placeholder y puede sustituirse (IA o primer mensaje)."""
        self.ensure_one()
        return self._thread_name_is_generic_placeholder(self.name)

    def _apply_auto_title_from_first_user_message(self, text, attachment_ids=None):
        """Genera un título corto a partir del primer mensaje o nombres de adjuntos."""
        self.ensure_one()
        if not self._is_default_thread_title():
            return
        attachment_ids = attachment_ids or []
        raw = (text or "").strip().replace("\n", " ").replace("\r", " ")
        if not raw and attachment_ids:
            atts = self.env["ir.attachment"].browse([int(x) for x in attachment_ids])
            raw = ", ".join(atts.mapped("name")) or "Adjuntos"
        if not raw:
            return
        max_len = 60
        title = raw if len(raw) <= max_len else raw[: max_len - 1].rstrip() + "…"
        self.write({"name": title, "title_auto_generated": True})

    def generate(self, user_message_body, **kwargs):
        """Main generation method with PostgreSQL advisory locking."""
        self.ensure_one()

        attachment_ids = kwargs.pop("attachment_ids", None)

        with self._generation_lock():
            last_message = False
            # Post user message if provided (texto y/o adjuntos)
            if user_message_body or attachment_ids:
                post_kwargs = dict(kwargs)
                if attachment_ids:
                    # message_post espera list[int], no comandos M2M [(6, 0, ...)].
                    post_kwargs["attachment_ids"] = [int(x) for x in attachment_ids]

                last_message = self.message_post(
                    body=user_message_body or "",
                    llm_role="user",
                    author_id=self.env.user.partner_id.id,
                    **post_kwargs,
                )
                yield {
                    "type": "message_create",
                    "message": last_message.message_format()[0],
                }

            # Call the actual generation implementation
            last_message = yield from self.generate_messages(last_message)
            self._maybe_generate_thread_title()

            # Notificar al frontend del nombre actualizado DENTRO de la transacción,
            # antes de que el cursor haga commit.  Si se esperara al refreshThread del
            # evento 'done', la DB aún no habría commiteado y el cliente vería el
            # nombre anterior.
            yield {
                "type": "thread_name_update",
                "thread_id": self.id,
                "name": self.name,
            }

            return last_message

    def generate_messages(self, last_message=None):
        """Generate messages - to be overridden by llm_assistant module."""
        raise UserError(
            _("Please install the llm_assistant module for actual AI generation.")
        )

    def _maybe_generate_thread_title(self):
        """Hook tras un turno de generación (p. ej. título con IA). Las extensiones lo sobrescriben."""
        return

    def get_context(self, base_context=None):
        context = {
            **(base_context or {}),
            "thread_id": self.id,
        }

        try:
            related_record = self.env[self.model].browse(self.res_id)
            if related_record:
                context["related_record"] = RelatedRecordProxy(related_record)
                context["related_model"] = self.model
                context["related_res_id"] = self.res_id
            else:
                context["related_record"] = None
                context["related_model"] = None
                context["related_res_id"] = None
        except Exception as e:
            _logger.warning(
                "Error accessing related record %s,%s: %s", self.model, self.res_id, e
            )

        return context

    # ============================================================================
    # POSTGRESQL ADVISORY LOCK IMPLEMENTATION
    # ============================================================================

    def _acquire_thread_lock(self):
        """Acquire PostgreSQL advisory lock for this thread."""
        self.ensure_one()

        try:
            query = "SELECT pg_try_advisory_lock(%s)"
            self.env.cr.execute(query, (self.id,))
            result = self.env.cr.fetchone()

            if not result or not result[0]:
                raise UserError(
                    _("Thread is currently generating a response. Please wait.")
                )

            _logger.info(f"Acquired advisory lock for thread {self.id}")

        except UserError:
            raise
        except OperationalError as e:
            _logger.error(f"Database error acquiring lock for thread {self.id}: {e}")
            raise UserError(_("Database error acquiring thread lock.")) from e
        except Exception as e:
            _logger.error(f"Unexpected error acquiring lock for thread {self.id}: {e}")
            raise UserError(_("Failed to acquire thread lock.")) from e

    def _release_thread_lock(self):
        """Release PostgreSQL advisory lock for this thread."""
        self.ensure_one()

        try:
            query = "SELECT pg_advisory_unlock(%s)"
            self.env.cr.execute(query, (self.id,))
            result = self.env.cr.fetchone()

            success = result and result[0]
            if success:
                _logger.info(f"Released advisory lock for thread {self.id}")
            else:
                _logger.warning(f"Advisory lock for thread {self.id} was not held")

            return success

        except Exception as e:
            _logger.error(f"Error releasing lock for thread {self.id}: {e}")
            return False

    @contextlib.contextmanager
    def _generation_lock(self):
        """Context manager for thread generation with automatic lock cleanup."""
        self.ensure_one()

        self._acquire_thread_lock()

        try:
            _logger.info(f"Starting locked generation for thread {self.id}")
            yield self

        finally:
            released = self._release_thread_lock()
            if released:
                _logger.info(f"Finished locked generation for thread {self.id}")
            else:
                _logger.warning(f"Lock release failed for thread {self.id}")


    # ============================================================================
    # ODOO HOOKS AND CLEANUP
    # ============================================================================

    def unlink(self):
        # Equivalente a @api.ondelete(at_uninstall=False) en Odoo 16+: no notificar bus al desinstalar módulo.
        if not self.env.context.get(MODULE_UNINSTALL_FLAG):
            unlink_ids = [record.id for record in self]
            self.env["bus.bus"].sendone(
                (self._cr.dbname, "res.partner", self.env.user.partner_id.id),
                {"type": "llm.thread/delete", "ids": unlink_ids},
            )
        return super().unlink()
