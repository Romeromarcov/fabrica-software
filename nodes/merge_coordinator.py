"""
VI-2 — Merge Coordinator: resuelve conflictos entre ramas de features paralelos.

Flujo de decisión:
  ┌─ Sin conflictos ──────────────────────────────► auto-merge silencioso ✅
  │
  ├─ Conflictos LOW (tests, docs, templates) ─────► LLM propone estrategia → merge
  │
  ├─ Conflictos MEDIUM (views, services, api) ────► LLM propone estrategia → merge / escalar
  │
  └─ Conflictos HIGH (models, settings, migrations)► interrupt() al Founder ⛔
"""
from __future__ import annotations

import json
import logging
import re

from langgraph.types import interrupt

from project_state import ProjectState, FeatureTask
from nodes.base import call_agent
from tools.branch_manager import (
    get_branch_modified_files,
    detect_file_conflicts,
    classify_conflict_severity,
    merge_branch,
    format_conflict_report,
)
from tools.file_tools import save_run_metadata, RUNS_DIR
from config import MODEL_A6

logger = logging.getLogger(__name__)


def _derive_branch_name(feature_id: str, feature_name: str) -> str:
    """Construye el nombre de rama con la misma convención que A11/git_tools."""
    slug = feature_name[:20].replace(" ", "_").lower()
    return f"feature/{feature_id[:8]}-{slug}"[:50]


