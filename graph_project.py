"""
Grafo del Project Loop — orquesta múltiples runs del pipeline de features.

Flujo:
  A0 (Arquitecto) → Human aprueba roadmap → LOOP {
    pick_next_feature → run_feature_pipeline → pm_evaluador → advance_index
    → [arch_review? cada ARCH_REVIEW_INTERVAL features] → a0_revisor
    → check_backlog
  } → present_suggestions → project_complete (o loop de nuevo si hay más)

Dos niveles de control de calidad:
  • pm_evaluador: "¿cumplió este feature lo que A1 planificó?" (cada feature)
  • a0_revisor:   "¿sigue el proyecto alineado con la visión arquitectónica de A0?"
                  (cada N features configurable, default 3)
"""
from __future__ import annotations
import json
import logging
from datetime import datetime

from langgraph.graph import StateGraph, END
from langgraph.types import interrupt

from project_state import ProjectState, FeatureTask
from config import PARALLEL_WORKTREE_ISOLATION
from tools.file_tools import save_run_metadata, RUNS_DIR

logger = logging.getLogger(__name__)


# ── Nodos de agente ───────────────────────────────────────────────────────────

from nodes.a0_arquitecto    import a0_arquitecto
from nodes.a0_revisor       import a0_revisor
from nodes.pm_evaluador     import pm_evaluador
from nodes.merge_coordinator import merge_coordinator


# ── Human checkpoint: aprobación del roadmap ─────────────────────────────────

def human_approve_roadmap(state: ProjectState) -> dict:
    """Suspende el loop hasta que el Founder apruebe el roadmap generado por A0."""
    save_run_metadata(state["project_id"], {
        "project_status": "awaiting_approval",
        "roadmap_ready_at": datetime.utcnow().isoformat(),
    })

    # Notificar al Founder por Telegram con los comandos para responder
    try:
        from tools.telegram import notify_approval_needed
        notify_approval_needed(
            project_name=state["project_name"],
            project_id=state["project_id"],
            interrupt_type="project_roadmap_approval",
        )
    except Exception:
        pass  # La notificación es best-effort

    founder_input: str = interrupt({
        "tipo": "project_roadmap_approval",
        "mensaje": (
            f"\n{'='*60}\n"
            f"📐 ROADMAP generado para: {state['project_name']}\n"
            f"📦 Repo: {state['repo_name']}\n"
            f"{'='*60}\n\n"
            f"Fases:    {len(state.get('phases', []))}\n"
            f"Features: {len(state.get('backlog', []))}\n\n"
            f"Lee el roadmap en data/runs/{state['project_id']}/metadata.json\n\n"
            f"Para aprobar y lanzar el Project Loop escribe EXACTAMENTE:\n"
            f'  "Roadmap aprobado. Iniciar proyecto."\n\n'
            f"O escribe CANCELAR para detener."
        ),
        "project_id": state["project_id"],
    })

    aprobado = founder_input.strip() == "Roadmap aprobado. Iniciar proyecto."

    save_run_metadata(state["project_id"], {
        "project_status": "running" if aprobado else "cancelled",
        "approved_at": datetime.utcnow().isoformat() if aprobado else None,
    })

    return {
        "founder_approved_roadmap": aprobado,
        "project_status": "running" if aprobado else "failed",
    }


# ── Nodo: seleccionar siguiente feature del backlog ───────────────────────────

