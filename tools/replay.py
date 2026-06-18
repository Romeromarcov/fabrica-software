"""
tools/replay.py — Replay y debugging de pipelines (PLAN_PLATAFORMA_V2 M2, Fase 1).

Cada feature persiste artefactos navegables en `RUNS_DIR/<feature_id>/`:
  - `output_<nodo>.md` por cada agente que produjo salida (checkpoints).
  - `metadata.json` (estado/costos/risk).
  - `MASTER_PLAN.md`.

Este módulo permite inspeccionar esos checkpoints y calcular un PLAN DE REPLAY:
qué nodos se re-ejecutarían desde un punto dado (`--from <nodo>`). La re-ejecución
real (que requiere LLM en vivo) se dispara desde el CLI/grafo; aquí vive la lógica
pura y verificable offline.
"""
from __future__ import annotations

import logging
from pathlib import Path

logger = logging.getLogger(__name__)


def _runs_dir() -> Path:
    from config import RUNS_DIR
    return Path(RUNS_DIR)


def _run_dir(feature_id: str) -> Path:
    return _runs_dir() / feature_id


def canonical_node_order() -> list[str]:
    """Orden canónico de nodos del pipeline software (desde el registry data-driven)."""
    try:
        from graph_builder import build_pipeline_spec
        spec = build_pipeline_spec("software")
        return [a["node_name"] for a in spec["agents"] if a.get("node_name")]
    except Exception as exc:  # noqa: BLE001 — fallback explícito si el registry no carga
        logger.warning("replay: no se pudo leer el orden del registry (%s); fallback", exc)
        return [
            "a1_planificador", "a2_db", "a3_mcp", "a4_backend", "a5_frontend",
            "a6_refactor", "a7_qa", "a8_secops", "a10_code_writer", "a9_sandbox",
            "a85_adversarial", "a11_devops",
        ]


def list_checkpoints(feature_id: str) -> list[str]:
    """Nodos que tienen salida guardada (`output_<nodo>.md`) para este feature."""
    run_dir = _run_dir(feature_id)
    if not run_dir.exists():
        return []
    return sorted(p.stem.replace("output_", "") for p in run_dir.glob("output_*.md"))


def load_run_state(feature_id: str) -> dict:
    """
    Reconstruye un estado PARCIAL del feature desde los artefactos en disco:
    metadata + outputs por nodo + master_plan. No ejecuta nada.
    """
    run_dir = _run_dir(feature_id)
    if not run_dir.exists():
        raise FileNotFoundError(f"Feature '{feature_id}' no encontrado en {run_dir}")

    state: dict = {"feature_id": feature_id}

    meta_path = run_dir / "metadata.json"
    if meta_path.exists():
        import json
        try:
            state["metadata"] = json.loads(meta_path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            logger.warning("replay: metadata ilegible (%s)", exc)
            state["metadata"] = {}

    mp_path = run_dir / "MASTER_PLAN.md"
    if mp_path.exists():
        state["master_plan"] = mp_path.read_text(encoding="utf-8")

    outputs: dict[str, str] = {}
    for p in sorted(run_dir.glob("output_*.md")):
        outputs[p.stem.replace("output_", "")] = p.read_text(encoding="utf-8")
    state["outputs"] = outputs
    return state


def replay_plan(feature_id: str, from_node: str) -> dict:
    """
    Calcula el plan de replay desde `from_node`.

    Returns:
      {
        "from_node": str,
        "to_rerun": [nodos desde from_node en adelante],
        "reused": [nodos previos cuyo checkpoint se reutiliza],
        "available_checkpoints": [...],
        "valid": bool,   # from_node está en el orden canónico
      }
    """
    order = canonical_node_order()
    checkpoints = set(list_checkpoints(feature_id))

    if from_node not in order:
        return {
            "from_node": from_node, "to_rerun": [], "reused": [],
            "available_checkpoints": sorted(checkpoints), "valid": False,
            "error": f"'{from_node}' no es un nodo del pipeline software",
        }

    idx = order.index(from_node)
    to_rerun = order[idx:]
    reused = [n for n in order[:idx] if n in checkpoints]
    return {
        "from_node": from_node,
        "to_rerun": to_rerun,
        "reused": reused,
        "available_checkpoints": sorted(checkpoints),
        "valid": True,
    }


def format_replay_plan(feature_id: str, from_node: str) -> str:
    """Render legible del plan de replay para el CLI."""
    plan = replay_plan(feature_id, from_node)
    if not plan["valid"]:
        return f"❌ {plan.get('error', 'nodo inválido')}\nCheckpoints: {plan['available_checkpoints']}"
    lines = [
        f"## Plan de replay — feature {feature_id}",
        f"Desde: {plan['from_node']}",
        f"Reutiliza checkpoints: {', '.join(plan['reused']) or '(ninguno)'}",
        f"Re-ejecuta: {' → '.join(plan['to_rerun'])}",
    ]
    return "\n".join(lines)
