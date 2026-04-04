import json
import logging
import re
from typing import Any, Optional, Union

from odoo import _, api, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

_SQL_BLOCKED = re.compile(
    r"\b(INSERT|UPDATE|DELETE|DROP|CREATE|ALTER|TRUNCATE|GRANT|REVOKE|EXECUTE)\b",
    re.IGNORECASE | re.DOTALL,
)


class LLMToolRecordRetriever(models.Model):
    _inherit = "llm.tool"

    @api.model
    def _get_available_implementations(self):
        implementations = super()._get_available_implementations()
        return implementations + [("odoo_record_retriever", "Odoo Record Retriever")]

    def _validate_select_only_sql(self, sql_text: str) -> str:
        """Solo SELECT de lectura; una sentencia."""
        s = (sql_text or "").strip().rstrip(";")
        if not s:
            raise UserError(_("La consulta SQL está vacía."))
        if ";" in s:
            raise UserError(_("Solo se permite una sentencia SQL (sin punto y coma interno)."))
        if _SQL_BLOCKED.search(s):
            raise UserError(
                _(
                    "Solo se permiten consultas SELECT de lectura (sin INSERT, UPDATE, DELETE, DDL, etc.)."
                )
            )
        if not re.match(r"^\s*SELECT\b", s, re.IGNORECASE | re.DOTALL):
            raise UserError(_("La consulta debe comenzar con SELECT."))
        try:
            import sqlparse
            from sqlparse.sql import Statement

            parsed = sqlparse.parse(s)
            if len(parsed) != 1:
                raise UserError(_("Una sola sentencia SQL permitida."))
            stmt = parsed[0]
            if stmt.get_type() != "SELECT":
                raise UserError(_("Solo SELECT está permitido."))
        except ImportError:
            _logger.debug("sqlparse no instalado; validación por regex únicamente.")
        return s

    def _execute_sql_select(self, sql_text: str, sql_limit: int) -> list[dict[str, Any]]:
        """Ejecuta SELECT en un SAVEPOINT y revierte para no persistir efectos."""
        sql = self._validate_select_only_sql(sql_text)
        self.env.cr.execute("SAVEPOINT llm_tool_sql_read")
        try:
            self.env.cr.execute(sql)
            rows = self.env.cr.fetchall()
            cols = [d[0] for d in (self.env.cr.description or [])]
            lim = min(max(1, int(sql_limit)), 5000)
            out = []
            for row in rows[:lim]:
                out.append({cols[i]: row[i] for i in range(len(cols))})
            return json.loads(json.dumps(out, default=str))
        finally:
            self.env.cr.execute("ROLLBACK TO SAVEPOINT llm_tool_sql_read")

    def odoo_record_retriever_execute(
        self,
        model: str = "",
        domain: list[list[Union[str, int, bool, float, None]]] = [],  # noqa: B006
        fields: list[str] = [],  # noqa: B006
        limit: int = 100,
        mode: str = "orm",
        query: Optional[str] = None,
        sql_limit: int = 500,
    ) -> dict[str, Any]:
        """
        Execute the Odoo Record Retriever tool

        Parameters:
            model: The Odoo model to retrieve records from (modo orm)
            domain: Domain to filter records (list of lists/tuples like ['field', 'op', 'value'])
            fields: List of field names to retrieve
            limit: Maximum number of records to retrieve (ORM)
            mode: "orm" (RPC/search_read) o "sql" (solo SELECT)
            query: Sentencia SQL SELECT (modo sql)
            sql_limit: Máximo de filas devueltas en modo sql
        """
        if mode == "sql":
            if not query:
                raise UserError(_("En modo sql debe indicarse el parámetro query (SELECT)."))
            _logger.info("Odoo Record Retriever SQL (solo lectura)")
            rows = self._execute_sql_select(query, sql_limit)
            return {"rows": rows}

        if not model:
            raise UserError(_("Debe indicarse el modelo en modo orm."))

        _logger.info(
            "Executing Odoo Record Retriever ORM: model=%s, domain=%s, fields=%s, limit=%s",
            model,
            domain,
            fields,
            limit,
        )
        model_obj = self.env[model]

        # Using search_read for efficiency
        if fields:
            result = model_obj.search_read(domain=domain, fields=fields, limit=limit)
        else:
            records = model_obj.search(domain=domain, limit=limit)
            result = records.read()

        # Convert to serializable format
        return json.loads(json.dumps(result, default=str))