def pick_next_feature(state: ProjectState) -> dict:
    """Selecciona el siguiente feature pendiente del backlog."""
    from tools.branch_manager import blocked_feature_indices

    backlog = state.get("backlog", [])
    dep_graph = state.get("dependency_graph", {})

    # B3.1: features pendientes con dependencias fallidas/escaladas → bloqueados.
    blocked = blocked_feature_indices(backlog, dep_graph)

    # BUG-005: buscar desde el inicio del backlog (no desde current_feature_index)
    # para no perderse features que quedaron en "pending" por reordenación
    for i in range(len(backlog)):
        if backlog[i]["status"] == "pending":
            # A3.4: los features importados sin aprobar no se ejecutan (anti prompt-injection).
            if backlog[i].get("pending_approval"):
                logger.info("Project Loop: feature '%s' importado pendiente de aprobación — omitido",
                            backlog[i].get("name", "?"))
                continue
            # B3.1: no arrancar features cuya base depende de algo fallido/escalado.
            if i in blocked:
                logger.warning(
                    "B3.1: feature '%s' bloqueado por dependencia(s) fallida(s): %s — omitido",
                    backlog[i].get("name", "?"), ", ".join(blocked[i]),
                )
                continue
            updated = list(backlog)
            updated[i] = FeatureTask(**{**backlog[i], "status": "running"})
            logger.info("Project Loop: iniciando feature %d/%d — %s", i+1, len(backlog), backlog[i]["name"])
            save_run_metadata(state["project_id"], {
                "current_feature": backlog[i]["name"],
                "current_feature_index": i,
                "project_status": "running",
            })
            return {"backlog": updated, "current_feature_index": i}

    # No hay más features pendientes (o las que quedan están bloqueadas por B3.1)
    return {"current_feature_index": len(backlog)}


# ── Nodo: ejecutar el pipeline de un feature ─────────────────────────────────

def run_feature_pipeline(state: ProjectState) -> dict:
    """
    Ejecuta el pipeline completo (graph.py) para el feature actual.
    Corre en el mismo proceso usando compile_graph_project_mode().
    """
    from state import initial_state
    from graph import compile_graph_project_mode
    from datetime import datetime

    idx     = state["current_feature_index"]
    backlog = list(state["backlog"])
    feature = backlog[idx]

    # Generar feature_id
    slug = feature["name"][:20].replace(" ", "_").lower()
    feature_id = f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{slug}"

    logger.info("run_feature_pipeline: %s → %s", feature["name"], feature_id)

    # Crear estado inicial del feature
    feat_state = initial_state(
        feature_id=feature_id,
        feature_name=feature["name"],
        mode=feature.get("suggested_mode", "auto"),
        repo_name=state["repo_name"],
        repo_path=state["repo_path"],
        project_mode=True,
        project_id=state["project_id"],
    )

    # Construir spec completa del A0 para este feature (G4/G5 anti-alucinaciones)
    a0_spec = (
        f"Nombre: {feature['name']}\n"
        f"Descripción: {feature.get('description', '')}\n"
        f"Fase: {feature.get('phase', '')}\n"
        f"Criterios de aceptación: {feature.get('acceptance_criteria', '')}\n"
        f"Modo sugerido: {feature.get('suggested_mode', 'auto')}"
    )

    feat_state = {
        **feat_state,
        "feature_name":    feature["name"],  # nombre limpio, sin truncar
        "a0_feature_spec": a0_spec,          # spec completa de A0, inyectada en A1
    }

    # Compilar y ejecutar
    feat_app = compile_graph_project_mode()
    config   = {"configurable": {"thread_id": feature_id}}

    final_status = "completed"
    try:
        for chunk in feat_app.stream(feat_state, config=config, stream_mode="updates"):
            node_name = list(chunk.keys())[0]
            if node_name == "__interrupt__":
                # Solo qa_escalation puede interrumpir en modo proyecto
                interrupt_data = chunk[node_name][0].value
                logger.warning("BLOQUEANTE en project mode: %s", interrupt_data.get("tipo"))
                final_status = "failed"
                # Guardar el bloqueante en el proyecto
                save_run_metadata(state["project_id"], {
                    "blocker": {
                        "feature": feature["name"],
                        "feature_id": feature_id,
                        "tipo": interrupt_data.get("tipo"),
                        "at": datetime.utcnow().isoformat(),
                    }
                })
                break

        # BUG-017: pequeño margen para que a1_pr_final termine de escribir metadata.json
        import time as _time
        _time.sleep(1)

        # Verificar status final del feature
        meta_path = RUNS_DIR / feature_id / "metadata.json"
        if meta_path.exists():
            meta = json.loads(meta_path.read_text())
            if meta.get("status") == "detenido":
                final_status = "failed"

    except Exception as e:
        logger.exception("Error ejecutando feature %s: %s", feature_id, e)
        final_status = "failed"

    # Actualizar backlog con el feature_id.
    # BUG-004: dejamos "running" (no "pending") para que si pm_evaluador falla,
    # el feature no sea re-ejecutado indefinidamente.
    # pm_evaluador actualiza el estado a "completed" o "failed".
    backlog[idx] = FeatureTask(**{
        **feature,
        "feature_id": feature_id,
        "status": final_status if final_status == "failed" else "running",
    })

    cost_entries = []
    meta_path = RUNS_DIR / feature_id / "metadata.json"
    try:
        run_meta = json.loads(meta_path.read_text())
        cost_usd = run_meta.get("total_cost_usd", 0)
        cost_entries = [{"agent": feature["name"], "cost_usd": cost_usd}]
    except Exception:
        pass

    return {
        "backlog": backlog,
        "cost_entries": cost_entries,
    }


