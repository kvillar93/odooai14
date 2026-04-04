# -*- coding: utf-8 -*-
import io
import json
import logging
from typing import Any, Optional

from odoo import _, api, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class LLMToolArtifact(models.Model):
    _inherit = "llm.tool"

    @api.model
    def _get_available_implementations(self):
        impl = super()._get_available_implementations()
        return impl + [("llm_artifact_builder", "Generador de artefactos (gráfico/Excel)")]

    def llm_artifact_builder_execute(
        self,
        artifact_type: str = "echarts",
        title: str = "Informe",
        # --- ECharts (modo principal) ---
        echarts_option: str = "{}",
        explanation: str = "",
        # --- Excel ---
        file_name: Optional[str] = None,
        data_json: str = "[]",
        # --- Matplotlib legacy (fallback) ---
        chart_kind: str = "bar",
    ) -> dict[str, Any]:
        """
        Genera artefactos visuales interactivos en el chat.

        artifact_type:
          - "echarts"  (por defecto) → gráfico interactivo con Apache ECharts.
          - "xlsx"     → Excel descargable.
          - "chart"    → PNG con matplotlib (solo como fallback).

        Para gráficos ECharts:
          - echarts_option: JSON completo de opciones ECharts 5 (ver https://echarts.apache.org/en/option.html).
            Puede incluir campo extra "odoo_links" para drill-down a registros Odoo:
              "odoo_links": {"model": "sale.order.line", "domain_template": "[['product_id.name','=','{{name}}']]"}
          - explanation: texto markdown que acompaña el gráfico (incluido en el PDF).

        IMPORTANTE: el campo "mensaje_markdown" del resultado debe copiarse LITERALMENTE
        en tu respuesta para que el gráfico se muestre en el chat.
        """
        self.ensure_one()

        if artifact_type == "xlsx":
            try:
                data = json.loads(data_json or "[]")
            except json.JSONDecodeError as e:
                raise UserError(_("JSON inválido en data_json: %s") % e) from e
            fname = file_name or "artefacto"
            return self._artifact_xlsx(title, data, fname)

        if artifact_type == "chart":
            # Matplotlib legacy
            try:
                data = json.loads(data_json or "[]")
            except json.JSONDecodeError as e:
                raise UserError(_("JSON inválido en data_json: %s") % e) from e
            fname = file_name or "grafico"
            return self._artifact_chart(title, data, chart_kind, fname)

        # Default: ECharts interactivo
        return self._artifact_echarts(title, echarts_option, explanation)

    # ------------------------------------------------------------------
    # ECharts (nuevo motor principal)
    # ------------------------------------------------------------------

    def _artifact_echarts(self, title, echarts_option_str, explanation):
        """Valida la opción ECharts y devuelve el bloque markdown para insertar en chat."""
        if not echarts_option_str or echarts_option_str.strip() in ("{}", ""):
            raise UserError(
                _(
                    "echarts_option está vacío. Proporciona un JSON de opción ECharts válido con "
                    "title, xAxis/yAxis (si aplica) y series."
                )
            )
        try:
            option = json.loads(echarts_option_str)
        except json.JSONDecodeError as e:
            raise UserError(_("JSON inválido en echarts_option: %s") % e) from e

        if not isinstance(option, dict):
            raise UserError(_("echarts_option debe ser un objeto JSON (dict)."))

        # Asegurar título si no lo tiene
        if "title" not in option and title:
            option["title"] = {"text": title}

        # Aplicar tema por defecto si no se especificó
        option.setdefault("tooltip", {"trigger": "axis"})
        option.setdefault("toolbox", {
            "show": True,
            "feature": {
                "dataZoom": {"yAxisIndex": "none"},
                "restore": {},
                "saveAsImage": {}
            }
        })

        option_str = json.dumps(option, ensure_ascii=False)
        explanation_md = f"\n\n{explanation}" if explanation and explanation.strip() else ""

        # Bloque fenced que el frontend detecta y renderiza con ECharts
        mensaje_markdown = f"```echarts\n{option_str}\n```{explanation_md}"

        return {
            "tipo": "echarts",
            "mensaje_markdown": mensaje_markdown,
            "nota": (
                "Copia el campo 'mensaje_markdown' literalmente en tu respuesta "
                "para que el gráfico interactivo aparezca en el chat."
            ),
        }

    # ------------------------------------------------------------------
    # Excel
    # ------------------------------------------------------------------

    def _artifact_xlsx(self, title, data, fname):
        try:
            import xlsxwriter
        except ImportError as e:
            raise UserError(_("Instale xlsxwriter: %s") % e) from e
        buf = io.BytesIO()
        workbook = xlsxwriter.Workbook(buf, {"in_memory": True})
        sheet = workbook.add_worksheet(title[:31] or "Hoja1")
        if isinstance(data, list) and data and isinstance(data[0], dict):
            headers = list(data[0].keys())
            for c, h in enumerate(headers):
                sheet.write(0, c, h)
            for r, row in enumerate(data, start=1):
                for c, h in enumerate(headers):
                    sheet.write(r, c, row.get(h))
        else:
            sheet.write(0, 0, json.dumps(data, default=str))
        workbook.close()
        import base64
        b64 = base64.b64encode(buf.getvalue()).decode()
        att = self.env["ir.attachment"].create(
            {
                "name": f"{fname}.xlsx",
                "type": "binary",
                "datas": b64,
                "mimetype": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            }
        )
        base = self.env["ir.config_parameter"].sudo().get_param("web.base.url", "")
        url = f"{base}/web/content/{att.id}?download=true"
        return {
            "tipo": "xlsx",
            "url_descarga": url,
            "attachment_id": att.id,
        }

    # ------------------------------------------------------------------
    # Matplotlib legacy (fallback)
    # ------------------------------------------------------------------

    def _artifact_chart(self, title, data, chart_kind, fname):
        try:
            import base64
            import matplotlib
            matplotlib.use("Agg")
            import matplotlib.pyplot as plt
        except ImportError as e:
            raise UserError(_("Instale matplotlib: %s") % e) from e

        fig, ax = plt.subplots(figsize=(6, 4))
        if isinstance(data, list) and data and isinstance(data[0], dict):
            keys = list(data[0].keys())
            if len(keys) >= 2:
                xk, yk = keys[0], keys[1]
                xs = [row.get(xk) for row in data]
                ys = [row.get(yk) for row in data]
                ax.bar(range(len(xs)), ys, tick_label=[str(x) for x in xs])
                ax.set_title(title)
                ax.set_ylabel(yk)
            else:
                ax.text(0.5, 0.5, str(data), ha="center")
        elif isinstance(data, list) and len(data) == 2:
            ax.plot(data[0], data[1])
            ax.set_title(title)
        else:
            ax.text(0.5, 0.5, json.dumps(data, default=str)[:2000], ha="center")
        buf = io.BytesIO()
        fig.savefig(buf, format="png", bbox_inches="tight")
        plt.close(fig)
        b64 = base64.b64encode(buf.getvalue()).decode()
        att = self.env["ir.attachment"].create(
            {
                "name": f"{fname}.png",
                "type": "binary",
                "datas": b64,
                "mimetype": "image/png",
            }
        )
        base = self.env["ir.config_parameter"].sudo().get_param("web.base.url", "")
        url = f"{base}/web/content/{att.id}?download=true"
        return {
            "tipo": "chart",
            "mensaje_markdown": f"![{title}]({base}/web/image/{att.id})",
            "url_descarga": url,
            "attachment_id": att.id,
        }
