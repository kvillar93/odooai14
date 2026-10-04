# -*- coding: utf-8 -*-
import logging

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    """Separa el esfuerzo de razonamiento del modo de trabajo.

    - ``deep_thinking`` pasa a ``reasoning_effort='high'`` con modo normal.
    - Los resúmenes antiguos se descartan: se generaban sobre una ventana de 25
      mensajes y ahora el historial completo se gestiona con el corte de contexto.
    """
    cr.execute(
        """
        UPDATE llm_thread
           SET reasoning_effort = 'high', chat_work_mode = 'normal'
         WHERE chat_work_mode = 'deep_thinking'
        """
    )
    _logger.info("llm_experience: %s hilos de pensamiento profundo → esfuerzo alto", cr.rowcount)
    cr.execute(
        "UPDATE llm_thread SET reasoning_effort = 'medium' WHERE reasoning_effort IS NULL"
    )
    cr.execute(
        """
        UPDATE llm_thread
           SET usage_compaction_summary = NULL,
               usage_live_tokens = 0,
               usage_needs_compaction = FALSE
         WHERE COALESCE(context_cutoff_message_id, 0) = 0
        """
    )