# ── Nodo: avanzar el índice tras evaluación ───────────────────────────────────

def advance_index(state: ProjectState) -> dict:
    """Incrementa el índice tras completar un feature (run + evaluación)."""
    return {"current_feature_index": state["current_feature_index"] + 1}


# ── Human checkpoint: sugerencias al final del backlog ───────────────────────

def present_suggestions(state: ProjectState) -> dict:
    """
    Se activa cuando el backlog se vacía.
    Muestra el resumen y sugerencias del PM. Notifica por Telegram al Founder.
    """
    from tools.telegram import notify_suggestions

    completed = sum(1 for f in state["backlog"] if f["status"] == "completed")
    failed    = sum(1 for f in state["backlog"] if f["status"] == "failed")
    total     = len(state["backlog"])
    sug_text  = "\n".join(state.get("suggestions", [])) or "Ninguna"

    save_run_metadata(state["project_id"], {
        "project_status":  "awaiting_suggestions_review",
        "final_completed": completed,
        "final_failed":    failed,
    })

    # Notificar al Founder por Telegram antes de suspender (incluye comandos)
    notify_suggestions(
        project_name=state["project_name"],
        suggestions=state.get("suggestions", []),
        project_id=state["project_id"],
    )

    founder_input: str = interrupt({
        "tipo": "project_suggestions",
        "mensaje": (
            f"\n{'='*60}\n"
            f"🏁 BACKLOG COMPLETADO — {state['project_name']}\n"
            f"{'='*60}\n"
            f"  ✓ Completados: {completed}/{total}\n"
            f"  ✗ Fallidos:    {failed}/{total}\n"
            f"  💰 Costo total: ${sum(e.get('cost_usd',0) for e in state.get('cost_entries',[])):.4f} USD\n\n"
            f"SUGERENCIAS DEL PM:\n{sug_text}\n\n"
            f"Opciones:\n"
            f"  CONTINUAR — añadir sugerencias al backlog y seguir\n"
            f"  CERRAR    — marcar el proyecto como completado\n"
            f"  PAUSA     — pausar y revisar manualmente"
        ),
        "project_id": state["project_id"],
        "suggestions": state.get("suggestions", []),
    })

    decision = founder_input.strip().upper()

    save_run_metadata(state["project_id"], {
        "founder_suggestions_decision": decision,
    })

    if decision == "CONTINUAR" and state.get("suggestions"):
        # Convertir sugerencias en nuevos FeatureTasks y añadir al backlog
        new_tasks: list[FeatureTask] = []
        for i, sug in enumerate(state["suggestions"]):
            # Parsear "SUGERENCIA-001: nombre — descripción — Prioridad: alta"
            parts = sug.split("—")
            name  = parts[0].split(":", 1)[-1].strip() if parts else sug[:50]
            desc  = parts[1].strip() if len(parts) > 1 else ""
            prio  = 5 + i
            new_tasks.append(FeatureTask(
                name=name,
                description=desc,
                phase="Sugerencias del PM",
                priority=prio,
                suggested_mode="auto",
                acceptance_criteria="",
                depends_on=[],        # VI-1: sugerencias no tienen dependencias explícitas
                feature_id=None,
                status="pending",
                evaluation_notes=None,
            ))

        updated_backlog = list(state["backlog"]) + new_tasks
        return {
            "backlog": updated_backlog,
            "suggestions": [],
            "project_status": "running",
        }

    elif decision == "CERRAR":
        return {"project_status": "completed"}
    else:
        return {"project_status": "paused"}


