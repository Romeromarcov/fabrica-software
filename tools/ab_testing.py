"""
tools/ab_testing.py — A/B testing de modelos por agente (PLAN_PLATAFORMA_V2 M6, Fase 3).

En un X% de los features, un agente usa un modelo ALTERNATIVO (de sus model_fallbacks
en el registry). Se registra el resultado (iteraciones QA, costo, score) por modelo y
se recomienda el modelo óptimo por rol. Explota la ventaja de "modelo por agente".

Diseño: bucketing DETERMINISTA por hash(feature_id+agent_id) → reproducible y testeable
sin azar. Lógica pura + IO JSONL. Opt-in (`AB_TESTING_ENABLED`); default off → idéntico.
"""
from __future__ import annotations

import hashlib
import json
import logging
from collections import defaultdict
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


def _runs_dir() -> Path:
    try:
        from config import RUNS_DIR
        return Path(RUNS_DIR)
    except ImportError:
        return Path("data/runs")


def _ab_path(project_id: str) -> Path:
    return _runs_dir() / project_id / "ab_results.jsonl"


def _bucket(feature_id: str, agent_id: str) -> float:
    """Devuelve un valor estable en [0,1) por (feature, agente)."""
    h = hashlib.sha256(f"{feature_id}:{agent_id}".encode("utf-8")).hexdigest()
    return (int(h[:8], 16) % 10_000) / 10_000.0


def should_use_variant(feature_id: str, agent_id: str, pct: float) -> bool:
    """True si este (feature, agente) cae en el grupo de variante (pct en [0,1])."""
    if pct <= 0 or not feature_id:
        return False
    if pct >= 1:
        return True
    return _bucket(feature_id, agent_id) < pct


def choose_model(feature_id: str, agent_id: str, primary: str,
                 alternatives: list[str], pct: float) -> tuple[str, bool]:
    """
    Devuelve (modelo_elegido, es_variante). Si cae en el grupo de variante y hay
    alternativas, elige la primera alternativa; si no, el primario.
    """
    if alternatives and should_use_variant(feature_id, agent_id, pct):
        return alternatives[0], True
    return primary, False


def record_result(project_id: str, agent_id: str, model: str, *,
                  qa_iterations: int, cost_usd: float, quality_score: int,
                  is_variant: bool) -> None:
    """Registra el resultado de una corrida con el modelo usado por el agente."""
    if not project_id:
        return
    rec = {
        "agent_id": agent_id, "model": model, "qa_iterations": qa_iterations,
        "cost_usd": round(cost_usd, 6), "quality_score": quality_score,
        "is_variant": is_variant,
    }
    path = _ab_path(project_id)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    except OSError as exc:
        from tools.degradation import best_effort_log
        best_effort_log("Registro A/B de modelos", exc, logger)


def _read(project_id: str) -> list[dict]:
    path = _ab_path(project_id)
    if not path.exists():
        return []
    out = []
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line:
                out.append(json.loads(line))
    except (OSError, ValueError) as exc:
        from tools.degradation import best_effort_log
        best_effort_log("Lectura de resultados A/B", exc, logger)
    return out


def recommend_model(project_id: str, agent_id: str, min_samples: int = 3) -> Optional[dict]:
    """
    Compara los modelos probados para un agente y recomienda el de mayor score medio
    (desempate por menor costo). None si no hay datos suficientes para ≥1 modelo.
    """
    rows = [r for r in _read(project_id) if r.get("agent_id") == agent_id]
    if not rows:
        return None

    by_model: dict[str, list[dict]] = defaultdict(list)
    for r in rows:
        by_model[r["model"]].append(r)

    stats = []
    for model, items in by_model.items():
        if len(items) < min_samples:
            continue
        avg_score = sum(i["quality_score"] for i in items) / len(items)
        avg_cost = sum(i["cost_usd"] for i in items) / len(items)
        avg_iters = sum(i["qa_iterations"] for i in items) / len(items)
        stats.append({"model": model, "samples": len(items),
                      "avg_score": round(avg_score, 1), "avg_cost": round(avg_cost, 6),
                      "avg_qa_iters": round(avg_iters, 2)})
    if not stats:
        return None

    # Mayor score, desempate por menor costo.
    stats.sort(key=lambda s: (-s["avg_score"], s["avg_cost"]))
    best = stats[0]
    return {"agent_id": agent_id, "recommended_model": best["model"],
            "candidates": stats}
