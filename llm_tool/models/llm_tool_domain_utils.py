# -*- coding: utf-8 -*-
"""Utilidades de validación y saneo de ``domain`` para herramientas LLM.

Los modelos LLM (Gemini, Anthropic, OpenAI…) ocasionalmente generan
``domain`` mal estructurados. El caso más típico es un *leaf* con dos
elementos en lugar de tres porque el modelo concatena el operador con el
valor (p. ej. ``["id", "=,947]],model:"]``). Cuando ese domain llega al
ORM, Odoo lanza ``Invalid leaf`` y el usuario ve un error críptico.

Este módulo proporciona:

* :func:`sanitize_domain`: intenta arreglar leafs malformados típicos y
  devuelve un domain limpio. Si la reparación es imposible, lanza
  ``UserError`` con un mensaje *explicativo en español* que el LLM
  recibirá como ``tool_result`` y podrá usar para reintentar con el
  formato correcto.
* :data:`VALID_OPERATORS`: lista de operadores válidos para validación.
"""
import logging
import re
from typing import Any, Optional

from odoo import _
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

# Operadores soportados por el ORM de Odoo (orm/expression.py).
VALID_OPERATORS = frozenset({
    "=", "!=", ">", ">=", "<", "<=",
    "=?", "=like", "=ilike",
    "like", "not like",
    "ilike", "not ilike",
    "in", "not in",
    "child_of", "parent_of",
    "any", "not any",
})

# Conectores lógicos válidos en un domain (forma polaca).
LOGICAL_OPS = frozenset({"&", "|", "!"})

# Patrón para detectar el caso típico ``"=,947]],model:"`` (operador
# concatenado con valor por error de generación del LLM).
_BROKEN_LEAF_RE = re.compile(
    r"^\s*("
    r"=|!=|>=|<=|>|<|"
    r"=\?|=like|=ilike|"
    r"not like|like|"
    r"not ilike|ilike|"
    r"not in|in|"
    r"child_of|parent_of|"
    r"not any|any"
    r")\s*,?\s*(.+?)\s*[\]\}\)]*\s*$",
    re.IGNORECASE,
)


def _try_coerce_value(raw: str) -> Any:
    """Intenta convertir una cadena suelta al tipo Python adecuado.

    Limpia caracteres de ruido (corchetes, llaves, dos puntos, comas,
    espacios) que aparecen cuando el LLM concatena por error operador y
    valor con sintaxis residual del JSON envoltorio.
    """
    s = (raw or "").strip()
    # Quitar ruido por ambos extremos varias veces hasta estabilizar.
    noise_chars = ",;:]}) "
    for _i in range(5):
        new = s.strip().strip(noise_chars)
        if new == s:
            break
        s = new
    if not s:
        return False
    low = s.lower()
    if low in ("true", "verdadero"):
        return True
    if low in ("false", "falso"):
        return False
    if low in ("null", "none", "nil"):
        return False
    # ¿Lista explícita? ``[1, 2, 3]`` o ``[1,2,3]``
    if s.startswith("[") and s.endswith("]"):
        inner = s[1:-1]
        parts = [p.strip() for p in inner.split(",") if p.strip()]
        return [_try_coerce_value(p) for p in parts]
    # Cadena con comillas externas (eliminarlas).
    if (s.startswith('"') and s.endswith('"')) or (
        s.startswith("'") and s.endswith("'")
    ):
        s = s[1:-1]
    # ¿Número entero o decimal entero al inicio? Acepta también casos
    # como ``947]],model`` extrayendo solo el número líder, ya que ese
    # fragmento es el típico residuo del JSON malformado.
    m_num = re.match(r"^\s*(-?\d+(?:\.\d+)?)\s*$", s)
    if m_num:
        token = m_num.group(1)
        if "." in token:
            return float(token)
        return int(token)
    m_lead = re.match(r"^\s*(-?\d+(?:\.\d+)?)\b", s)
    if m_lead:
        token = m_lead.group(1)
        if "." in token:
            return float(token)
        return int(token)
    return s


def _try_split_broken_leaf(leaf: list) -> Optional[list]:
    """Intenta partir un leaf de 2 elementos cuyo 2.º componente concatena
    operador y valor (p. ej. ``["id", "=947"]`` o
    ``["id", "=,947]],model:"]``).

    Devuelve un leaf de 3 elementos válido o ``None`` si no hay match.
    """
    if not isinstance(leaf, (list, tuple)) or len(leaf) != 2:
        return None
    field, broken = leaf
    if not isinstance(field, str) or not isinstance(broken, str):
        return None
    m = _BROKEN_LEAF_RE.match(broken)
    if not m:
        return None
    op = m.group(1).lower()
    raw_value = m.group(2)
    value = _try_coerce_value(raw_value)
    return [field, op, value]


# Operadores que esperan una lista/tupla como valor.
_LIST_OPERATORS = frozenset({"in", "not in"})