# ── Nodo terminal ─────────────────────────────────────────────────────────────

def project_complete(state: ProjectState) -> dict:
    from tools.telegram import notify_project_done, send_message

    completed = sum(1 for f in state["backlog"] if f["status"] == "completed")
    total     = len(state["backlog"])
    cost      = sum(e.get("cost_usd", 0) for e in state.get("cost_entries", []))
    status    = state.get("project_status", "completed")

    save_run_metadata(state["project_id"], {
        "project_status":     status,
        "completed_at":       datetime.utcnow().isoformat(),
        "features_completed": completed,
        "features_total":     total,
        "total_cost_usd":     round(cost, 6),
    })

    logger.info(
        "Proyecto %s → %s: %d/%d features | $%.4f",
        state["project_name"], status, completed, total, cost,
    )

    # I-06: diferenciar mensaje según si fue cancelado o completado
    if status in ("cancelled", "failed") or not state.get("founder_approved_roadmap"):
        send_message(
            f"❌ *Proyecto cancelado*\n"
            f"*Proyecto:* {state['project_name']}\n"
            f"El roadmap fue rechazado o el proyecto fue cancelado antes de iniciar."
        )
    else:
        notify_project_done(
            project_name=state["project_name"],
            completed=completed,
            total=total,
            cost_usd=cost,
        )
    return {}


# ── VI-2: Nodos del path paralelo ────────────────────────────────────────────

def pick_ready_features(state: ProjectState) -> dict:
    """
    VI-2: Selecciona hasta MAX_PARALLEL_FEATURES features listos
    (status=pending + dependencias cumplidas) y los marca como 'running'.
    Devuelve parallel_batch con los índices seleccionados.
    """
    from config import MAX_PARALLEL_FEATURES
    from tools.branch_manager import get_ready_indices
    from tools.risk_classifier import select_parallel_safe, classify_text_risk

    backlog    = state.get("backlog", [])
    dep_graph  = state.get("dependency_graph", {})
    indices    = get_ready_indices(backlog, dep_graph, max_parallel=MAX_PARALLEL_FEATURES)

    if not indices:
        logger.info("pick_ready_features: sin features listos (dependencias pendientes)")
        return {"parallel_batch": [], "current_feature_index": len(backlog)}

    # F4.1: ningún feature tier HIGH corre en paralelo. Se calcula el tier por el
    # texto del feature (mismo clasificador de la Fase 3) y se serializan los HIGH.
    def _tier_of(i: int) -> str:
        f = backlog[i]
        return classify_text_risk(
            f"{f.get('name','')} {f.get('description','')} {f.get('acceptance_criteria','')}"
        )

    safe_indices = select_parallel_safe(indices, _tier_of)
    if safe_indices != indices:
        deferred = [backlog[i]["name"] for i in indices if i not in safe_indices]
        logger.info("F4.1: HIGH serializado — lote=%s · diferidos=%s",
                    [backlog[i]["name"] for i in safe_indices], deferred)
    indices = safe_indices

    updated = list(backlog)
    for i in indices:
        updated[i] = FeatureTask(**{**backlog[i], "status": "running"})

    names = [backlog[i]["name"] for i in indices]
    logger.info("Parallel batch (%d): %s", len(indices), names)
    save_run_metadata(state["project_id"], {
        "parallel_batch":  names,
        "project_status":  "running",
    })
    return {
        "backlog":                updated,
        "parallel_batch":         indices,
        "current_feature_index":  indices[0],
    }


