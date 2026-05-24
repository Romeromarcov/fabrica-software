"""
Sistema de Aprendizaje — Nivel 2: Score de Calidad por Feature.

Registra métricas de calidad en cada feature y calcula tendencias.
Si un mismo patrón de bug aparece ≥3 veces, propone actualizar CODING_STANDARDS.md.

Almacenamiento:
  data/runs/[project_id]/quality_metrics.jsonl  — una línea JSON por feature
"""
from __future__ import annotations

import json
import logging
import re
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# Importado dinámicamente para no acoplar con file_tools en el módulo
_RUNS_DIR: Optional[Path] = None


def _get_runs_dir() -> Path:
    global _RUNS_DIR
    if _RUNS_DIR is None:
        try:
            from tools.file_tools import RUNS_DIR
            _RUNS_DIR = RUNS_DIR
        except ImportError:
            _RUNS_DIR = Path("data/runs")
    return _RUNS_DIR


def _metrics_path(project_id: str) -> Path:
    return _get_runs_dir() / project_id / "quality_metrics.jsonl"


# ── Registro de métricas ──────────────────────────────────────────────────────

def record_feature_metrics(
    project_id: str,
    feature_id: str,
    feature_name: str,
    qa_iterations: int,
    secops_iterations: int,
    sandbox_passes: int,       # 1 si pasó al primer intento, 0 si no
    bug_categories: list[str], # categorías extraídas por LearningMemory
    had_rollback: bool = False,
    total_cost_usd: float = 0.0,
    mode: str = "completo",
) -> None:
    """Registra las métricas de un feature completado."""
    if not project_id:
        return

    record = {
        "feature_id":       feature_id,
        "feature_name":     feature_name,
        "date":             datetime.now(timezone.utc).isoformat(),
        "mode":             mode,
        "qa_iterations":    qa_iterations,
        "secops_iterations":secops_iterations,
        "sandbox_passes":   sandbox_passes,
        "bug_categories":   bug_categories,
        "had_rollback":     had_rollback,
        "total_cost_usd":   round(total_cost_usd, 6),
        # Score compuesto: 100 puntos base, penalizar por iteraciones extra
        "quality_score":    max(0, 100
                                - (max(0, qa_iterations - 1) * 15)
                                - (secops_iterations * 10)
                                - (0 if sandbox_passes else 20)
                                - (30 if had_rollback else 0)),
    }

    path = _metrics_path(project_id)
    path.parent.mkdir(parents=True, exist_ok=True)

    try:
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
        logger.info(
            "QualityTracker: feature '%s' → score=%d (QA iters=%d, SecOps iters=%d)",
            feature_name, record["quality_score"], qa_iterations, secops_iterations,
        )
    except Exception as exc:
        logger.error("QualityTracker: error al registrar métricas: %s", exc)


# ── Cálculo de tendencias ─────────────────────────────────────────────────────

def compute_trend(project_id: str, last_n: int = 10) -> dict:
    """
    Calcula tendencias de calidad de los últimos N features.

    Retorna dict con:
      - avg_qa_iters: float
      - avg_score: float
      - direction: "mejorando" | "estable" | "empeorando"
      - top_bug_categories: list[str]
      - total_features: int
      - zero_qa_pct: float   (% de features con 0 iteraciones QA extra)
      - recurring_patterns: list[str]  (categorías que aparecen ≥3 veces)
    """
    path = _metrics_path(project_id)
    if not path.exists():
        return {"total_features": 0, "avg_qa_iters": 0, "avg_score": 0,
                "direction": "sin datos", "top_bug_categories": [],
                "zero_qa_pct": 0.0, "recurring_patterns": []}

    records: list[dict] = []
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line:
                records.append(json.loads(line))
    except Exception as exc:
        logger.error("QualityTracker: error al leer métricas: %s", exc)
        return {}

    total = len(records)
    if total == 0:
        return {"total_features": 0, "avg_qa_iters": 0, "avg_score": 0,
                "direction": "sin datos", "top_bug_categories": [],
                "zero_qa_pct": 0.0, "recurring_patterns": []}

    recent = records[-last_n:]

    # Promedios
    avg_qa_iters = sum(r["qa_iterations"] for r in recent) / len(recent)
    avg_score    = sum(r["quality_score"]  for r in recent) / len(recent)
    zero_qa_pct  = sum(1 for r in recent if r["qa_iterations"] <= 1) / len(recent) * 100

    # Dirección: comparar primera mitad vs segunda mitad
    direction = "estable"
    if len(recent) >= 4:
        mid       = len(recent) // 2
        score_old = sum(r["quality_score"] for r in recent[:mid]) / mid
        score_new = sum(r["quality_score"] for r in recent[mid:]) / (len(recent) - mid)
        diff = score_new - score_old
        if diff > 5:
            direction = "mejorando"
        elif diff < -5:
            direction = "empeorando"

    # Top categorías de bugs (todos los features, no sólo los últimos N)
    all_cats: list[str] = []
    for r in records:
        all_cats.extend(r.get("bug_categories", []))
    cat_counter  = Counter(all_cats)
    top_bugs     = [cat for cat, _ in cat_counter.most_common(5)]
    recurring    = [cat for cat, count in cat_counter.items() if count >= 3]

    return {
        "total_features":      total,
        "avg_qa_iters":        round(avg_qa_iters, 2),
        "avg_score":           round(avg_score, 1),
        "direction":           direction,
        "top_bug_categories":  top_bugs,
        "zero_qa_pct":         round(zero_qa_pct, 1),
        "recurring_patterns":  sorted(recurring),
    }


