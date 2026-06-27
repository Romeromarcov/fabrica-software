"""
tools/react_loop.py — Mini-loop ReAct para el harness/ACI (PLAN_MAESTRO F2, paso 2).

Convierte una llamada de agente de un solo turno en un loop "pide tool → harness ejecuta →
observa → itera". El agente, en vez de recibir todo el contexto en el prompt, pide tools del
`agent_toolbelt` (read_file, grep, run_tests…) y razona sobre lo que lee del repo real.

Orquestación pura y testeable: `call_fn` (llamada al agente) y `dispatch_fn` (ejecución de
tools) se inyectan. Sin estado global, sin lógica de proveedor, sin side effects al importar.

Protocolo (agnóstico de proveedor, sobre texto):
  • El agente pide tools con líneas:   TOOL: <nombre> {<json-args>}
  • Cuando termina, entrega:           FINAL: <respuesta>
  • Topes: max_iterations y truncado de observaciones (no explota el contexto).
  • Degradación: si el agente no pide tools ni marca FINAL, su texto se toma como final
    (equivale al prompt-stuffing de hoy → nunca peor que el comportamiento previo).
"""
from __future__ import annotations

import json
import logging
import re
from typing import Callable, Optional

logger = logging.getLogger(__name__)

_TOOL_RE = re.compile(r"^\s*TOOL:\s*([A-Za-z_]\w*)\s*(\{.*\})?\s*$", re.MULTILINE)
_FINAL_RE = re.compile(r"FINAL:\s*(.*)", re.DOTALL)

_DEFAULT_MAX_ITERATIONS = 6
_MAX_OBSERVATION_CHARS = 3000


def protocol_instructions(tool_specs: list[dict]) -> str:
    """Bloque de instrucciones del protocolo ReAct + catálogo de tools para el prompt."""
    lines = [
        "\n\n## MODO HARNESS — HERRAMIENTAS",
        "Tienes herramientas para LEER el repo real antes de responder. Úsalas en vez de asumir.",
        "Para invocar una tool escribe UNA línea EXACTA por llamada:",
        "  TOOL: <nombre> {\"arg\": \"valor\"}",
        "Observarás el resultado y podrás pedir más tools. Cuando tengas todo, responde:",
        "  FINAL: <tu respuesta completa>",
        "Tools disponibles:",
    ]
    for s in tool_specs:
        lines.append(f"  - {s['name']}({s['args']}) — {s['desc']}")
    return "\n".join(lines) + "\n"


def parse_tool_calls(text: str) -> list[tuple[str, dict]]:
    """Extrae las llamadas `TOOL: nombre {json}` del texto del agente."""
    calls: list[tuple[str, dict]] = []
    for m in _TOOL_RE.finditer(text or ""):
        name = m.group(1)
        raw_args = m.group(2)
        args: dict = {}
        if raw_args:
            try:
                parsed = json.loads(raw_args)
                if isinstance(parsed, dict):
                    args = parsed
            except (json.JSONDecodeError, ValueError) as exc:
                logger.debug("react_loop: args no-JSON para %s (%s); se usan {}", name, exc)
        calls.append((name, args))
    return calls


def parse_final(text: str) -> Optional[str]:
    """Devuelve la respuesta final si el agente marcó FINAL:, si no None."""
    m = _FINAL_RE.search(text or "")
    return m.group(1).strip() if m else None


def run_react(
    call_fn: Callable[[str], tuple],
    *,
    base_task: str,
    dispatch_fn: Callable[..., dict],
    tool_specs: list[dict],
    max_iterations: int = _DEFAULT_MAX_ITERATIONS,
    max_observation_chars: int = _MAX_OBSERVATION_CHARS,
) -> tuple[str, list, int]:
    """
    Ejecuta el loop ReAct. Devuelve (texto_final, [cost_entries], n_iteraciones).

    `call_fn(task) -> (text, cost)`; `dispatch_fn(tool_name, **args) -> dict`.
    """
    transcript = base_task + protocol_instructions(tool_specs)
    costs: list = []
    last_text = ""

    for i in range(1, max_iterations + 1):
        text, cost = call_fn(transcript)
        last_text = text
        if cost is not None:
            costs.append(cost)

        final = parse_final(text)
        calls = parse_tool_calls(text)

        # Fin: el agente entregó FINAL o no pidió tools (degrada a su texto como respuesta).
        if final is not None:
            return final, costs, i
        if not calls:
            return text, costs, i

        observations = []
        for name, args in calls:
            result = dispatch_fn(name, **args)
            observations.append(f"OBSERVATION {name}: {json.dumps(result, ensure_ascii=False)[:max_observation_chars]}")
        logger.info("react_loop: iteración %d ejecutó %d tool(s)", i, len(calls))

        transcript = (
            transcript
            + "\n\n## TU TURNO ANTERIOR\n" + text
            + "\n\n## OBSERVACIONES\n" + "\n".join(observations)
            + "\n\nContinúa: pide más tools (TOOL: ...) o entrega FINAL: con tu respuesta."
        )

    logger.info("react_loop: alcanzado el tope de %d iteraciones; se devuelve el último texto", max_iterations)
    return last_text, costs, max_iterations