def run_parallel_batch(state: ProjectState) -> dict:
    """
    VI-2: Ejecuta el batch de features en paralelo usando ThreadPoolExecutor.
    Cada feature corre su propio pipeline (graph.py) en un hilo independiente.
    """
    from concurrent.futures import ThreadPoolExecutor, as_completed
    from state import initial_state
    from graph import compile_graph_project_mode
    from datetime import datetime as _dt

    indices = state.get("parallel_batch", [])
    if not indices:
        return {}

    # F4.3 / CTF-FABRICA-001: cada feature paralelo corre en su propio git worktree
    # (ver _run_one). Si el aislamiento está desactivado, se avisa de la carrera.
    if len(indices) > 1 and not PARALLEL_WORKTREE_ISOLATION:
        logger.warning(
            "F4.3: %d features en paralelo con aislamiento por worktree DESACTIVADO "
            "(riesgo de carrera en A10). Activar PARALLEL_WORKTREE_ISOLATION.",
            len(indices),
        )

    backlog = list(state["backlog"])

    def _run_one(idx: int):
        feature    = backlog[idx]
        slug       = feature["name"][:20].replace(" ", "_").lower()
        feature_id = f"{_dt.now().strftime('%Y%m%d_%H%M%S')}_{slug}"

        # CTF-FABRICA-001: aislar cada feature en su propio git worktree para que dos
        # A10 concurrentes no se pisen los archivos. La rama usa la nomenclatura
        # compartida con el Merge Coordinator y se pre-setea en el state para que
        # a1_pr_final commitee en ella (y no cree otra). Fallback: repo compartido.
        run_repo   = state["repo_path"]
        pre_branch = ""
        if PARALLEL_WORKTREE_ISOLATION and len(indices) > 1:
            try:
                from tools.worktree import create_worktree
                from tools.branch_naming import feature_branch_name
                branch = feature_branch_name(feature_id, feature["name"])
                wt = create_worktree(state["repo_path"], branch, feature_id)
                if wt:
                    run_repo, pre_branch = wt, branch
                    logger.info("worktree aislado para '%s' → %s", feature["name"], wt)
                else:
                    logger.warning("worktree no disponible para '%s' — repo compartido", feature["name"])
            except Exception as _wt_exc:  # noqa: BLE001
                logger.warning("worktree falló (%s) — repo compartido", _wt_exc)

        a0_spec = (
            f"Nombre: {feature['name']}\n"
            f"Descripción: {feature.get('description', '')}\n"
            f"Fase: {feature.get('phase', '')}\n"
            f"Criterios de aceptación: {feature.get('acceptance_criteria', '')}\n"
            f"Modo sugerido: {feature.get('suggested_mode', 'auto')}"
        )
        feat_state = initial_state(
            feature_id=feature_id,
            feature_name=feature["name"],
            mode=feature.get("suggested_mode", "auto"),
            repo_name=state["repo_name"],
            repo_path=run_repo,
            project_mode=True,
            project_id=state["project_id"],
        )
        feat_state = {
            **feat_state,
            "feature_name":    feature["name"],
            "a0_feature_spec": a0_spec,
            # rama pre-creada por el worktree → a1_pr_final commitea en ella
            "feature_branch":  pre_branch,
        }

        # Cada hilo compila su propia instancia del grafo
        # (evita compartir conexión SQLite entre hilos)
        feat_app = compile_graph_project_mode()
        config   = {"configurable": {"thread_id": feature_id}}

        final_status = "completed"
        try:
            for chunk in feat_app.stream(feat_state, config=config, stream_mode="updates"):
                node_name = list(chunk.keys())[0]
                if node_name == "__interrupt__":
                    final_status = "failed"
                    break

            import time as _t
            _t.sleep(1)  # Margen para que a1_pr_final termine de escribir metadata

            meta_path = RUNS_DIR / feature_id / "metadata.json"
            if meta_path.exists():
                meta = json.loads(meta_path.read_text())
                if meta.get("status") == "detenido":
                    final_status = "failed"

        except Exception as e:
            logger.exception("run_parallel_batch: error en %s: %s", feature["name"], e)
            final_status = "failed"

        return idx, feature_id, final_status

    # ── Lanzar en paralelo ────────────────────────────────────────────────────
    results: dict[int, tuple[str, str]] = {}
    with ThreadPoolExecutor(max_workers=max(1, len(indices))) as executor:
        future_map = {executor.submit(_run_one, idx): idx for idx in indices}
        for future in as_completed(future_map):
            try:
                idx, feature_id, status = future.result()
                results[idx] = (feature_id, status)
            except Exception as exc:
                idx = future_map[future]
                logger.exception("run_parallel_batch: futuro falló para idx=%d: %s", idx, exc)
                results[idx] = ("error", "failed")

    # ── Actualizar backlog ────────────────────────────────────────────────────
    cost_entries = []
    for idx, (feature_id, final_status) in results.items():
        backlog[idx] = FeatureTask(**{
            **backlog[idx],
            "feature_id": feature_id,
            # "running" si completado (pm_evaluador decidirá), "failed" si explotó
            "status": final_status if final_status == "failed" else "running",
        })
        try:
            meta = json.loads((RUNS_DIR / feature_id / "metadata.json").read_text())
            cost_entries.append({
                "agent":    backlog[idx]["name"],
                "cost_usd": meta.get("total_cost_usd", 0),
            })
        except Exception:
            pass

    return {"backlog": backlog, "cost_entries": cost_entries}


