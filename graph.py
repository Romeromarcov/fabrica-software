"""
Grafo LangGraph de la Fábrica de Software.

Pipeline:

  COMPLETO: A1 PM → Stop ⛔ → A2 DB → A3 MCP → A4 Backend → A5 Frontend
              → A6 Refactor ↺(QA falla) → A7 QA → A8 SecOps ↺(vulnerabilidades)
              → A9 Sandbox → A10 CodeWriter → A11 DevOps [condicional] → A1 PM Final

  LITE:     A1 PM → Stop ⛔ → A4 Backend → A5 Frontend
              → A6 Refactor ↺(QA falla) → A7 QA → A8 SecOps ↺(vulnerabilidades)
              → A9 Sandbox → A10 CodeWriter → A11 DevOps [condicional] → A1 PM Final

Loops y escalaciones:
  • QA falla → vuelve a A6 (que lee el qa_report y corrige)
  • Máx. iteraciones QA↔A6 → qa_escalation ⚠️ → humano
  • SecOps encuentra vulnerabilidades → corrige código → retest A7 QA
  • Máx. iteraciones SecOps↔QA (MAX_SECOPS_ITER=2) → qa_escalation ⚠️ → humano
  • Sandbox falla → vuelve a A6 (lee sandbox_results)
  • A10 escribe archivos al repo real
  • A11 actualiza deps/infra solo cuando needs_devops=True
  • Notificación Telegram al completar y al escalar
"""
from __future__ import annotations
from langgraph.graph import StateGraph, END
from langgraph.checkpoint.sqlite import SqliteSaver

from state import FabricaState
from config import DB_PATH, MAX_QA_ITER_COMPLETO, MAX_QA_ITER_LITE, MAX_SECOPS_ITER, MAX_SANDBOX_ITER

# ── Nodos de agentes ──────────────────────────────────────────────────────────
from nodes.a1_planificador import a1_planificador
from nodes.a1_pr_final     import a1_pr_final
from nodes.a2_db           import a2_db
from nodes.a3_mcp          import a3_mcp
from nodes.a4_backend      import a4_backend
from nodes.a5_frontend     import a5_frontend
from nodes.a6_refactor     import a6_refactor
from nodes.a7_qa           import a7_qa
from nodes.a8_secops       import a8_secops
from nodes.a9_sandbox      import a9_sandbox
from nodes.a10_code_writer import a10_code_writer
from nodes.a11_devops      import a11_devops

# ── Nodos humanos ─────────────────────────────────────────────────────────────
from nodes.human_nodes import stop_protocol, qa_escalation


# ── Routers ───────────────────────────────────────────────────────────────────

def _route_after_approval(state: FabricaState) -> str:
    """Stop Protocol: plan aprobado → infraestructura (completo) o código (lite)."""
    if not state["founder_approval"]:
        return "rechazado"
    mode = state["mode"]
    return mode if mode in ("completo", "lite") else "completo"


def _route_after_refactor(state: FabricaState) -> str:
    """A6: código OK → QA | bloqueante crítico → detener."""
    return "qa" if state["refactor_doc_approved"] else "error"


def _route_after_qa(state: FabricaState) -> str:
    """
    QA: pasó → SecOps
        falla (con margen) → A6 Refactor (lee el qa_report y corrige)
        agotó iteraciones → escala humano
    """
    if state["qa_passed"]:
        return "passed"
    max_iter = MAX_QA_ITER_COMPLETO if state["mode"] == "completo" else MAX_QA_ITER_LITE
    if state["qa_iterations"] >= max_iter:
        return "escalar"
    return "reintentar"


def _route_after_secops(state: FabricaState) -> str:
    """
    SecOps:
      sin vulnerabilidades → Sandbox (A9)
      vulnerabilidades corregidas + margen → A7 QA (retest con código corregido)
      vulnerabilidades no corregibles o máx. iteraciones → escala humano
    """
    block = state.get("security_block_2")
    if not block:
        return "limpio"                  # → A9 Sandbox

    # Hay un bloqueo: ¿puede reintentarse?
    unfixable = "UNFIXABLE" in (block or "").upper()
    if unfixable or state.get("secops_iterations", 0) >= MAX_SECOPS_ITER:
        return "escalar"                 # → qa_escalation → humano

    return "retest"                      # → A7 QA (código ya corregido por SecOps)


def _route_after_sandbox(state: FabricaState) -> str:
    """
    Sandbox:
      todos los checks pasaron (o sin herramientas) → A10 Code Writer
      hay fallos y hay margen → A6 Refactor (lee sandbox_results y corrige)
      agotó iteraciones → escala humano
    """
    if state["sandbox_passed"]:
        return "passed"   # → a10_code_writer
    if state.get("sandbox_iterations", 0) >= MAX_SANDBOX_ITER:
        return "escalar"
    return "reintentar"


def _route_after_code_writer(state: FabricaState) -> str:
    """
    Code Writer:
      necesita devops (deps/infra nuevas) → A11 DevOps
      no necesita → PR Final directamente
    """
    return "devops" if state.get("needs_devops") else "pr_final"


# ── Nodo terminal ─────────────────────────────────────────────────────────────

def pipeline_detenido(state: FabricaState) -> dict:
    from tools.file_tools import save_run_metadata
    from datetime import datetime

    razon = (
        (state.get("errors") or ["Pipeline detenido"])[-1]
        or "Pipeline detenido por decisión del Founder"
    )
    save_run_metadata(state["feature_id"], {
        "status":     "detenido",
        "razon":      str(razon)[:200],
        "stopped_at": datetime.utcnow().isoformat(),
    })
    return {"errors": [f"Pipeline detenido: {str(razon)[:100]}"]}


