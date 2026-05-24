"""
Grafo LangGraph de la Fábrica de Software.

Pipeline:

  COMPLETO: A1 PM → Stop ⛔ → A2 DB → [A3 MCP]* → [A4 Backend]* → [A5 Frontend]*
              → A6 Refactor ↺(QA falla) → A7 QA → A8 SecOps ↺(vulnerabilidades)
              → A10 CodeWriter → A9 Sandbox → [A11 DevOps]* → A1 PM Final

  LITE:     A1 PM → Stop ⛔ → [A4 Backend]* → [A5 Frontend]*
              → A6 Refactor ↺(QA falla) → A7 QA → A8 SecOps ↺(vulnerabilidades)
              → A10 CodeWriter → A9 Sandbox → [A11 DevOps]* → A1 PM Final

  * = condicional según flags detectados por A1 Planificador:
      [A3 MCP]      → salta si needs_mcp=False
      [A4 Backend]  → salta si skip_backend=True  (feature solo de frontend)
      [A5 Frontend] → salta si skip_frontend=True (feature solo de backend/API)
      [A11 DevOps]  → salta si needs_devops=False

ORDEN A10→A9 (correcto, G1 fix):
  A10 escribe archivos al repo PRIMERO, luego A9 los testea en disco real.
  Si A9 falla → A6 corrige en state → A7 → A8 → A10 reescribe → A9 retest.

Loops y escalaciones:
  • QA falla → vuelve a A6 (que lee el qa_report y corrige)
  • Máx. iteraciones QA↔A6 → qa_escalation ⚠️ → humano
  • SecOps encuentra vulnerabilidades → corrige código → retest A7 QA
  • Máx. iteraciones SecOps↔QA (MAX_SECOPS_ITER=2) → qa_escalation ⚠️ → humano
  • Sandbox falla → vuelve a A6 (lee sandbox_results) → … → A10 reescribe → A9 retest
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
    """
    Stop Protocol: plan aprobado → infraestructura (completo) | código (lite) | fin.
    G5: lite + skip_backend → salta directamente al frontend.
    """
    if not state["founder_approval"]:
        return "rechazado"
    mode = state["mode"]
    # G5: si solo hay cambios de frontend y el modo es lite, saltar A4
    if mode == "lite" and state.get("skip_backend"):
        return "frontend_only"
    return mode if mode in ("completo", "lite") else "completo"


def _route_after_db(state: FabricaState) -> str:
    """
    G4: A2 DB → A3 MCP solo si needs_mcp=True.
    Si needs_mcp=False, salta directamente a A4 Backend (o A5 si skip_backend).
    """
    if not state.get("needs_mcp", True):
        # Sin MCP: ir a backend o saltarlo si es skip_backend
        return "a5_frontend" if state.get("skip_backend") else "a4_backend"
    return "a3_mcp"


def _route_after_mcp(state: FabricaState) -> str:
    """
    G5 (modo completo): A3 MCP → A4 Backend | saltar si skip_backend=True.
    """
    return "a5_frontend" if state.get("skip_backend") else "a4_backend"


def _route_after_backend(state: FabricaState) -> str:
    """
    G5: A4 Backend → A5 Frontend | A6 Refactor (si skip_frontend=True).
    """
    return "a6_refactor" if state.get("skip_frontend") else "a5_frontend"


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
      sin vulnerabilidades → A10 Code Writer (G1: era A9 Sandbox — corregido)
      vulnerabilidades corregidas + margen → A7 QA (retest con código corregido)
      vulnerabilidades no corregibles o máx. iteraciones → escala humano
    """
    block = state.get("security_block_2")
    if not block:
        return "limpio"                  # → A10 Code Writer (escribe archivos primero)

    # Hay un bloqueo: ¿puede reintentarse?
    unfixable = "UNFIXABLE" in (block or "").upper()
    if unfixable or state.get("secops_iterations", 0) >= MAX_SECOPS_ITER:
        return "escalar"                 # → qa_escalation → humano

    return "retest"                      # → A7 QA (código ya corregido por SecOps)


def _route_after_sandbox(state: FabricaState) -> str:
    """
    Sandbox (corre DESPUÉS de A10 — testea archivos reales en disco):
      todos los checks pasaron → A11 DevOps [condicional] | PR Final
      hay fallos y hay margen → A6 Refactor (lee sandbox_results, corrige state)
                                 → A7 → A8 → A10 reescribe → A9 retest
      agotó iteraciones → escala humano
    """
    if state["sandbox_passed"]:
        return "devops" if state.get("needs_devops") else "pr_final"
    if state.get("sandbox_iterations", 0) >= MAX_SANDBOX_ITER:
        return "escalar"
    return "reintentar"


# ── Nodo terminal ─────────────────────────────────────────────────────────────