def advance_parallel_batch(state: ProjectState) -> dict:
    """
    VI-2: Cierra el batch paralelo.
    - Marca los features 'running' como 'completed'.
    - Limpia parallel_batch.
    - Recalcula progreso.
    """
    batch_indices = state.get("parallel_batch", [])
    backlog       = list(state["backlog"])
    total         = len(backlog)

    for idx in batch_indices:
        f = backlog[idx]
        if f.get("status") == "running":
            backlog[idx] = FeatureTask(**{**f, "status": "completed"})

    completed_now = sum(1 for f in backlog if f["status"] in ("completed", "failed"))
    progress      = round(completed_now / total * 100, 1) if total else 0.0

    names = [backlog[i]["name"] for i in batch_indices]
    logger.info(
        "advance_parallel_batch: batch cerrado %s | progreso %.1f%%", names, progress,
    )
    save_run_metadata(state["project_id"], {
        "batch_completed": names,
        "progress_pct":    progress,
    })

    return {
        "backlog":               backlog,
        "parallel_batch":        [],
        "progress_pct":          progress,
        "current_feature_index": (max(batch_indices) + 1) if batch_indices else 0,
    }


# ── Routers ───────────────────────────────────────────────────────────────────

def _route_after_approval(state: ProjectState) -> str:
    if not state.get("founder_approved_roadmap"):
        return "cancelado"
    from config import PARALLEL_FEATURES_ENABLED
    return "iniciar_loop_paralelo" if PARALLEL_FEATURES_ENABLED else "iniciar_loop"


