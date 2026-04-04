# -*- coding: utf-8 -*-
import logging
import os

from odoo import api, fields, models

_logger = logging.getLogger(__name__)

MAX_FILE_SNIPPET = 4000


class LLMModuleKnowledgeSnapshot(models.Model):
    _name = "llm.module.knowledge.snapshot"
    _description = "Snapshot de conocimiento de módulos instalados"

    name = fields.Char(default="Conocimiento de módulos", required=True)
    active = fields.Boolean(default=True)
    prepend_to_chat = fields.Boolean(
        string="Anteponer al chat LLM",
        default=True,
        help="Si está activo, el contenido del snapshot se envía como mensaje de sistema "
        "al inicio de cada conversación (junto al contexto del registro vinculado). "
        "Aumenta el contexto útil pero también el consumo de tokens; desactive si "
        "necesita hilos más ligeros.",
    )
    prepend_max_chars = fields.Integer(
        string="Máximo de caracteres en el prepend",
        default=32000,
        help="Límite de texto del snapshot inyectado en el prompt (por defecto ~8k tokens aprox.).",
    )
    content = fields.Text(string="Contenido agregado")
    last_sync = fields.Datetime(string="Última sincronización", readonly=True)

    @api.model
    def _get_or_create_singleton(self):
        rec = self.search([], limit=1)
        if not rec:
            rec = self.create({"name": "Conocimiento de módulos"})
        return rec

    def action_refresh_snapshot(self):
        """Genera texto a partir de módulos instalados y archivos .py (extractos)."""
        self.ensure_one()
        lines = []
        mods = self.env["ir.module.module"].search([("state", "=", "installed")])
        for mod in mods.sorted(lambda m: m.name):
            lines.append(f"## Módulo: {mod.name}\n")
            lines.append(f"Nombre visible: {mod.shortdesc or ''}\n")
            lines.append(f"Resumen: {mod.summary or ''}\n")
            imodels = self.env["ir.model"].search([("model", "!=", False)])
            related = imodels.filtered(
                lambda m, mn=mod.name: m.modules
                and mn in [x.strip() for x in m.modules.split(",")]
            )
            if related:
                lines.append("Modelos (muestra):\n")
                for im in related[:80]:
                    lines.append(f"  - {im.model}: {im.name}\n")
            path = self._module_path(mod.name)
            if path:
                py_snip = self._sample_python_files(path)
                if py_snip:
                    lines.append("Extractos .py (docstrings / cabeceras):\n")
                    lines.append(py_snip[:20000])
            lines.append("\n---\n")

        text = "".join(lines)
        max_len = 500000
        if len(text) > max_len:
            text = text[:max_len] + "\n… [truncado]"
        self.write({"content": text, "last_sync": fields.Datetime.now()})
        return True

    def _module_path(self, module_name):
        """Ruta addons del módulo si existe."""
        try:
            from odoo.modules.module import get_module_path

            return get_module_path(module_name)
        except Exception as e:
            _logger.debug("path %s: %s", module_name, e)
            return None

    def _sample_python_files(self, base_path):
        """Lee trozos de .py bajo el directorio del módulo."""
        out = []
        if not base_path or not os.path.isdir(base_path):
            return ""
        for root, _dirs, files in os.walk(base_path):
            for fn in files:
                if not fn.endswith(".py"):
                    continue
                if "test" in root.lower():
                    continue
                fp = os.path.join(root, fn)
                try:
                    with open(fp, encoding="utf-8", errors="ignore") as f:
                        chunk = f.read(MAX_FILE_SNIPPET)
                    out.append(f"\n### {fp}\n```python\n{chunk}\n```\n")
                except OSError:
                    continue
                if len("".join(out)) > 15000:
                    return "".join(out)
        return "".join(out)

    @api.model
    def cron_monthly_snapshot(self):
        rec = self._get_or_create_singleton()
        rec.action_refresh_snapshot()