# ── Construcción del grafo ────────────────────────────────────────────────────

def build_graph() -> StateGraph:
    g = StateGraph(FabricaState)

    # ── Nodos ─────────────────────────────────────────────────────────────────
    g.add_node("a1_planificador",   a1_planificador)
    g.add_node("stop_protocol",     stop_protocol)       # ⛔ aprobación del MASTER_PLAN
    g.add_node("a2_db",             a2_db)               # solo modo completo
    g.add_node("a3_mcp",            a3_mcp)              # solo modo completo
    g.add_node("a4_backend",        a4_backend)
    g.add_node("a5_frontend",       a5_frontend)
    g.add_node("a6_refactor",       a6_refactor)         # pre-QA: revisa+corrige+unifica
    g.add_node("a7_qa",             a7_qa)
    g.add_node("qa_escalation",     qa_escalation)       # ⚠️ escala humano (QA o SecOps)
    g.add_node("a8_secops",         a8_secops)           # post-QA: auditoría + corrección
    g.add_node("a9_sandbox",        a9_sandbox)          # post-SecOps: tests reales + lint
    g.add_node("a10_code_writer",   a10_code_writer)     # escribe archivos al repo real
    g.add_node("a11_devops",        a11_devops)          # actualiza deps/infra [condicional]
    g.add_node("a1_pr_final",       a1_pr_final)         # PM cierre: cumplimiento+docs+PR
    g.add_node("pipeline_detenido", pipeline_detenido)

    # ── Flujo ─────────────────────────────────────────────────────────────────

    # 1. PM genera MASTER_PLAN → Stop Protocol (aprobación)
    g.set_entry_point("a1_planificador")
    g.add_edge("a1_planificador", "stop_protocol")

    # 2. Aprobado → infraestructura (completo) | código directo (lite) | fin
    g.add_conditional_edges(
        "stop_protocol",
        _route_after_approval,
        {
            "completo":  "a2_db",
            "lite":      "a4_backend",
            "rechazado": "pipeline_detenido",
        },
    )

    # 3. Modo completo: DB → MCP → Backend
    g.add_edge("a2_db",  "a3_mcp")
    g.add_edge("a3_mcp", "a4_backend")

    # 4. Backend → Frontend → A6 Refactor (ambos modos)
    g.add_edge("a4_backend",  "a5_frontend")
    g.add_edge("a5_frontend", "a6_refactor")

    # 5. A6 → QA (aprobado) | detener (bloqueante crítico)
    g.add_conditional_edges(
        "a6_refactor",
        _route_after_refactor,
        {
            "qa":    "a7_qa",
            "error": "pipeline_detenido",
        },
    )

    # 6. QA loop: pasó → SecOps | falla → A6 (con feedback) | agotó → escala
    g.add_conditional_edges(
        "a7_qa",
        _route_after_qa,
        {
            "passed":    "a8_secops",
            "reintentar": "a6_refactor",   # A6 lee qa_report y corrige
            "escalar":   "qa_escalation",
        },
    )

    # 7. QA Escalation → fin
    g.add_edge("qa_escalation", "pipeline_detenido")

    # 8. SecOps: limpio → Sandbox | corrigió → retest QA | no puede → escala
    g.add_conditional_edges(
        "a8_secops",
        _route_after_secops,
        {
            "limpio":  "a9_sandbox",
            "retest":  "a7_qa",             # código ya corregido en state
            "escalar": "qa_escalation",
        },
    )

    # 9. Sandbox: passed → A10 CodeWriter | fallos → A6 Refactor | agotó → escala
    g.add_conditional_edges(
        "a9_sandbox",
        _route_after_sandbox,
        {
            "passed":     "a10_code_writer",   # → escribe archivos al repo real
            "reintentar": "a6_refactor",       # A6 lee sandbox_results y corrige
            "escalar":    "qa_escalation",
        },
    )

    # 10. Code Writer → DevOps (condicional) | PR Final (directo)
    g.add_conditional_edges(
        "a10_code_writer",
        _route_after_code_writer,
        {
            "devops":   "a11_devops",     # actualiza deps/infra
            "pr_final": "a1_pr_final",    # directo al PR
        },
    )

    # 11. DevOps → PR Final
    g.add_edge("a11_devops", "a1_pr_final")

    # 12. PM Final → FIN
    g.add_edge("a1_pr_final",       END)
    g.add_edge("pipeline_detenido", END)

    return g


# ── Compilación ───────────────────────────────────────────────────────────────

def compile_graph():
    """
    Modo feature standalone: Stop Protocol espera aprobación humana del MASTER_PLAN.
    Solo dos puntos de interrupción: aprobación del plan y escalación.
    """
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    checkpointer = SqliteSaver.from_conn_string(str(DB_PATH))
    return build_graph().compile(
        checkpointer=checkpointer,
        interrupt_before=[
            "stop_protocol",   # ⛔ Founder revisa y aprueba el MASTER_PLAN
            "qa_escalation",   # ⚠️ QA o SecOps no pudo resolver → Founder decide
        ],
    )


def compile_graph_project_mode():
    """
    Modo project loop: el PM no espera aprobación humana (A0 ya dio la instrucción).
    Solo interrumpe ante escalaciones que requieren intervención humana.
    """
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    checkpointer = SqliteSaver.from_conn_string(str(DB_PATH))
    return build_graph().compile(
        checkpointer=checkpointer,
        interrupt_before=["qa_escalation"],
    )
