"""
Grafo LangGraph de la Fábrica de Software.

Pipeline:

  COMPLETO:  A1 PM → Stop ⛔ → A2 DB → [A3 MCP]* → [A4 Backend]* → [A5 Frontend]*
               → A6 Refactor ↺(QA falla) → A7 QA → A8 SecOps ↺(vulnerabilidades)
               → A10 CodeWriter → A9 Sandbox → [A11 DevOps]* → A1 PM Final

  LITE:      A1 PM → Stop ⛔ → [A4 Backend]* → [A5 Frontend]*
               → A6 Refactor ↺(QA falla) → A7 QA → A8 SecOps ↺(vulnerabilidades)
               → A10 CodeWriter → A9 Sandbox → [A11 DevOps]* → A1 PM Final

  LIGHTNING: ⚡ A1 PM → auto-aprobado → [A4 Backend]* → [A5 Frontend]*
               → A10 CodeWriter → lightning_complete → END
               (omite: A2 DB, A3 MCP, A6 Refactor, A7 QA, A8 SecOps,
                        A9 Sandbox, A11 DevOps, A1 PR Final)
               Para hotfixes y prototipos desechables. Target: < 90 seg.

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
from config import DB_PATH, MAX_QA_ITER_COMPLETO, MAX_QA_ITER_LITE, MAX_SECOPS_ITER, MAX_SANDBOX_ITER, MAX_ADVERSARIAL_ITER, VETO_WINDOW_MINUTES

# ── Nodos de agentes ──────────────────────────────────────────────────────────
from nodes.debate_panel    import run_debate
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
from nodes.a85_adversarial import a85_adversarial
from nodes.a10_code_writer import a10_code_writer
from nodes.a11_devops      import a11_devops

# ── Nodos humanos ─────────────────────────────────────────────────────────────
from nodes.human_nodes import (
    stop_protocol, qa_escalation,
    confidence_auto_approve, veto_window,
)


# ── Routers ───────────────────────────────────────────────────────────────────

def _route_after_plan(state: FabricaState) -> str:
    """
    Bloque III: decide el camino de aprobación del MASTER_PLAN.
    Solo aplica en project_mode; en modo standalone siempre va a stop_protocol.

    lightning                      → confidence_auto_approve (siempre — modo ultra-rápido)
    confidence >= 85 + risk=LOW   → confidence_auto_approve (sin intervención)
    confidence >= 60 + risk≠HIGH  → veto_window (aprobación automática tras N min)
    demás casos                   → stop_protocol (aprobación manual)
    """
    if state.get("mode") == "lightning":
        return "confidence_auto_approve"  # ⚡ lightning: nunca espera aprobación manual
    if not state.get("project_mode"):
        return "stop_protocol"
    conf = state.get("confidence_score", 70)
    risk = state.get("risk_level", "MEDIUM")
    if conf >= 85 and risk == "LOW":
        return "confidence_auto_approve"
    if conf >= 60 and risk != "HIGH":
        return "veto_window"
    return "stop_protocol"


def _route_after_plan_or_debate(state: FabricaState) -> str:
    """
    VIII-3: Si RISK_LEVEL=HIGH y el modo no es lightning y el debate no se hizo
    todavía → debate_panel (2 revisores + árbitro A1).
    Cualquier otro caso → flujo normal de aprobación via _route_after_plan().
    """
    if (
        state.get("risk_level") == "HIGH"
        and state.get("mode") != "lightning"
        and not state.get("debate_done")
    ):
        return "debate_panel"
    return _route_after_plan(state)


def _route_after_approval(state: FabricaState) -> str:
    """
    Stop Protocol / Auto-approve: plan aprobado → infraestructura | código | fin.
    G5:        lite      + skip_backend → salta directamente al frontend.
    Lightning: lightning + skip_backend → salta directamente al frontend.
    Lightning: lightning               → A4 Backend (omite A2 DB, A3 MCP).
    """
    if not state["founder_approval"]:
        return "rechazado"
    mode = state["mode"]
    if mode == "lightning":
        # ⚡ lightning salta A2/A3 siempre; el resto del shortcut se resuelve downstream
        return "frontend_only" if state.get("skip_backend") else "lightning"
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
    G5:        A4 Backend → A5 Frontend | A6 Refactor (si skip_frontend=True).
    Lightning: A4 Backend → A10 Code Writer directamente (sin A5, A6, A7, A8, A9).
    """
    if state.get("mode") == "lightning":
        return "a10_code_writer"  # ⚡ lightning: skip todo post-backend
    return "a6_refactor" if state.get("skip_frontend") else "a5_frontend"


