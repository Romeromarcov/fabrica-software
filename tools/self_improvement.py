"""
tools/self_improvement.py — Meta-agente de auto-mejora (PLAN_PLATAFORMA_V2 Fase 9, M9).

Agrega señales reales del historial de la fábrica (tendencia de calidad por proyecto,
tendencia de evals, patrones de error recurrentes) y propone mejoras **priorizadas** de
forma DETERMINISTA (reglas), por lo que es 100% verificable sin LLM en vivo. La síntesis
narrativa opcional puede delegarse a un LLM aguas arriba; aquí se entrega el motor de reglas.

Sin side effects al importar. Las recolecciones de señales son defensivas: si una fuente
falla o no tiene datos, se degrada (no rompe el análisis completo).
"""
from __future__ import annotations

import logging
from typing import Optional

logger = logging.getLogger(__name__)

# Umbrales (ajustables) para disparar recomendaciones.
QA_ITERS_HIGH = 3.0          # iteraciones QA promedio altas → loop de corrección caro
LOW_SCORE = 75.0             # score de calidad promedio bajo
ZERO_QA_LOW_PCT = 50.0       # % de features que pasan QA a la primera


def gather_signals(project_id: str = "", repo_path: str = "") -> dict:
    """Recolecta señales del historial. Cada fuente es opcional y defensiva."""
    signals: dict = {"quality": {}, "evals": {}, "recurring_errors": []}

    try:
        from tools.quality_tracker import compute_trend
        signals["quality"] = compute_trend(project_id) if project_id else {}
    except (ImportError, KeyError, ValueError) as exc:
        logger.warning("self_improvement: sin tendencia de calidad: %s", exc)

    try:
        from tools.evals import eval_trend
        signals["evals"] = eval_trend()
    except (ImportError, KeyError, ValueError) as exc:
        logger.warning("self_improvement: sin tendencia de evals: %s", exc)

    if repo_path:
        try:
            from tools.learning_memory import recurring_error_patterns
            signals["recurring_errors"] = recurring_error_patterns(repo_path) or []
        except (ImportError, KeyError, ValueError) as exc:
            logger.warning("self_improvement: sin patrones recurrentes: %s", exc)

    return signals


def propose_improvements(signals: dict) -> list[dict]:
    """
    Motor de reglas: convierte señales en propuestas priorizadas.
    Cada propuesta: {area, severity (alta|media|baja), rationale, action}.
    """
    proposals: list[dict] = []
    q = signals.get("quality") or {}
    e = signals.get("evals") or {}
    recurring = signals.get("recurring_errors") or []

    if q.get("total_features", 0) > 0:
        if q.get("avg_qa_iters", 0) >= QA_ITERS_HIGH:
            proposals.append({
                "area": "qa_loop", "severity": "alta",
                "rationale": f"QA promedia {q['avg_qa_iters']} iteraciones (≥{QA_ITERS_HIGH}): "
                             "el código llega con defectos que el loop corrige caro.",
                "action": "Reforzar prompts de A4/A5 (generación) y A6 (refactor) con los "
                          "bugs recurrentes; subir el listón del checklist de A6.",
            })
        if q.get("avg_score", 100) < LOW_SCORE:
            proposals.append({
                "area": "quality_score", "severity": "alta",
                "rationale": f"Score de calidad promedio {q['avg_score']} < {LOW_SCORE}.",
                "action": "Auditar los gates y añadir casos a la suite de evals de referencia.",
            })
        if q.get("direction") == "empeorando":
            proposals.append({
                "area": "regression", "severity": "alta",
                "rationale": "La tendencia de calidad va empeorando entre features.",
                "action": "Revisar cambios recientes de prompts/estándares; considerar rollback.",
            })
        if q.get("zero_qa_pct", 100) < ZERO_QA_LOW_PCT:
            proposals.append({
                "area": "first_pass", "severity": "media",
                "rationale": f"Solo {q['zero_qa_pct']}% de features pasan QA a la primera.",
                "action": "Endurecer el prompt de A4/A5 con ejemplos de los patrones que fallan.",
            })
        for cat in q.get("recurring_patterns", []):
            proposals.append({
                "area": f"recurring:{cat}", "severity": "media",
                "rationale": f"La categoría de bug '{cat}' reaparece (≥3 veces).",
                "action": f"Añadir una instrucción dura / gate específico para '{cat}'.",
            })

    if e.get("runs", 0) > 0 and e.get("direction") == "empeorando":
        proposals.append({
            "area": "evals", "severity": "alta",
            "rationale": f"Los evals bajaron (latest {e.get('latest')} < previous {e.get('previous')}).",
            "action": "Bisecar qué cambio degradó los evals; bloquear promoción hasta recuperar.",
        })

    for patt in recurring:
        proposals.append({
            "area": "missed_by_pipeline", "severity": "media",
            "rationale": f"Patrón que el pipeline dejó pasar: {patt}",
            "action": "Sembrar un caso de eval y/o un gate que lo atrape.",
        })

    _order = {"alta": 0, "media": 1, "baja": 2}
    proposals.sort(key=lambda p: _order.get(p["severity"], 3))
    return proposals


def format_improvement_report(signals: dict, proposals: Optional[list[dict]] = None) -> str:
    """Reporte legible de auto-mejora (señales + propuestas priorizadas)."""
    if proposals is None:
        proposals = propose_improvements(signals)
    q = signals.get("quality") or {}
    e = signals.get("evals") or {}
    lines = [
        "=== Auto-mejora (M9) ===",
        f"Calidad: features={q.get('total_features', 0)} avg_qa_iters={q.get('avg_qa_iters', 0)} "
        f"avg_score={q.get('avg_score', 0)} dir={q.get('direction', 'sin datos')}",
        f"Evals: runs={e.get('runs', 0)} avg={e.get('avg', 0)} dir={e.get('direction', 'sin datos')}",
        f"Propuestas: {len(proposals)}",
    ]
    for p in proposals:
        lines.append(f"  [{p['severity'].upper()}] {p['area']}: {p['action']}")
    if not proposals:
        lines.append("  (sin acciones: las señales están sanas o no hay datos suficientes)")
    return "\n".join(lines)