def _route_after_parallel_batch(state: ProjectState) -> str:
    """
    Después de advance_parallel_batch: decide siguiente acción.
    Misma lógica que _route_after_advance pero para el path paralelo.
    """
    from config import ARCH_REVIEW_INTERVAL

    backlog     = state.get("backlog", [])
    has_pending = any(f["status"] == "pending" for f in backlog)

    if not has_pending:
        return "fin_backlog"
    if state.get("project_status") == "arch_review_paused":
        return "fin_backlog"

    if ARCH_REVIEW_INTERVAL > 0:
        completed_count = sum(1 for f in backlog if f["status"] in ("completed", "failed"))
        last_review_at  = state.get("arch_review_last_at_count", 0)
        since_review    = completed_count - last_review_at

        current_idx = state.get("current_feature_index", 1) - 1
        phase_done  = False
        if 0 <= current_idx < len(backlog):
            phase = backlog[current_idx].get("phase", "")
            if phase:
                phase_features = [f for f in backlog if f.get("phase") == phase]
                phase_done = all(f["status"] in ("completed", "failed") for f in phase_features)

        if since_review >= ARCH_REVIEW_INTERVAL or phase_done:
            return "arch_review"

    return "continuar"


def _route_after_advance(state: ProjectState) -> str:
    """
    Después de advance_index: decide si hacer auditoría A0, seguir al siguiente feature,
    o ir a la pantalla de sugerencias finales.

    Prioridad:
      1. Sin features pendientes → fin_backlog (independiente de arch review)
      2. Proyecto pausado por arch review → fin_backlog (espera resolución)
      3. Arch review due → arch_review
      4. Continuar normalmente → continuar
    """
    from config import ARCH_REVIEW_INTERVAL

    backlog = state.get("backlog", [])
    has_pending = any(f["status"] == "pending" for f in backlog)

    # Sin pendientes o proyecto pausado → fin
    if not has_pending:
        return "fin_backlog"
    if state.get("project_status") == "arch_review_paused":
        return "fin_backlog"

    # Verificar si corresponde auditoría arquitectónica
    if ARCH_REVIEW_INTERVAL > 0:
        completed_count = sum(1 for f in backlog if f["status"] in ("completed", "failed"))
        last_review_at  = state.get("arch_review_last_at_count", 0)
        since_review    = completed_count - last_review_at

        # También triggear al final de cada fase
        current_idx = state.get("current_feature_index", 1) - 1
        phase_done  = False
        if 0 <= current_idx < len(backlog):
            phase = backlog[current_idx].get("phase", "")
            if phase:
                phase_features = [f for f in backlog if f.get("phase") == phase]
                phase_done = all(f["status"] in ("completed", "failed") for f in phase_features)

        if since_review >= ARCH_REVIEW_INTERVAL or phase_done:
            return "arch_review"

    return "continuar"


def _route_after_arch_review(state: ProjectState) -> str:
    """Después de a0_revisor: continuar el loop o pausar si hay derivación crítica."""
    if state.get("project_status") == "arch_review_paused":
        return "fin_backlog"
    has_pending = any(f["status"] == "pending" for f in state.get("backlog", []))
    if not has_pending:
        return "fin_backlog"
    from config import PARALLEL_FEATURES_ENABLED
    return "continuar_paralelo" if PARALLEL_FEATURES_ENABLED else "continuar"


def _route_check_backlog(state: ProjectState) -> str:
    """Mantener por compatibilidad — ahora usamos _route_after_advance."""
    backlog = state.get("backlog", [])
    has_pending = any(f["status"] == "pending" for f in backlog)
    return "continuar" if has_pending else "fin_backlog"


def _route_after_suggestions(state: ProjectState) -> str:
    status = state.get("project_status", "")
    if status != "running":
        return "cerrar"
    # Volver al path correcto según el modo activo
    from config import PARALLEL_FEATURES_ENABLED
    return "continuar_loop_paralelo" if PARALLEL_FEATURES_ENABLED else "continuar_loop"


# ── Construcción del grafo ────────────────────────────────────────────────────