def _route_after_frontend(state: FabricaState) -> str:
    """
    A5 Frontend → A6 Refactor (normal) | A10 Code Writer (lightning).
    """
    if state.get("mode") == "lightning":
        return "a10_code_writer"  # ⚡ lightning: skip A6/A7/A8/A9
    return "a6_refactor"


def _route_after_code_writer(state: FabricaState) -> str:
    """
    A10 Code Writer → A9 Sandbox (normal) | lightning_complete (lightning).
    """
    if state.get("mode") == "lightning":
        return "lightning_complete"  # ⚡ lightning: skip sandbox
    return "a9_sandbox"


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
        return "adversarial"             # → A8.5 revisión adversarial a nivel repo (Fase 2)
    if state.get("sandbox_iterations", 0) >= MAX_SANDBOX_ITER:
        return "escalar"
    return "reintentar"


def _route_after_adversarial(state: FabricaState) -> str:
    """
    A8.5 Revisión adversarial (corre DESPUÉS de A9 — repo real en disco):
      clear → A11 DevOps [condicional] | PR Final
      block y hay margen → A6 Refactor (con el hallazgo en sandbox_gate_failures)
      block y agotó iteraciones → escala humano (R-PROC-3)
    """
    if state.get("adversarial_clear", True):
        return "devops" if state.get("needs_devops") else "pr_final"
    if state.get("adversarial_iterations", 0) >= MAX_ADVERSARIAL_ITER:
        return "escalar"
    return "reintentar"


# ── Nodo Lightning Complete ───────────────────────────────────────────────────

