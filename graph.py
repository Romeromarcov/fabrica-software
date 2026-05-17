"""
Grafo LangGraph de la Fábrica de Software Omni ERP.
Define el pipeline completo con sus dos modos (completo / lite),
el Stop Protocol, los checkpoints y el max_retries de QA.
"""
from __future__ import annotations
from langgraph.graph import StateGraph, END
from langgraph.checkpoint.sqlite import SqliteSaver

from state import FabricaState
from config import DB_PATH, MAX_QA_ITER_COMPLETO, MAX_QA_ITER_LITE

# ── Nodos de agentes ──────────────────────────────────────────────────────────
from nodes.a1_planificador import a1_planificador
from nodes.a1_pr_final import a1_pr_final
from nodes.a2_backend import a2_backend
from nodes.a3_frontend import a3_frontend
from nodes.a4_qa import a4_qa
from nodes.a5_refactor_doc import a5_refactor_doc
from nodes.a6_db import a6_db
from nodes.a7_secops import a7_revision_1, a7_revision_2
from nodes.a8_mcp import a8_mcp

# ── Nodos humanos ─────────────────────────────────────────────────────────────
from nodes.human_nodes import stop_protocol, checkpoint_a, checkpoint_b, qa_escalation


# ── Routers (funciones de decisión) ──────────────────────────────────────────

def _route_after_approval(state: FabricaState) -> str:
    """Tras el Stop Protocol: aprobado → ejecutar según modo; rechazado → fin."""
    if not state["founder_approval"]:
        return "rechazado"
    return state["mode"]  # "completo" o "lite"


def _route_after_secops_1(state: FabricaState) -> str:
    if state.get("security_block_1"):
        return "bloqueado"
    return "continuar"


def _route_after_checkpoint_a(state: FabricaState) -> str:
    if not state["checkpoint_a_approved"]:
        return "pausado"
    return "construir"


def _route_after_qa(state: FabricaState) -> str:
    if state["qa_passed"]:
        return "passed"
    max_iter = MAX_QA_ITER_COMPLETO if state["mode"] == "completo" else MAX_QA_ITER_LITE
    if state["qa_iterations"] >= max_iter:
        return "escalar"
    return "reintentar"


def _route_after_secops_2(state: FabricaState) -> str:
    if state.get("security_block_2"):
        return "bloqueado"
    return "continuar"


def _route_after_checkpoint_b(state: FabricaState) -> str:
    if not state["checkpoint_b_approved"]:
        return "pausado"
    return "refactor"


def _route_after_refactor(state: FabricaState) -> str:
    if state["refactor_doc_approved"]:
        return "pr_final"
    return "error"


# ── Nodo terminal de bloqueo (para Security Blocks y pausas) ─────────────────

def pipeline_detenido(state: FabricaState) -> dict:
    """Nodo de terminación limpia — el pipeline llegó a un estado no continuable."""
    from tools.file_tools import save_run_metadata
    from datetime import datetime

    razon = (
        state.get("security_block_1")
        or state.get("security_block_2")
        or "Pipeline detenido por decisión del Founder"
    )
    save_run_metadata(state["feature_id"], {
        "status": "detenido",
        "razon": razon[:200],
        "stopped_at": datetime.utcnow().isoformat(),
    })
    return {"errors": [f"Pipeline detenido: {razon[:100]}"]}


# ── Construcción del grafo ────────────────────────────────────────────────────