def _try_flatten_list_operator_leaf(leaf: list) -> Optional[list]:
    """Repara leafs aplanados de operadores ``in`` / ``not in``.

    El LLM a veces genera ``["id", "in", 1118, 1119]`` en lugar de
    ``["id", "in", [1118, 1119]]``. Si detectamos exactamente ese
    patrón, recolectamos los valores escalares finales en una lista.
    """
    if not isinstance(leaf, list) or len(leaf) <= 3:
        return None
    field = leaf[0]
    op = leaf[1]
    if not isinstance(field, str) or not isinstance(op, str):
        return None
    if op.lower() not in _LIST_OPERATORS:
        return None
    rest = leaf[2:]
    # Solo recolectamos valores escalares (str, int, float, bool); si hay
    # una lista anidada, no aplicamos esta heurística.
    if not all(isinstance(v, (str, int, float, bool)) or v is None for v in rest):
        return None
    return [field, op.lower(), list(rest)]


def _validate_leaf(leaf: Any) -> list:
    """Valida un solo leaf y devuelve la versión normalizada.

    Lanza ``UserError`` con mensaje explicativo si es irreparable.
    """
    if isinstance(leaf, str) and leaf in LOGICAL_OPS:
        return leaf  # type: ignore[return-value]

    if isinstance(leaf, tuple):
        leaf = list(leaf)

    if not isinstance(leaf, list):
        raise UserError(
            _(
                "Domain inválido: cada cláusula debe ser una lista "
                "[campo, operador, valor] o un conector lógico ('&', '|', '!'). "
                "Recibido: %r"
            )
            % (leaf,)
        )

    # Caso típico de mala generación del LLM: leaf de 2 elementos donde
    # el 2.º componente concatena operador + valor. Lo intentamos partir.
    if len(leaf) == 2:
        repaired = _try_split_broken_leaf(leaf)
        if repaired is not None:
            _logger.warning(
                "llm_tool: leaf domain malformado reparado %r -> %r",
                leaf,
                repaired,
            )
            leaf = repaired

    # Caso ``["id", "in", 1118, 1119]`` → ``["id", "in", [1118, 1119]]``.
    if len(leaf) > 3:
        flattened = _try_flatten_list_operator_leaf(leaf)
        if flattened is not None:
            _logger.warning(
                "llm_tool: leaf domain con operador de lista aplanado "
                "reparado %r -> %r",
                leaf,
                flattened,
            )
            leaf = flattened

    if len(leaf) != 3:
        raise UserError(
            _(
                "Domain inválido: cada leaf debe tener exactamente 3 "
                "elementos [campo, operador, valor]. Recibido: %r. "
                "Ejemplo correcto: [\"id\", \"=\", 947] o "
                "[\"name\", \"ilike\", \"prueba\"] o "
                "[\"id\", \"in\", [1118, 1119]] (con los IDs en una lista)."
            )
            % (leaf,)
        )

    field, op, value = leaf
    if not isinstance(field, str) or not field:
        raise UserError(
            _(
                "Domain inválido: el primer elemento del leaf debe ser el "
                "nombre del campo (cadena). Recibido: %r"
            )
            % (field,)
        )
    if not isinstance(op, str) or op.lower() not in VALID_OPERATORS:
        raise UserError(
            _(
                "Domain inválido: operador %r no soportado. Operadores "
                "válidos: %s. Leaf recibido: %r"
            )
            % (op, ", ".join(sorted(VALID_OPERATORS)), leaf)
        )

    # Para ``in`` / ``not in`` el valor debe ser una lista o tupla.
    op_l = op.lower()
    if op_l in _LIST_OPERATORS:
        if isinstance(value, (str, int, float, bool)) or value is None:
            value = [value]
        elif isinstance(value, tuple):
            value = list(value)
        elif not isinstance(value, list):
            raise UserError(
                _(
                    "Domain inválido: el operador %r requiere una lista de "
                    "valores como tercer elemento. Leaf recibido: %r. "
                    "Ejemplo correcto: [\"id\", \"in\", [1118, 1119]]."
                )
                % (op_l, leaf)
            )

    return [field, op_l, value]


def sanitize_domain(domain: Any) -> list:
    """Valida y normaliza un domain. Devuelve siempre una lista válida.

    * Acepta tuplas y las convierte a listas.
    * Acepta ``None`` o lista vacía → devuelve ``[]``.
    * Repara leafs malformados típicos (operador y valor pegados).
    * Lanza ``UserError`` (con mensaje legible para el LLM) si la
      estructura general no se puede corregir.
    """
    if domain is None:
        return []
    if isinstance(domain, tuple):
        domain = list(domain)
    if not isinstance(domain, list):
        raise UserError(
            _(
                "Domain inválido: debe ser una lista de leafs. Recibido tipo "
                "%s: %r. Ejemplo correcto: [[\"id\", \"=\", 947]]."
            )
            % (type(domain).__name__, domain)
        )

    out = []
    for leaf in domain:
        out.append(_validate_leaf(leaf))
    return out