def lightning_complete(state: FabricaState) -> dict:
    """
    ⚡ Terminal del pipeline Lightning: omite QA, SecOps, Sandbox, DevOps y PR.
    Guarda metadata, notifica por Telegram y termina.
    """
    from tools.file_tools import save_run_metadata
    from datetime import datetime

    n_files = len(state.get("files_written", []))
    save_run_metadata(state["feature_id"], {
        "status":       "completado_lightning",
        "completed_at": datetime.utcnow().isoformat(),
        "files_written": state.get("files_written", []),
        "mode":         "lightning",
    })

    try:
        from tools.telegram import send_message
        send_message(
            f"⚡ *Lightning completado*: {state['feature_name']}\n"
            f"📁 {n_files} archivo(s) escritos al repo `{state['repo_name']}`.\n"
            f"⚠️ Sin QA ni SecOps — solo para hotfixes/prototipos."
        )
    except Exception:
        pass  # best-effort

    # VII-2: señal de fin de pipeline para cerrar SSE
    try:
        from tools.event_bus import emit_pipeline_end
        emit_pipeline_end(state["feature_id"], "completado_lightning")
    except Exception:
        pass

    return {"current_agent": "lightning_complete"}


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
    g.add_node("a1_planificador",        a1_planificador)
    g.add_node("confidence_auto_approve", confidence_auto_approve)  # Bloque III: auto
    g.add_node("veto_window",             veto_window)              # Bloque III: veto N min
    g.add_node("stop_protocol",           stop_protocol)            # ⛔ aprobación manual
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
    g.add_node("a85_adversarial",   a85_adversarial)     # Fase 2: revisión adversarial a nivel repo
    g.add_node("a11_devops",          a11_devops)          # actualiza deps/infra [condicional]
    g.add_node("a1_pr_final",         a1_pr_final)         # PM cierre: cumplimiento+docs+PR
    g.add_node("pipeline_detenido",   pipeline_detenido)
    g.add_node("lightning_complete",  lightning_complete)  # ⚡ terminal lightning (sin QA/PR)
    g.add_node("debate_panel",        run_debate)          # VIII-3: revisión inter-agente (HIGH risk)

    # ── Flujo ─────────────────────────────────────────────────────────────────

    # 1. PM genera MASTER_PLAN → debate (si HIGH) o aprobación directa (Bloque III + VIII-3)
    g.set_entry_point("a1_planificador")
    g.add_conditional_edges(
        "a1_planificador",
        _route_after_plan_or_debate,
        {
            "debate_panel":            "debate_panel",         # VIII-3: HIGH risk
            "confidence_auto_approve": "confidence_auto_approve",
            "veto_window":             "veto_window",
            "stop_protocol":           "stop_protocol",
        },
    )

    # 1b. Debate completado → flujo normal de aprobación (debate_done=True, no re-entra)
    g.add_conditional_edges(
        "debate_panel",
        _route_after_plan,
        {
            "confidence_auto_approve": "confidence_auto_approve",
            "veto_window":             "veto_window",
            "stop_protocol":           "stop_protocol",
        },
    )

    # ── Mapa compartido de salidas post-aprobación ────────────────────────────
    _approval_targets = {
        "completo":      "a2_db",
        "lite":          "a4_backend",
        "lightning":     "a4_backend",   # ⚡ lightning: salta A2/A3; diverge en downstream
        "frontend_only": "a5_frontend",  # lite/lightning + skip_backend
        "rechazado":     "pipeline_detenido",
    }

    # 1b. Los tres caminos convergen en _route_after_approval
    g.add_conditional_edges("confidence_auto_approve", _route_after_approval, _approval_targets)
    g.add_conditional_edges("veto_window",             _route_after_approval, _approval_targets)

    # 2. Aprobado → infraestructura (completo) | código directo (lite/lightning) | fin
    g.add_conditional_edges("stop_protocol", _route_after_approval, _approval_targets)

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

    # 4. Backend → Frontend condicional (G5: skip_frontend) | A10 directo (lightning)
    g.add_conditional_edges(
        "a4_backend",
        _route_after_backend,
        {
            "a5_frontend":    "a5_frontend",
            "a6_refactor":    "a6_refactor",    # G5: skip_frontend
            "a10_code_writer": "a10_code_writer", # ⚡ lightning: skip A5/A6/A7/A8
        },
    )

    # A5 Frontend → A6 Refactor (normal) | A10 Code Writer (lightning)
    g.add_conditional_edges(
        "a5_frontend",
        _route_after_frontend,
        {
            "a6_refactor":    "a6_refactor",
            "a10_code_writer": "a10_code_writer",  # ⚡ lightning
        },
    )

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

    # 9. A10 Code Writer → A9 Sandbox (normal) | lightning_complete (lightning)
    g.add_conditional_edges(
        "a10_code_writer",
        _route_after_code_writer,
        {
            "a9_sandbox":         "a9_sandbox",
            "lightning_complete": "lightning_complete",  # ⚡ skip sandbox
        },
    )

    # 10. Sandbox: passed → A8.5 adversarial | fallos → A6 Refactor | agotó → escala
    g.add_conditional_edges(
        "a9_sandbox",
        _route_after_sandbox,
        {
            "adversarial": "a85_adversarial",  # Fase 2: revisión adversarial a nivel repo
            "reintentar":  "a6_refactor",      # A6 corrige → A7 → A8 → A10 reescribe → A9 retest
            "escalar":     "qa_escalation",
        },
    )

    # 10.5 A8.5 Adversarial: clear → DevOps/PR | block → A6 Refactor | agotó → escala humano
    g.add_conditional_edges(
        "a85_adversarial",
        _route_after_adversarial,
        {
            "devops":     "a11_devops",
            "pr_final":   "a1_pr_final",
            "reintentar": "a6_refactor",   # hallazgo adversarial inyectado en sandbox_gate_failures
            "escalar":    "qa_escalation",
        },
    )

    # 11. DevOps → PR Final
    g.add_edge("a11_devops", "a1_pr_final")

    # 12. PM Final → FIN
    g.add_edge("a1_pr_final",         END)
    g.add_edge("pipeline_detenido",   END)
    g.add_edge("lightning_complete",  END)  # ⚡

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
    Modo project loop: el PM no espera aprobación manual (A0 ya dio la instrucción).
    Interrumpe ante: veto_window (Founder puede vetar) y escalaciones QA.
    confidence_auto_approve no necesita interrupt_before — aprueba sin suspender.
    """
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    checkpointer = SqliteSaver.from_conn_string(str(DB_PATH))
    return build_graph().compile(
        checkpointer=checkpointer,
        interrupt_before=["veto_window", "qa_escalation"],
    )