def pipeline_detenido(state: FabricaState) -> dict:
    from tools.file_tools import save_run_metadata
    from datetime import datetime

    # G9: Rollback de archivos escritos si el pipeline falla
    files_backup: dict = state.get("files_backup", {})
    files_written: list = state.get("files_written", [])
    repo_path = state.get("repo_path", "")

    if files_backup and repo_path:
        from pathlib import Path
        import logging
        _log = logging.getLogger(__name__)
        restored = 0
        for rel_path, original_content in files_backup.items():
            try:
                full = Path(repo_path) / rel_path
                full.write_text(original_content, encoding="utf-8")
                restored += 1
            except Exception as exc:
                _log.warning("rollback: no se pudo restaurar %s — %s", rel_path, exc)
        # Eliminar archivos NEW (no estaban antes, sin backup)
        new_files = [f for f in files_written if f not in files_backup]
        for rel_path in new_files:
            try:
                full = Path(repo_path) / rel_path
                if full.exists():
                    full.unlink()
                    restored += 1
            except Exception as exc:
                _log.warning("rollback: no se pudo eliminar %s — %s", rel_path, exc)
        if restored:
            _log.info("pipeline_detenido: rollback completado — %d archivos restaurados/eliminados", restored)

    razon = (
        (state.get("errors") or ["Pipeline detenido"])[-1]
        or "Pipeline detenido por decisión del Founder"
    )
    save_run_metadata(state["feature_id"], {
        "status":     "detenido",
        "razon":      str(razon)[:200],
        "stopped_at": datetime.utcnow().isoformat(),
        "rollback":   bool(files_backup),
    })
    return {"errors": [f"Pipeline detenido: {str(razon)[:100]}"]}


# ── Construcción del grafo ────────────────────────────────────────────────────

def build_graph() -> StateGraph:
    g = StateGraph(FabricaState)

    # ── Nodos ─────────────────────────────────────────────────────────────────
    g.add_node("a1_planificador",   a1_planificador)
    g.add_node("stop_protocol",     stop_protocol)       # ⛔ aprobación del MASTER_PLAN
    g.add_node("a2_db",             a2_db)               # solo modo completo
    g.add_node("a3_mcp",            a3_mcp)              # condicional: needs_mcp=True
    g.add_node("a4_backend",        a4_backend)          # condicional: skip_backend=False
    g.add_node("a5_frontend",       a5_frontend)         # condicional: skip_frontend=False
    g.add_node("a6_refactor",       a6_refactor)         # pre-QA: revisa+corrige+unifica
    g.add_node("a7_qa",             a7_qa)
    g.add_node("qa_escalation",     qa_escalation)       # ⚠️ escala humano (QA o SecOps)
    g.add_node("a8_secops",         a8_secops)           # post-QA: auditoría + corrección
    g.add_node("a10_code_writer",   a10_code_writer)     # escribe archivos al repo real (ANTES de A9)
    g.add_node("a9_sandbox",        a9_sandbox)          # post-A10: tests sobre archivos reales
    g.add_node("a11_devops",        a11_devops)          # actualiza deps/infra [condicional]
    g.add_node("a1_pr_final",       a1_pr_final)         # PM cierre: cumplimiento+docs+PR
    g.add_node("pipeline_detenido", pipeline_detenido)

    # ── Flujo ─────────────────────────────────────────────────────────────────

    # 1. PM genera MASTER_PLAN → Stop Protocol (aprobación)
    g.set_entry_point("a1_planificador")
    g.add_edge("a1_planificador", "stop_protocol")

    # 2. Aprobado → infraestructura (completo) | código directo (lite) | frontend-only | fin
    g.add_conditional_edges(
        "stop_protocol",
        _route_after_approval,
        {
            "completo":      "a2_db",
            "lite":          "a4_backend",
            "frontend_only": "a5_frontend",  # G5: lite + skip_backend
            "rechazado":     "pipeline_detenido",
        },
    )

    # 3. Modo completo: DB → (A3 MCP condicional G4) → Backend o Frontend
    g.add_conditional_edges(
        "a2_db",
        _route_after_db,
        {
            "a3_mcp":       "a3_mcp",
            "a4_backend":   "a4_backend",
            "a5_frontend":  "a5_frontend",  # needs_mcp=False + skip_backend=True
        },
    )

    # A3 MCP → Backend condicional (G5: skip_backend en completo)
    g.add_conditional_edges(
        "a3_mcp",
        _route_after_mcp,
        {
            "a4_backend":  "a4_backend",
            "a5_frontend": "a5_frontend",  # skip_backend en completo
        },
    )

    # 4. Backend → Frontend condicional (G5: skip_frontend)
    g.add_conditional_edges(
        "a4_backend",
        _route_after_backend,
        {
            "a5_frontend": "a5_frontend",
            "a6_refactor": "a6_refactor",  # G5: skip_frontend
        },
    )
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
            "passed":     "a8_secops",
            "reintentar": "a6_refactor",   # A6 lee qa_report y corrige
            "escalar":    "qa_escalation",
        },
    )

    # 7. QA Escalation → fin
    g.add_edge("qa_escalation", "pipeline_detenido")

    # 8. SecOps: limpio → A10 Code Writer (G1 fix) | corrigió → retest QA | no puede → escala
    g.add_conditional_edges(
        "a8_secops",
        _route_after_secops,
        {
            "limpio":  "a10_code_writer",  # G1: A10 escribe ANTES que A9 testee
            "retest":  "a7_qa",            # código ya corregido en state
            "escalar": "qa_escalation",
        },
    )

    # 9. A10 Code Writer → A9 Sandbox (G1: archivos ya en disco → tests sobre código real)
    g.add_edge("a10_code_writer", "a9_sandbox")

    # 10. Sandbox: passed → DevOps/PR | fallos → A6 Refactor | agotó → escala
    g.add_conditional_edges(
        "a9_sandbox",
        _route_after_sandbox,
        {
            "devops":     "a11_devops",    # needs_devops → actualiza deps/infra
            "pr_final":   "a1_pr_final",   # directo al PR
            "reintentar": "a6_refactor",   # A6 corrige → A7 → A8 → A10 reescribe → A9 retest
            "escalar":    "qa_escalation",
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