def build_project_graph() -> StateGraph:
    g = StateGraph(ProjectState)

    # ── Nodos compartidos ─────────────────────────────────────────────────────
    g.add_node("a0_arquitecto",         a0_arquitecto)
    g.add_node("human_approve_roadmap", human_approve_roadmap)
    g.add_node("a0_revisor",            a0_revisor)
    g.add_node("present_suggestions",   present_suggestions)
    g.add_node("project_complete",      project_complete)

    # ── Path SECUENCIAL (PARALLEL_FEATURES_ENABLED=False) ────────────────────
    g.add_node("pick_next_feature",     pick_next_feature)
    g.add_node("run_feature_pipeline",  run_feature_pipeline)
    g.add_node("pm_evaluador",          pm_evaluador)
    g.add_node("advance_index",         advance_index)

    # ── Path PARALELO (PARALLEL_FEATURES_ENABLED=True) — VI-2 ────────────────
    g.add_node("pick_ready_features",   pick_ready_features)
    g.add_node("run_parallel_batch",    run_parallel_batch)
    g.add_node("merge_coordinator",     merge_coordinator)
    g.add_node("advance_parallel_batch",advance_parallel_batch)

    # ── Entrada ───────────────────────────────────────────────────────────────
    g.set_entry_point("a0_arquitecto")
    g.add_edge("a0_arquitecto", "human_approve_roadmap")

    # ── Post-aprobación: bifurca en secuencial vs paralelo ────────────────────
    g.add_conditional_edges(
        "human_approve_roadmap",
        _route_after_approval,
        {
            "iniciar_loop":         "pick_next_feature",
            "iniciar_loop_paralelo":"pick_ready_features",
            "cancelado":            "project_complete",
        },
    )

    # ══════════════════════════════════════════════════════════════════════════
    # PATH SECUENCIAL
    # ══════════════════════════════════════════════════════════════════════════
    g.add_edge("pick_next_feature",    "run_feature_pipeline")
    g.add_edge("run_feature_pipeline", "pm_evaluador")
    g.add_edge("pm_evaluador",         "advance_index")

    g.add_conditional_edges(
        "advance_index",
        _route_after_advance,
        {
            "continuar":   "pick_next_feature",
            "arch_review": "a0_revisor",
            "fin_backlog": "present_suggestions",
        },
    )

    # ══════════════════════════════════════════════════════════════════════════
    # PATH PARALELO — VI-2
    # ══════════════════════════════════════════════════════════════════════════
    g.add_edge("pick_ready_features",    "run_parallel_batch")
    g.add_edge("run_parallel_batch",     "merge_coordinator")
    g.add_edge("merge_coordinator",      "advance_parallel_batch")

    g.add_conditional_edges(
        "advance_parallel_batch",
        _route_after_parallel_batch,
        {
            "continuar":   "pick_ready_features",
            "arch_review": "a0_revisor",
            "fin_backlog": "present_suggestions",
        },
    )

    # ── a0_revisor: vuelve al path correcto según el modo ────────────────────
    g.add_conditional_edges(
        "a0_revisor",
        _route_after_arch_review,
        {
            "continuar":          "pick_next_feature",    # Path secuencial
            "continuar_paralelo": "pick_ready_features",  # Path paralelo
            "fin_backlog":        "present_suggestions",
        },
    )

    # ── Post-backlog ──────────────────────────────────────────────────────────
    g.add_conditional_edges(
        "present_suggestions",
        _route_after_suggestions,
        {
            "continuar_loop":         "pick_next_feature",    # Secuencial
            "continuar_loop_paralelo":"pick_ready_features",  # Paralelo
            "cerrar":                 "project_complete",
        },
    )

    g.add_edge("project_complete", END)
    return g


def compile_project_graph():
    """Compila el grafo de proyecto con persistencia SQLite."""
    from graph import _make_sqlite_checkpointer
    checkpointer = _make_sqlite_checkpointer()
    return build_project_graph().compile(
        checkpointer=checkpointer,
        interrupt_before=[
            "human_approve_roadmap",  # ⛔ Founder aprueba roadmap inicial
            "present_suggestions",    # ⛔ Founder decide continuar/cerrar al vaciar backlog
            # Nota: a0_revisor y merge_coordinator usan interrupt() interno
            # solo cuando hay DERIVACION_CRITICA o conflicto HIGH de merge
        ],
    )
