"""
tools/pipeline_orchestrator.py — Orquestación entre pipelines (PLAN_PLATAFORMA_V2 Fase 8).

Bus de eventos desacoplado entre dominios: un evento (p.ej. `software.feature_merged`)
dispara otros pipelines según los `triggers` declarados en su `pipeline.yaml`:

    triggers:
      - on: "software.feature_merged"
        map: { feature_name: input.title, changelog: input.body }

Este módulo resuelve QUÉ pipelines se disparan ante un evento y CÓMO se mapea el
payload del evento al input del pipeline destino. Lógica pura, verificable offline.
La EJECUCIÓN real del pipeline destino (que requiere LLM) se delega al runtime; aquí
se devuelve el PLAN de despacho.
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)


def _resolve_path(payload: dict, expr: str):
    """
    Resuelve una expresión de mapeo. 'input.title' → payload['title'].
    Cualquier otra cosa se trata como literal.
    """
    expr = (expr or "").strip()
    if expr.startswith("input."):
        key = expr[len("input."):]
        return payload.get(key)
    return expr


def map_event_to_input(trigger: dict, event_payload: dict) -> dict:
    """Aplica el `map` del trigger al payload del evento → input del pipeline destino."""
    mapping = (trigger or {}).get("map") or {}
    result: dict = {}
    for dest_key, expr in mapping.items():
        result[dest_key] = _resolve_path(event_payload or {}, expr)
    return result


def triggers_for_event(event_name: str) -> list[dict]:
    """
    Recorre todos los pipelines y devuelve los triggers que casan con `event_name`:
    [{pipeline, on, map}]. Vacío si ninguno casa.
    """
    from tools.pipeline_loader import discover_pipelines, load_pipeline

    matches: list[dict] = []
    for name in discover_pipelines():
        try:
            spec = load_pipeline(name)
        except Exception as exc:  # noqa: BLE001 — un pipeline ilegible no frena al resto
            logger.warning("orchestrator: pipeline '%s' ilegible (%s)", name, exc)
            continue
        for trig in (spec.get("triggers") or []):
            # YAML 1.1 interpreta la clave `on:` como booleano True (quirk Norway/on-off);
            # aceptamos ambas formas para no obligar a citar la clave en el yaml.
            on_value = trig.get("on", trig.get(True))
            if on_value == event_name:
                matches.append({"pipeline": name, "on": on_value,
                                "map": trig.get("map") or {}})
    return matches


def on_event(event_name: str, payload: dict | None = None) -> list[dict]:
    """
    Devuelve el PLAN de despacho ante un evento: [{pipeline, input}].
    No ejecuta el pipeline destino (eso requiere LLM/runtime) — devuelve el plan.
    """
    payload = payload or {}
    plan: list[dict] = []
    for trig in triggers_for_event(event_name):
        plan.append({
            "pipeline": trig["pipeline"],
            "input": map_event_to_input(trig, payload),
            "triggered_by": event_name,
        })
    if plan:
        logger.info("orchestrator: evento '%s' → %d pipeline(s) a disparar",
                    event_name, len(plan))
    return plan
