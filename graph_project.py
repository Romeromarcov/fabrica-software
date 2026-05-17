"""
Grafo del Project Loop — orquesta múltiples runs del pipeline de features.

Flujo:
  A0 (Arquitecto) → Human aprueba roadmap → LOOP {
    pick_next_feature → run_feature_pipeline → pm_evaluador → check_backlog
  } → present_suggestions → project_complete (o loop de nuevo si hay más)
"""
from __future__ import annotations
import json
import logging
from datetime import datetime

from langgraph.graph import StateGraph, END
from langgraph.checkpoint.sqlite import SqliteSaver
from langgraph.types import interrupt

from project_state import ProjectState, FeatureTask
from config import DB_PATH
from tools.file_tools import save_run_metadata, RUNS_DIR

logger = logging.getLogger(__name__)


# ── Nodos de agente ───────────────────────────────────────────────────────────

from nodes.a0_arquitecto import a0_arquitecto
from nodes.pm_evaluador  import pm_evaluador


# ── Human checkpoint: aprobación del roadmap ─────────────────────────────────

def human_approve_roadmap(state: ProjectState) -> dict:
    """Suspende el loop hasta que el Founder apruebe el roadmap generado por A0."""
    save_run_metadata(state["project_id"], {
        "project_status": "awaiting_approval",
        "roadmap_ready_at": datetime.utcnow().isoformat(),
    })

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
    backlog = state.get("backlog", [])
    idx     = state.get("current_feature_index", 0)

    # Buscar el primer pendiente desde current_feature_index en adelante
    for i in range(idx, len(backlog)):
        if backlog[i]["status"] == "pending":
            updated = list(backlog)
            updated[i] = FeatureTask(**{**backlog[i], "status": "running"})
            logger.info("Project Loop: iniciando feature %d/%d — %s", i+1, len(backlog), backlog[i]["name"])
            save_run_metadata(state["project_id"], {
                "current_feature": backlog[i]["name"],
                "current_feature_index": i,
                "project_status": "running",
            })
            return {"backlog": updated, "current_feature_index": i}

    # No hay más features pendientes
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

    # Añadir criterios de aceptación como contexto en el feature_name
    feat_state = {
        **feat_state,
        "feature_name": f"{feature['name']} — {feature.get('acceptance_criteria', '')[:100]}",
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

        # Verificar status final del feature
        meta_path = RUNS_DIR / feature_id / "metadata.json"
        if meta_path.exists():
            meta = json.loads(meta_path.read_text())
            if meta.get("status") == "detenido":
                final_status = "failed"

    except Exception as e:
        logger.exception("Error ejecutando feature %s: %s", feature_id, e)
        final_status = "failed"

    # Actualizar backlog con el feature_id y estado inicial
    backlog[idx] = FeatureTask(**{
        **feature,
        "feature_id": feature_id,
        "status": final_status if final_status == "failed" else "pending",
        # Lo deja en "pending" para que pm_evaluador actualice a "completed"/"failed"
    })

    cost_entries = []
    try:
        run_meta = json.loads((RUNS_DIR / feature_id / "metadata.json").read_text())
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
    Muestra el resumen del proyecto y las sugerencias del PM para que el Founder
    decida si quiere añadir más features o cerrar el proyecto.
    """
    completed = sum(1 for f in state["backlog"] if f["status"] == "completed")
    failed    = sum(1 for f in state["backlog"] if f["status"] == "failed")
    total     = len(state["backlog"])
    sug_text  = "\n".join(state.get("suggestions", [])) or "Ninguna"

    save_run_metadata(state["project_id"], {
        "project_status": "awaiting_suggestions_review",
        "final_completed": completed,
        "final_failed": failed,
    })

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
    completed = sum(1 for f in state["backlog"] if f["status"] == "completed")
    total     = len(state["backlog"])
    cost      = sum(e.get("cost_usd", 0) for e in state.get("cost_entries", []))

    save_run_metadata(state["project_id"], {
        "project_status": state.get("project_status", "completed"),
        "completed_at": datetime.utcnow().isoformat(),
        "features_completed": completed,
        "features_total": total,
        "total_cost_usd": round(cost, 6),
    })

    logger.info(
        "Proyecto %s finalizado: %d/%d features | $%.4f",
        state["project_name"], completed, total, cost,
    )
    return {}


# ── Routers ───────────────────────────────────────────────────────────────────

def _route_after_approval(state: ProjectState) -> str:
    if not state.get("founder_approved_roadmap"):
        return "cancelado"
    return "iniciar_loop"


def _route_check_backlog(state: ProjectState) -> str:
    """¿Hay más features pendientes en el backlog?"""
    backlog = state.get("backlog", [])
    idx     = state.get("current_feature_index", 0)
    has_pending = any(f["status"] == "pending" for f in backlog[idx:])

    if has_pending:
        return "continuar"

    # ¿Hubo algún bloqueante duro (feature fallido sin qa_escalation resuelta)?
    failed = [f for f in backlog if f["status"] == "failed"]
    if failed:
        logger.warning("%d features fallidos — el proyecto se detiene", len(failed))

    return "fin_backlog"


def _route_after_suggestions(state: ProjectState) -> str:
    status = state.get("project_status", "")
    if status == "running":
        return "continuar_loop"   # El Founder añadió más features
    return "cerrar"


# ── Construcción del grafo ────────────────────────────────────────────────────

def build_project_graph() -> StateGraph:
    g = StateGraph(ProjectState)

    g.add_node("a0_arquitecto",        a0_arquitecto)
    g.add_node("human_approve_roadmap",human_approve_roadmap)
    g.add_node("pick_next_feature",    pick_next_feature)
    g.add_node("run_feature_pipeline", run_feature_pipeline)
    g.add_node("pm_evaluador",         pm_evaluador)
    g.add_node("advance_index",        advance_index)
    g.add_node("present_suggestions",  present_suggestions)
    g.add_node("project_complete",     project_complete)

    # ── Entrada ───────────────────────────────────────────────────────────────
    g.set_entry_point("a0_arquitecto")
    g.add_edge("a0_arquitecto", "human_approve_roadmap")

    # ── Post-aprobación ───────────────────────────────────────────────────────
    g.add_conditional_edges(
        "human_approve_roadmap",
        _route_after_approval,
        {
            "iniciar_loop": "pick_next_feature",
            "cancelado":    "project_complete",
        },
    )

    # ── Feature loop ──────────────────────────────────────────────────────────
    g.add_edge("pick_next_feature",    "run_feature_pipeline")
    g.add_edge("run_feature_pipeline", "pm_evaluador")
    g.add_edge("pm_evaluador",         "advance_index")

    g.add_conditional_edges(
        "advance_index",
        _route_check_backlog,
        {
            "continuar":   "pick_next_feature",
            "fin_backlog": "present_suggestions",
        },
    )

    # ── Post-backlog ──────────────────────────────────────────────────────────
    g.add_conditional_edges(
        "present_suggestions",
        _route_after_suggestions,
        {
            "continuar_loop": "pick_next_feature",   # Loop con nuevos features
            "cerrar":         "project_complete",
        },
    )

    g.add_edge("project_complete", END)
    return g


def compile_project_graph():
    """Compila el grafo de proyecto con persistencia SQLite."""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    checkpointer = SqliteSaver.from_conn_string(str(DB_PATH))
    return build_project_graph().compile(
        checkpointer=checkpointer,
        interrupt_before=["human_approve_roadmap", "present_suggestions"],
    )