def merge_coordinator(state: ProjectState) -> dict:
    """
    Nodo VI-2: gestiona el merge de las ramas del batch paralelo.

    1. Recopila los nombres de rama del batch actual.
    2. Detecta archivos modificados por cada rama (git diff).
    3. Clasifica la severidad de los conflictos.
    4. Decide auto-merge, LLM-resolve o escalado al Founder.
    """
    batch_indices: list[int] = state.get("parallel_batch", [])
    backlog = list(state["backlog"])
    repo_path = state.get("repo_path", "")

    if not batch_indices or not repo_path:
        logger.debug("merge_coordinator: nada que hacer (batch vacío o sin repo)")
        return {}

    # ── Mapear feature → rama ─────────────────────────────────────────────────
    feature_to_branch: dict[str, str] = {}
    for idx in batch_indices:
        f = backlog[idx]
        fid = f.get("feature_id")
        if not fid:
            continue
        branch = _derive_branch_name(fid, f["name"])
        feature_to_branch[f["name"]] = branch

    if not feature_to_branch:
        logger.info("merge_coordinator: sin ramas con feature_id — saltando")
        return {}

    # ── Detectar archivos modificados ─────────────────────────────────────────
    branch_files: dict[str, list[str]] = {}
    for feat_name, branch in feature_to_branch.items():
        files = get_branch_modified_files(branch, repo_path)
        branch_files[feat_name] = files
        logger.info(
            "merge_coordinator: %s (%s) → %d archivos",
            feat_name, branch, len(files),
        )

    # ── Detectar conflictos ───────────────────────────────────────────────────
    conflicts = detect_file_conflicts(branch_files)
    severity  = classify_conflict_severity(conflicts)
    report    = format_conflict_report(conflicts, branch_files, severity)

    # ── F4.2: el TIER del lote gobierna el merge (no solo el conflicto de archivos) ──
    from tools.risk_classifier import batch_tier as _batch_tier
    texts = [
        f"{backlog[idx].get('name','')} {backlog[idx].get('description','')} "
        f"{backlog[idx].get('acceptance_criteria','')}"
        for idx in batch_indices
    ]
    tier = _batch_tier(texts)
    # Defensa en profundidad: un lote con feature HIGH nunca se auto-fusiona en silencio
    # (F4.1 ya los serializa, pero si llegara uno → escalar a humano).
    if tier == "HIGH" and severity in ("NONE", "LOW", "MEDIUM"):
        logger.warning("merge_coordinator: tier de lote HIGH → forzando escalado a humano")
        severity = "HIGH"

    save_run_metadata(state["project_id"], {
        "merge_coordinator": {
            "batch_features": list(feature_to_branch.keys()),
            "conflicts":      len(conflicts),
            "severity":       severity,
            "batch_tier":     tier,
        }
    })

    logger.info(
        "merge_coordinator: %d conflictos (severidad %s) en batch de %d features",
        len(conflicts), severity, len(batch_indices),
    )

    # ══════════════════════════════════════════════════════════════════════════
    # CASO 1: Sin conflictos → auto-merge
    # ══════════════════════════════════════════════════════════════════════════
    if severity == "NONE":
        # F4.2: solo el tier LOW se auto-fusiona en silencio. Un lote MEDIUM se fusiona
        # pero se NOTIFICA (transparencia; el merge es reversible — R-PROD-4).
        if tier == "MEDIUM":
            logger.info("merge_coordinator: 🟡 sin conflictos pero tier MEDIUM — merge con aviso")
            _notify_telegram_conflict(
                state, "Lote MEDIUM sin conflictos de archivo — merge automático con aviso.", "MEDIUM"
            )
        else:
            logger.info("merge_coordinator: ✅ sin conflictos (tier LOW) — auto-merge")
        _do_merge_all(feature_to_branch, repo_path)
        return {}

    # ══════════════════════════════════════════════════════════════════════════
    # CASO 2: Conflictos HIGH → escalar al Founder
    # ══════════════════════════════════════════════════════════════════════════
    if severity == "HIGH":
        logger.warning("merge_coordinator: 🔴 conflictos HIGH — escalando al Founder")
        _notify_telegram_conflict(state, report, severity)

        founder_input: str = interrupt({
            "tipo":        "merge_conflict_high",
            "mensaje":     (
                f"\n{'='*60}\n"
                f"🔴 CONFLICTO DE MERGE CRÍTICO — {state['project_name']}\n"
                f"{'='*60}\n\n"
                f"{report}\n\n"
                f"Los archivos afectados son críticos (models / settings / migrations).\n"
                f"Resolución manual requerida antes de continuar.\n\n"
                f"Opciones:\n"
                f"  RESOLVER — confirmás que resolviste el conflicto manualmente\n"
                f"  CANCELAR — descartamos las ramas con conflicto y continuamos\n"
            ),
            "project_id":  state["project_id"],
        })

        decision = founder_input.strip().upper()
        save_run_metadata(state["project_id"], {"merge_conflict_decision": decision})

        if decision == "RESOLVER":
            return {"merge_conflict_resolved": True}

        # CANCELAR: marcar las ramas conflictivas como fallidas
        conflict_branches = {b for c in conflicts for b in c["branches"]}
        updated_backlog = list(backlog)
        for idx in batch_indices:
            f = updated_backlog[idx]
            if f["name"] in conflict_branches:
                updated_backlog[idx] = FeatureTask(
                    **{**f, "status": "failed",
                       "evaluation_notes": "Descartado — conflicto de merge HIGH sin resolver"}
                )
        return {"backlog": updated_backlog, "merge_conflict_resolved": False}

    # ══════════════════════════════════════════════════════════════════════════
    # CASO 3: Conflictos LOW / MEDIUM → LLM propone estrategia
    # ══════════════════════════════════════════════════════════════════════════
    logger.info("merge_coordinator: 🟡 conflictos %s — consultando LLM", severity)

    task = f"""
Eres el Merge Coordinator del pipeline de Fábrica de Software.

## SITUACIÓN
Dos features corrieron en paralelo y sus ramas tocan archivos en común.
Debes proponer la estrategia de merge menos destructiva.

## REPORTE DE CONFLICTOS
{report}

## PROYECTO
{state['project_name']} | {repo_path}

## TU TAREA

1. Analiza qué archivos están en conflicto y por qué es esperable o inesperado.
2. Propón la estrategia:
   - **SECUENCIAL**: mergear una rama y luego la otra (git resuelve automáticamente).
     Indica el orden: primero `{list(feature_to_branch.keys())[0]}` o
     primero `{list(feature_to_branch.keys())[-1]}`.
   - **SELECTIVO**: para cada archivo en conflicto, indicar qué rama tiene la versión
     correcta y quedarse con esa.
   - **ESCALAR**: el conflicto es demasiado complejo — requiere revisión humana.

Al final escribe EXACTAMENTE una de:
  `ESTRATEGIA: SECUENCIAL <nombre_feature_primero>`
  `ESTRATEGIA: SELECTIVO`
  `ESTRATEGIA: ESCALAR`
"""

    output, cost = call_agent(
        agent_key="a1_pm",
        agent_label="Merge Coordinator LLM",
        task_content=task,
        model=MODEL_A6,
        include_static=[],
        repo_path=repo_path,
    )

    strategy_m = re.search(
        r"ESTRATEGIA:\s*(SECUENCIAL|SELECTIVO|ESCALAR)(?:\s+(.+))?",
        output, re.IGNORECASE,
    )
    strategy  = strategy_m.group(1).upper() if strategy_m else "SECUENCIAL"
    first_feat = strategy_m.group(2).strip() if strategy_m and strategy_m.group(2) else None

    logger.info("merge_coordinator: estrategia LLM = %s (primero=%s)", strategy, first_feat)

    if strategy == "ESCALAR":
        _notify_telegram_conflict(state, report, severity)
        founder_input = interrupt({
            "tipo":       "merge_conflict_medium",
            "mensaje":    (
                f"🟡 CONFLICTO DE MERGE — {state['project_name']}\n\n"
                f"{report}\n\n"
                f"Análisis del agente:\n{output[:600]}\n\n"
                f"RESOLVER (resolviste manualmente) / CANCELAR (descartar ramas)"
            ),
            "project_id": state["project_id"],
        })
        decision = founder_input.strip().upper()
        if decision != "RESOLVER":
            conflict_branches = {b for c in conflicts for b in c["branches"]}
            updated = list(backlog)
            for idx in batch_indices:
                f = updated[idx]
                if f["name"] in conflict_branches:
                    updated[idx] = FeatureTask(
                        **{**f, "status": "failed",
                           "evaluation_notes": "Descartado — conflicto escalado"}
                    )
            return {"backlog": updated, "merge_conflict_resolved": False, "cost_entries": [cost]}
        return {"merge_conflict_resolved": True, "cost_entries": [cost]}

    # SECUENCIAL o SELECTIVO: intentar merge en orden
    ordered_features = list(feature_to_branch.items())
    if strategy == "SECUENCIAL" and first_feat:
        # Reordenar: el feature preferido va primero
        ordered_features.sort(key=lambda x: 0 if first_feat.lower() in x[0].lower() else 1)

    merge_results = []
    for feat_name, branch in ordered_features:
        result = merge_branch(branch, repo_path)
        merge_results.append({
            "feature": feat_name,
            "branch":  branch,
            "success": result["success"],
            "output":  result["output"][:300],
        })
        if result["success"]:
            logger.info("merge_coordinator: ✅ %s mergeado", branch)
        else:
            logger.warning(
                "merge_coordinator: ⚠️ merge de %s falló tras estrategia %s",
                branch, strategy,
            )

    save_run_metadata(state["project_id"], {
        "merge_strategy":  strategy,
        "merge_results":   merge_results,
    })

    return {
        "merge_conflict_resolved": True,
        "cost_entries":            [cost],
    }


# ── Helpers ───────────────────────────────────────────────────────────────────

def _do_merge_all(feature_to_branch: dict[str, str], repo_path: str) -> None:
    """Hace merge de todas las ramas en orden sin LLM."""
    for feat_name, branch in feature_to_branch.items():
        result = merge_branch(branch, repo_path)
        if result["success"]:
            logger.info("merge_coordinator: ✅ auto-merge %s", branch)
        else:
            logger.warning(
                "merge_coordinator: ⚠️ auto-merge %s falló: %s",
                branch, result["output"][:200],
            )


def _notify_telegram_conflict(state: ProjectState, report: str, severity: str) -> None:
    """Notifica al Founder por Telegram sobre el conflicto."""
    try:
        from tools.telegram import send_message
        icon = "🔴" if severity == "HIGH" else "🟡"
        send_message(
            f"{icon} *Merge Coordinator — Conflicto {severity}*\n"
            f"*Proyecto:* {state['project_name']}\n"
            f"{report[:400]}\n"
            f"Intervención requerida."
        )
    except Exception:
        pass  # Best-effort
