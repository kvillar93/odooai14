# -*- coding: utf-8 -*-
from odoo import _, fields, models


class LlmAssistant(models.Model):
    """Añade control de acceso por usuario específico.

    Si un asistente tiene ``allowed_user_ids`` con al menos un usuario,
    SOLO esos usuarios podrán verlo (aunque pertenezcan a grupos que
    tengan acceso al asistente por ``allowed_group_ids``). Si el campo
    queda vacío, se mantiene el comportamiento original basado en
    ``is_public`` / ``allowed_group_ids``.
    """

    _inherit = "llm.assistant"

    allowed_user_ids = fields.Many2many(
        "res.users",
        "llm_assistant_user_rel",
        "assistant_id",
        "user_id",
        string="Usuarios permitidos",
        help=(
            "Si se seleccionan usuarios, este asistente SOLO será "
            "visible para ellos (prevalece sobre 'Público' y "
            "'Grupos permitidos'). Si se deja vacío, se aplica el "
            "control habitual por grupos."
        ),
    )

    def _get_allowed_assistants_for_user(self, user=None):
        """Filtra, adicionalmente, por ``allowed_user_ids``.

        * Asistentes con usuarios explícitos → solo visibles para ellos.
        * Asistentes sin usuarios explícitos → visibles según reglas
          estándar (is_public / allowed_group_ids).
        * Administradores del sistema → siguen viéndolo todo (misma
          lógica que el método original).
        """
        if not user:
            user = self.env.user
        if user.has_group("base.group_system"):
            return super()._get_allowed_assistants_for_user(user=user)

        # Incluye asistentes asignados específicamente al usuario, aunque
        # no sean públicos ni pertenezcan a sus grupos.
        assigned = self.search(
            [("allowed_user_ids", "in", user.id)]
        )

        # El super() ya aplica is_public / allowed_group_ids. Le quitamos
        # los que tengan allowed_user_ids definidos pero el usuario no
        # esté dentro, porque en ese caso deben quedar ocultos.
        base_allowed = super()._get_allowed_assistants_for_user(user=user)
        base_allowed = base_allowed.filtered(
            lambda a: not a.allowed_user_ids or user in a.allowed_user_ids
        )
        return base_allowed | assigned
