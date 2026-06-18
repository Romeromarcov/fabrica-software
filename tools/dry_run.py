"""
tools/dry_run.py — Estimación de dry run (PLAN_PLATAFORMA_V2 M10, Fase 3).

Antes de comprometer el pipeline completo, proyecta tiempo/costo/riesgo/iteraciones
esperadas de un feature a partir de:
  - el RIESGO del plan (risk_classifier sobre el texto del MASTER_PLAN + rutas),
  - el HISTORIAL del proyecto (quality_tracker: iteraciones QA medias, costo medio).

Lógica pura (sin LLM, sin red): la "corrida A0+A1" real se dispara desde el CLI con
claves; aquí vive la proyección verificable offline.
"""
from __future__ import annotations

from tools.quality_tracker import compute_trend
from tools.risk_classifier import classify_change_risk, classify_text_risk, max_tier

# Iteraciones QA esperadas por tier cuando NO hay historial (heurística base).
_TIER_BASELINE_ITERS = {"LOW": 1.0, "MEDIUM": 2.0, "HIGH": 3.5}
# Minutos estimados por iteración del pipeline (orden de magnitud, no SLA).
_MINUTES_PER_ITER = 6.0
# Costo USD estimado por iteración cuando no hay historial.
_DEFAULT_COST_PER_ITER = 0.15


def estimate(project_id: str, master_plan: str, files_hint: list[str] | None = None) -> dict:
    """
    Proyecta el esfuerzo esperado de un feature.

    Returns dict:
      risk_tier, expected_qa_iters, expected_cost_usd, expected_minutes,
      based_on_history (bool), history_features (int), notes (list[str]).
    """
    text_tier = classify_text_risk(master_plan or "")
    path_tier = classify_change_risk(files_hint or [])
    risk_tier = max_tier(text_tier, path_tier)

    trend = compute_trend(project_id) if project_id else {}
    history_features = trend.get("total_features", 0) or 0
    based_on_history = history_features >= 3

    notes: list[str] = []

    if based_on_history:
        # Itera desde el historial, ajustando por el piso del tier.
        avg_iters = max(trend.get("avg_qa_iters", 1.0), _TIER_BASELINE_ITERS[risk_tier] * 0.6)
        avg_score = trend.get("avg_score", 100)
        # Score bajo → más iteraciones esperadas.
        if avg_score < 70:
            avg_iters += 1.0
            notes.append("Historial con score < 70 → +1 iteración esperada.")
        expected_iters = round(avg_iters, 1)
        notes.append(f"Proyección basada en {history_features} features previos.")
    else:
        expected_iters = _TIER_BASELINE_ITERS[risk_tier]
        notes.append("Sin historial suficiente (<3 features) → heurística por tier.")

    # Costo: medio histórico si existe, si no por iteración.
    cost_per_iter = _DEFAULT_COST_PER_ITER
    expected_cost = round(expected_iters * cost_per_iter, 4)
    expected_minutes = round(expected_iters * _MINUTES_PER_ITER, 1)

    if risk_tier == "HIGH":
        notes.append("Tier HIGH → revisión humana obligatoria (no auto-merge).")

    return {
        "risk_tier": risk_tier,
        "risk_tier_text": text_tier,
        "risk_tier_path": path_tier,
        "expected_qa_iters": expected_iters,
        "expected_cost_usd": expected_cost,
        "expected_minutes": expected_minutes,
        "based_on_history": based_on_history,
        "history_features": history_features,
        "notes": notes,
    }


def format_estimate(project_id: str, master_plan: str, files_hint: list[str] | None = None) -> str:
    """Render Markdown de la estimación para el CLI / panel del Founder."""
    est = estimate(project_id, master_plan, files_hint)
    lines = [
        "## Dry run — estimación",
        "| Métrica | Proyección |",
        "|---|---|",
        f"| Tier de riesgo | **{est['risk_tier']}** (texto={est['risk_tier_text']}, rutas={est['risk_tier_path']}) |",
        f"| Iteraciones QA esperadas | {est['expected_qa_iters']} |",
        f"| Costo estimado | ${est['expected_cost_usd']:.4f} |",
        f"| Tiempo estimado | ~{est['expected_minutes']} min |",
        f"| Base | {'historial' if est['based_on_history'] else 'heurística'} "
        f"({est['history_features']} features) |",
    ]
    if est["notes"]:
        lines.append("")
        lines.extend(f"- {n}" for n in est["notes"])
    return "\n".join(lines)
