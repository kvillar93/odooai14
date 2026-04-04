"""
Migration: Clean up threads referencing old interactive assistant (llm_assistant_invoice_analyzer).
Prevents FK constraint violations during module upgrade.
"""

import logging

_logger = logging.getLogger(__name__)


def migrate(cr, version):
    if not version:
        return

    # Find old assistant
    cr.execute("""
        SELECT res_id FROM ir_model_data
        WHERE module = 'account_invoice_import_llm'
        AND name = 'llm_assistant_invoice_analyzer'
        AND model = 'llm.assistant'
    """)
    result = cr.fetchone()
    if not result:
        return

    old_assistant_id = result[0]
    _logger.info("Cleaning up threads for old assistant ID: %s", old_assistant_id)

    # Get thread IDs
    cr.execute("SELECT id FROM llm_thread WHERE assistant_id = %s", (old_assistant_id,))
    thread_ids = [row[0] for row in cr.fetchall()]
    if not thread_ids:
        return

    # Delete messages, threads, and ir_model_data in order
    cr.execute(
        "DELETE FROM mail_message WHERE model = 'llm.thread' AND res_id IN %s",
        (tuple(thread_ids),),
    )
    cr.execute("DELETE FROM llm_thread WHERE id IN %s", (tuple(thread_ids),))
    cr.execute(
        "DELETE FROM ir_model_data WHERE model = 'llm.thread' AND res_id IN %s",
        (tuple(thread_ids),),
    )
    _logger.info("Deleted %d thread(s)", len(thread_ids))
