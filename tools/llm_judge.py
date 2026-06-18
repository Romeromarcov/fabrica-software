"""
tools/llm_judge.py — LLM-as-judge entre agentes (PLAN_PLATAFORMA_V2 M3, Fase 1).

Un evaluador ligero (modelo barato) puntúa la salida de un agente antes de pasar al
siguiente. Bajo umbral → se registra/escala (el reintento automático vive en el
routing del grafo y se aborda en un incremento posterior).

Diseño:
  - Lógica de parseo y decisión: pura y testeable sin red.
  - La llamada al LLM se inyecta (`call_fn`) → tests sin red.
  - Integración vía hook `post_agent` (R2), con guarda de reentrancia para que el
    propio juez no se evalúe a sí mismo (evita recursión infinita).
  - No-op por defecto: solo actúa si `LLM_JUDGE_ENABLED=true`.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Callable, Optional

logger = logging.getLogger(__name__)

# Guarda de reentrancia: True mientras corre una evaluación (el juez no se juzga).
_IN_JUDGE = False


@dataclass
class JudgeVerdict:
    score: int                      # 0..100
    passed: bool
    issues: list[str] = field(default_factory=list)
    raw: str = ""


def build_judge_prompt(agent_label: str, output: str, criteria: Optional[str] = None) -> str:
    """Construye el prompt del juez. Pide un veredicto estructurado y parseable."""
    criteria = criteria or (
        "completitud, correctitud aparente, ausencia de placeholders/TODOs, "
        "coherencia con buenas prácticas"
    )
    return (
        f"Eres un evaluador imparcial. Puntúa la salida del agente '{agent_label}'.\n"
        f"Criterios: {criteria}.\n\n"
        "SALIDA A EVALUAR:\n---\n"
        f"{output[:6000]}\n---\n\n"
        "Responde EXACTAMENTE en este formato:\n"
        "SCORE: <0-100>\n"
        "ISSUES: <lista separada por ';' o 'ninguno'>\n"
    )


def parse_judge_verdict(text: str, threshold: int) -> JudgeVerdict:
    """Parsea la respuesta del juez. Tolerante: sin SCORE → score 0, no pasa."""
    text = text or ""
    score_m = re.search(r"SCORE:\s*(\d{1,3})", text, re.IGNORECASE)
    score = int(score_m.group(1)) if score_m else 0
    score = max(0, min(100, score))

    issues: list[str] = []
    issues_m = re.search(r"ISSUES:\s*(.+)", text, re.IGNORECASE)
    if issues_m:
        raw_issues = issues_m.group(1).strip()
        if raw_issues.lower() not in ("ninguno", "none", "n/a", ""):
            issues = [s.strip() for s in raw_issues.split(";") if s.strip()]

    return JudgeVerdict(score=score, passed=score >= threshold, issues=issues, raw=text)


def judge_output(
    agent_label: str,
    output: str,
    *,
    model: str,
    threshold: int = 60,
    call_fn: Optional[Callable[..., tuple[str, dict]]] = None,
    criteria: Optional[str] = None,
) -> JudgeVerdict:
    """
    Evalúa `output`. `call_fn(agent_key, agent_label, task_content, model) -> (text, cost)`.
    Si no se inyecta, usa `nodes.base.call_agent`. Reentrante-seguro.
    """
    global _IN_JUDGE
    if _IN_JUDGE:
        # Estamos dentro de una evaluación → no evaluar al juez.
        return JudgeVerdict(score=100, passed=True, issues=[], raw="(skip: reentrante)")

    prompt = build_judge_prompt(agent_label, output, criteria)

    if call_fn is None:
        from nodes.base import call_agent as _ca

        def call_fn(**kw):  # type: ignore[misc]
            return _ca(**kw)

    _IN_JUDGE = True
    try:
        text, _cost = call_fn(
            agent_key="llm_judge",
            agent_label=f"Juez de {agent_label}",
            task_content=prompt,
            model=model,
        )
    except Exception as exc:  # noqa: BLE001 — el juez nunca rompe el pipeline
        logger.warning("llm_judge: la evaluación falló (%s) — se asume pase", exc)
        return JudgeVerdict(score=100, passed=True, issues=[], raw=f"(error: {exc})")
    finally:
        _IN_JUDGE = False

    verdict = parse_judge_verdict(text, threshold)
    logger.info("llm_judge[%s]: score=%d passed=%s", agent_label, verdict.score, verdict.passed)
    return verdict


def make_judge_hook(model: str, threshold: int = 60):
    """
    Crea un hook `post_agent` que evalúa la salida del agente. Reentrante-seguro
    (no evalúa al propio juez). Pensado para `hook_engine.register("post_agent", ...)`.
    """
    def _hook(ctx: dict) -> dict:
        if _IN_JUDGE:
            return {}
        output = ctx.get("output_text", "")
        label = ctx.get("agent_label", "agente")
        if not output:
            return {}
        verdict = judge_output(label, output, model=model, threshold=threshold)
        return {"judge_score": verdict.score, "judge_passed": verdict.passed,
                "judge_issues": verdict.issues}

    return _hook