def build_graph() -> StateGraph:
    g = StateGraph(FabricaState)

    # ── Nodos ─────────────────────────────────────────────────────────────────
    g.add_node("a1_planificador",  a1_planificador)
    g.add_node("stop_protocol",    stop_protocol)        # ⛔ Human-in-the-loop
    g.add_node("a6_db",            a6_db)
    g.add_node("a8_mcp",           a8_mcp)
    g.add_node("a7_revision_1",    a7_revision_1)
    g.add_node("checkpoint_a",     checkpoint_a)         # 🔔 Checkpoint A
    g.add_node("a2_backend",       a2_backend)
    g.add_node("a3_frontend",      a3_frontend)
    g.add_node("a4_qa",            a4_qa)
    g.add_node("qa_escalation",    qa_escalation)        # ⚠️ Max retries agotados
    g.add_node("a7_revision_2",    a7_revision_2)
    g.add_node("checkpoint_b",     checkpoint_b)         # 🔔 Checkpoint B
    g.add_node("a5_refactor_doc",  a5_refactor_doc)
    g.add_node("a1_pr_final",      a1_pr_final)
    g.add_node("pipeline_detenido", pipeline_detenido)

    # ── Entrada ───────────────────────────────────────────────────────────────
    g.set_entry_point("a1_planificador")

    # ── Flujo: Planificador → Stop Protocol ───────────────────────────────────
    g.add_edge("a1_planificador", "stop_protocol")

    # ── Flujo: Stop Protocol → modo (completo/lite) o fin ────────────────────
    g.add_conditional_edges(
        "stop_protocol",
        _route_after_approval,
        {
            "completo":   "a6_db",              # Modo completo: empieza por DB
            "lite":       "a2_backend",         # Modo lite: directo a construcción
            "rechazado":  "pipeline_detenido",
        },
    )

    # ── MODO COMPLETO ─────────────────────────────────────────────────────────

    # A6 → A8 (secuencial — los resultados se acumulan en el estado)
    g.add_edge("a6_db", "a8_mcp")
    g.add_edge("a8_mcp", "a7_revision_1")

    # SecOps Rev.1 → Checkpoint A o Bloqueo
    g.add_conditional_edges(
        "a7_revision_1",
        _route_after_secops_1,
        {
            "continuar": "checkpoint_a",
            "bloqueado": "pipeline_detenido",
        },
    )

    # Checkpoint A → Construcción o Pausa
    g.add_conditional_edges(
        "checkpoint_a",
        _route_after_checkpoint_a,
        {
            "construir": "a2_backend",
            "pausado":   "pipeline_detenido",
        },
    )

    # A2 → A3 (secuencial — el frontend necesita los endpoints del backend)
    g.add_edge("a2_backend", "a3_frontend")

    # ── MODO LITE: A2/A3 también llegan al QA ──────────────────────────────
    # (Modo lite entra por a2_backend → a3_frontend → a4_qa, mismo camino)
    g.add_edge("a3_frontend", "a4_qa")

    # QA → retry / escalar / continuar
    g.add_conditional_edges(
        "a4_qa",
        _route_after_qa,
        {
            "passed":    "a7_revision_2" if True else "a5_refactor_doc",
            "reintentar": "a2_backend",
            "escalar":   "qa_escalation",
        },
    )
    # Nota: en Modo Lite no hay SecOps Rev.2, pero usamos el mismo nodo
    # que simplemente pasa si no hay código nuevo que revisar de MCP/DB.

    # QA Escalation → fin (el Founder debe decidir externamente)
    g.add_edge("qa_escalation", "pipeline_detenido")

    # SecOps Rev.2 → Checkpoint B o Bloqueo
    g.add_conditional_edges(
        "a7_revision_2",
        _route_after_secops_2,
        {
            "continuar": "checkpoint_b",
            "bloqueado": "pipeline_detenido",
        },
    )

    # Checkpoint B → Refactor o Pausa
    g.add_conditional_edges(
        "checkpoint_b",
        _route_after_checkpoint_b,
        {
            "refactor": "a5_refactor_doc",
            "pausado":  "pipeline_detenido",
        },
    )

    # Agente 5 → PR Final (si aprobó) o error
    g.add_conditional_edges(
        "a5_refactor_doc",
        _route_after_refactor,
        {
            "pr_final": "a1_pr_final",
            "error":    "pipeline_detenido",
        },
    )

    # PR Final → FIN
    g.add_edge("a1_pr_final", END)
    g.add_edge("pipeline_detenido", END)

    return g


def compile_graph():
    """Compila el grafo con persistencia SQLite para Human-in-the-Loop."""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    checkpointer = SqliteSaver.from_conn_string(str(DB_PATH))
    return build_graph().compile(checkpointer=checkpointer, interrupt_before=[
        "stop_protocol",
        "checkpoint_a",
        "checkpoint_b",
        "qa_escalation",
    ])