# ── Propuesta de actualización de estándares ─────────────────────────────────

def propose_standards_update(project_id: str) -> Optional[str]:
    """
    Si hay patrones recurrentes (≥3 features con el mismo tipo de bug),
    retorna un mensaje de propuesta para actualizar CODING_STANDARDS.md.
    Retorna None si no hay nada que proponer.
    """
    trend = compute_trend(project_id, last_n=20)
    recurring = trend.get("recurring_patterns", [])

    if not recurring:
        return None

    lines = [
        "⚠️ **Patrones recurrentes detectados** — se sugiere actualizar "
        "`agents/CODING_STANDARDS.md`:\n"
    ]
    for pattern in recurring:
        lines.append(f"- **{pattern}**: aparece en 3 o más features. "
                     "Agregar regla explícita para prevenir este tipo de error.")
    lines.append(
        "\nEsto reduciría las iteraciones QA promedio. "
        f"Score actual: {trend.get('avg_score', '?')}/100."
    )
    return "\n".join(lines)


# ── Resumen legible para el PR / PM Evaluador ────────────────────────────────

def format_quality_summary(project_id: str, feature_id: str) -> str:
    """
    Retorna un bloque Markdown con el resumen de calidad de este feature
    y la tendencia del proyecto. Para incluir en el post-mortem del PR.
    """
    path = _metrics_path(project_id)
    if not path.exists():
        return ""

    # Leer el registro de este feature específico
    feature_record: Optional[dict] = None
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            r = json.loads(line)
            if r.get("feature_id") == feature_id:
                feature_record = r
        # tomar el último si hay varios (re-runs)
    except Exception:
        return ""

    if not feature_record:
        return ""

    trend = compute_trend(project_id, last_n=10)
    direction_emoji = {
        "mejorando":  "📈",
        "estable":    "➡️",
        "empeorando": "📉",
        "sin datos":  "❓",
    }.get(trend.get("direction", "sin datos"), "❓")

    proposal = propose_standards_update(project_id) or ""

    return (
        "\n## Post-mortem de Calidad\n\n"
        f"| Métrica | Este feature | Promedio proyecto |\n"
        f"|---------|-------------|-------------------|\n"
        f"| Iteraciones QA | {feature_record['qa_iterations']} | {trend.get('avg_qa_iters', '?')} |\n"
        f"| Iteraciones SecOps | {feature_record['secops_iterations']} | — |\n"
        f"| Sandbox pass | {'✅ 1er intento' if feature_record['sandbox_passes'] else '❌ retry'} | — |\n"
        f"| Rollback | {'Sí' if feature_record['had_rollback'] else 'No'} | — |\n"
        f"| Quality Score | **{feature_record['quality_score']}/100** | {trend.get('avg_score', '?')}/100 |\n"
        f"| Costo | ${feature_record['total_cost_usd']:.4f} USD | — |\n\n"
        f"**Tendencia del proyecto ({trend.get('total_features', 0)} features):** "
        f"{direction_emoji} {trend.get('direction', 'sin datos')} · "
        f"{trend.get('zero_qa_pct', 0)}% de features con ≤1 iteración QA\n"
        + (f"\n{proposal}\n" if proposal else "")
    )
