"""
tools/factory_router.py — Router NL unificado de la meta-capa (PLAN_PLATAFORMA_V2 Fase 7, 🟢).

Enruta una petición en lenguaje natural del fundador a la capacidad correcta:
  - "crea un agente de SEO que…"            → agent_builder   (Fase 5)
  - "crea un pipeline legal"                → pipeline_builder (Fase 6)
  - "modifica el prompt de A4", "añade un   → factory_modifier (Fase 7, 🔴 auto-modificación;
     paso antes de A1"                         NO implementado: requiere diseño/sign-off humano)

Solo DECIDE el destino (no ejecuta la acción peligrosa). La clasificación es DETERMINISTA
(reglas de palabras clave, verificable sin LLM) con un LLM opcional inyectable para casos
ambiguos. Sin side effects al importar.
"""
from __future__ import annotations

import re
from typing import Callable, Optional

AGENT_BUILDER = "agent_builder"
PIPELINE_BUILDER = "pipeline_builder"
FACTORY_MODIFIER = "factory_modifier"
UNKNOWN = "unknown"

# Señales de modificación de la fábrica existente (tienen prioridad: son las más específicas).
_MODIFY_PATTERNS = (
    r"\bmodific", r"\bcambia\b", r"\bcambiar\b", r"\bajusta", r"\bedita",
    r"\bprompt\b", r"\bañade un paso\b", r"\bagrega un paso\b", r"\bantes de\b",
    r"\bdespués de\b", r"\brefactoriza\b",
)
_PIPELINE_PATTERNS = (r"\bpipeline\b", r"\bflujo\b", r"\bdominio\b")
_AGENT_PATTERNS = (r"\bagente\b", r"\bagent\b")


def _matches(text: str, patterns) -> bool:
    return any(re.search(p, text) for p in patterns)


def route_request(text: str, llm: Optional[Callable[[str], object]] = None) -> dict:
    """
    Devuelve {"target": <capacidad>, "request": text, "method": "rules"|"llm"}.
    Precedencia de reglas: modificar fábrica > pipeline > agente. Si las reglas no deciden
    y hay `llm`, se delega; el LLM debe responder una de las etiquetas conocidas.
    """
    t = (text or "").lower()

    # "crea/añade un pipeline" gana a "modifica" si menciona pipeline explícitamente como objeto nuevo.
    creating = _matches(t, (r"\bcrea\b", r"\bcrear\b", r"\bnuevo\b", r"\bnueva\b"))

    if _matches(t, _PIPELINE_PATTERNS) and creating:
        return {"target": PIPELINE_BUILDER, "request": text, "method": "rules"}
    if _matches(t, _AGENT_PATTERNS) and creating:
        return {"target": AGENT_BUILDER, "request": text, "method": "rules"}
    if _matches(t, _MODIFY_PATTERNS):
        return {"target": FACTORY_MODIFIER, "request": text, "method": "rules"}
    if _matches(t, _PIPELINE_PATTERNS):
        return {"target": PIPELINE_BUILDER, "request": text, "method": "rules"}
    if _matches(t, _AGENT_PATTERNS):
        return {"target": AGENT_BUILDER, "request": text, "method": "rules"}

    if llm is not None:
        label = str(llm(text)).strip().lower()
        if label in (AGENT_BUILDER, PIPELINE_BUILDER, FACTORY_MODIFIER):
            return {"target": label, "request": text, "method": "llm"}

    return {"target": UNKNOWN, "request": text, "method": "rules"}


# Capacidades implementadas vs. escaladas (para que el llamador no asuma ejecución).
IMPLEMENTED_TARGETS = {AGENT_BUILDER, PIPELINE_BUILDER}
ESCALATED_TARGETS = {FACTORY_MODIFIER}  # Fase 7 🔴 — auto-modificación, requiere humano.


def is_executable(target: str) -> bool:
    """True si el destino tiene una capacidad implementada y segura para ejecutar."""
    return target in IMPLEMENTED_TARGETS
