"""
tools/structured_artifacts.py — Contratos estructurados (PLAN_MAESTRO F1).

Mecanismo de "structured output con reintento por validación": un agente declara un
`output_schema` (registry.json); tras llamarlo, se extrae el bloque JSON de su salida y
se valida contra el schema Pydantic. Si el artefacto es corrupto (no parsea o no valida),
se reintenta la llamada inyectando los errores como feedback — en vez de los formatos
frágiles de parseo string. Reemplaza el "diálogo libre" por objetos validados.

Sin dependencias de proveedor ni side effects al importar: `request_validated` recibe la
función de llamada al agente (inyectada), por lo que es 100% testeable offline.
"""
from __future__ import annotations

import json
import logging
import re
from typing import Callable, Optional

from schemas.agent_outputs import ValidationResult, validate_output

logger = logging.getLogger(__name__)

# Bloque ```json ... ``` (preferente) o ``` ... ``` con un objeto JSON dentro.
_JSON_FENCE_RE = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.DOTALL | re.IGNORECASE)


def extract_json_block(text: str) -> Optional[dict]:
    """
    Extrae el primer objeto JSON del texto del agente. Prioriza un bloque ```json fenced;
    si no hay, intenta el primer {...} balanceado del texto. Devuelve None si nada parsea.
    """
    if not text:
        return None
    for m in _JSON_FENCE_RE.finditer(text):
        obj = _try_load(m.group(1))
        if obj is not None:
            return obj
    # Fallback: primer objeto {...} balanceado fuera de fences.
    snippet = _first_balanced_object(text)
    if snippet:
        return _try_load(snippet)
    return None


def _try_load(raw: str) -> Optional[dict]:
    try:
        obj = json.loads(raw)
        return obj if isinstance(obj, dict) else None
    except (json.JSONDecodeError, ValueError) as exc:
        logger.debug("structured_artifacts: fragmento no es JSON válido (%s)", exc)
        return None


def _first_balanced_object(text: str) -> Optional[str]:
    start = text.find("{")
    while start != -1:
        depth = 0
        for i in range(start, len(text)):
            c = text[i]
            if c == "{":
                depth += 1
            elif c == "}":
                depth -= 1
                if depth == 0:
                    return text[start:i + 1]
        start = text.find("{", start + 1)
    return None


def contract_instruction(schema_name: str, fields: list[str]) -> str:
    """
    Sufijo de instrucción para que el agente emita, además de su salida normal, un bloque
    ```json con los campos del contrato. `fields` son los nombres esperados por el schema.
    """
    campos = ", ".join(fields)
    return (
        f"\n\n## CONTRATO ESTRUCTURADO ({schema_name})\n"
        f"Al final de tu respuesta incluye un bloque ```json con EXACTAMENTE este objeto "
        f"(campos: {campos}). Debe ser JSON válido y los tipos correctos:\n"
        f"```json\n{{ ... }}\n```\n"
    )


def request_validated(
    call_fn: Callable[[str], tuple],
    *,
    schema_name: str,
    base_task: str,
    max_retries: int = 2,
) -> tuple[str, ValidationResult, list]:
    """
    Llama al agente (`call_fn(task) -> (text, cost)`), extrae+valida el artefacto JSON contra
    `schema_name` y reintenta hasta `max_retries` veces si es corrupto, inyectando los errores
    como feedback. Devuelve (último_texto, ValidationResult, [cost_entries]).

    Tolerante: si tras los reintentos sigue inválido, devuelve el ValidationResult con ok=False
    (el llamador decide; nunca lanza). La cobertura de costos acumula todas las llamadas.
    """
    costs: list = []
    task = base_task
    last_text = ""
    last_result = ValidationResult(ok=False, schema_name=schema_name or "", errors=["sin intento"])

    attempts = max_retries + 1
    for attempt in range(1, attempts + 1):
        text, cost = call_fn(task)
        last_text = text
        if cost is not None:
            costs.append(cost)

        data = extract_json_block(text)
        result = validate_output(schema_name, data or {})
        last_result = result
        if result.ok:
            if attempt > 1:
                logger.info("structured_artifacts: '%s' válido tras %d intentos", schema_name, attempt)
            return text, result, costs

        if attempt < attempts:
            errs = "; ".join(result.errors) or "no se encontró un bloque JSON válido"
            logger.warning(
                "structured_artifacts: artefacto '%s' inválido (intento %d/%d): %s — reintentando",
                schema_name, attempt, attempts, errs,
            )
            task = (
                f"{base_task}\n\n## CORRECCIÓN DE CONTRATO (intento {attempt + 1})\n"
                f"Tu bloque JSON anterior NO validó contra {schema_name}. Errores: {errs}.\n"
                f"Devuelve de nuevo el bloque ```json corrigiendo EXACTAMENTE esos campos."
            )

    logger.warning(
        "structured_artifacts: '%s' sigue inválido tras %d intentos; se devuelve ok=False",
        schema_name, attempts,
    )
    return last_text, last_result, costs
