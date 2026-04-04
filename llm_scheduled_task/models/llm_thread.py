# -*- coding: utf-8 -*-
from odoo import api, fields, models


class LLMThread(models.Model):
    _inherit = "llm.thread"

    is_scheduled_task = fields.Boolean(
        "Pertenece a tarea programada",
        default=False,
        index=True,
        copy=False,
        help="Si está activado, este chat es el chat dedicado de una tarea programada "
             "y se excluye automáticamente de las vistas de chat normales.",
    )
    scheduled_task_ids = fields.One2many(
        "llm.scheduled.task",
        "thread_id",
        string="Tareas programadas",
        readonly=True,
    )
    scheduled_task_count = fields.Integer(
        "Nº Tareas",
        compute="_compute_scheduled_task_count",
    )

    def _compute_scheduled_task_count(self):
        for thread in self:
            thread.scheduled_task_count = len(thread.scheduled_task_ids)

    def action_view_scheduled_tasks(self):
        """Abre las tareas programadas vinculadas a este chat."""
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": "Tareas programadas",
            "res_model": "llm.scheduled.task",
            "view_mode": "tree,form",
            "domain": [("thread_id", "=", self.id)],
        }

    @api.model
    def search_read(self, domain=None, fields=None, offset=0, limit=None, order=None, **kwargs):
        """
        Excluye los chats de tareas programadas de las búsquedas genéricas.

        Solo se incluyen si el dominio ya contiene un filtro explícito por
        'is_scheduled_task', o si el contexto incluye show_task_threads=True.
        """
        domain = list(domain or [])

        if not self.env.context.get("show_task_threads"):
            has_task_filter = any(
                isinstance(leaf, (list, tuple))
                and len(leaf) >= 1
                and leaf[0] == "is_scheduled_task"
                for leaf in domain
            )
            if not has_task_filter:
                domain = [("is_scheduled_task", "=", False)] + domain

        return super().search_read(
            domain=domain,
            fields=fields,
            offset=offset,
            limit=limit,
            order=order,
            **kwargs,
        )
