"""
Nodos de interacción humana del pipeline.
Usan langgraph.types.interrupt() para suspender el proceso y esperar input del Founder.
El estado se persiste en SQLite vía SqliteSaver — sobrevive reinicios del proceso.
"""
from langgraph.types import interrupt
from state import FabricaState
from config import MAX_QA_ITER_COMPLETO, MAX_QA_ITER_LITE
from tools.file_tools import save_run_metadata
from datetime import datetime


FRASE_APROBACION = "Plan aprobado. Pasa a ejecución."


def stop_protocol(state: FabricaState) -> dict:
    """
    Stop Protocol del Agente 1.
    En modo proyecto (project_mode=True): auto-aprueba ya que el roadmap fue aprobado.
    En modo feature normal: suspende hasta que el Founder escriba la frase exacta.
    """
    # ── Modo proyecto: auto-aprobar ───────────────────────────────────────────
    if state.get("project_mode"):
        save_run_metadata(state["feature_id"], {
            "status": "auto_approved",
            "project_id": state.get("project_id"),
        })
        return {
            "founder_approval": True,
            "current_agent": "stop_protocol",
        }

    save_run_metadata(state["feature_id"], {
        "status": "awaiting_approval",
        "paused_at": datetime.utcnow().isoformat(),
    })

    founder_input: str = interrupt({
        "tipo": "stop_protocol",
        "mensaje": (
            f"\n{'='*60}\n"
            f"📋 MASTER_PLAN generado para: {state['feature_name']}\n"
            f"📦 Repositorio: {state['repo_name']}\n"
            f"📁 Guardado en: {state.get('master_plan_path', 'ver output anterior')}\n"
            f"{'='*60}\n\n"
            f"Lee el plan completo y cuando estés listo escribe EXACTAMENTE:\n\n"
            f'  "{FRASE_APROBACION}"\n\n'
            f"Cualquier otra respuesta no activa la ejecución."
        ),
        "feature_id": state["feature_id"],
    })

    aprobado = founder_input.strip() == FRASE_APROBACION

    updates: dict = {
        "founder_approval": aprobado,
        "current_agent": "stop_protocol",
    }

    if not aprobado:
        updates["errors"] = [
            f"Frase incorrecta: '{founder_input}'. "
            f"Usa exactamente: '{FRASE_APROBACION}'"
        ]

    save_run_metadata(state["feature_id"], {
        "status": "approved" if aprobado else "rejected",
        "approved_at": datetime.utcnow().isoformat() if aprobado else None,
    })

    return updates


def checkpoint_a(state: FabricaState) -> dict:
    """
    Checkpoint A: notificación tras SecOps Revisión 1.
    En modo proyecto: auto-continúa sin esperar.
    """
    if state.get("project_mode"):
        save_run_metadata(state["feature_id"], {"status": "building"})
        return {"checkpoint_a_approved": True, "current_agent": "checkpoint_a"}

    save_run_metadata(state["feature_id"], {
        "status": "checkpoint_a",
        "checkpoint_a_at": datetime.utcnow().isoformat(),
    })

    founder_input: str = interrupt({
        "tipo": "checkpoint",
        "checkpoint": "A",
        "mensaje": (
            f"\n{'─'*50}\n"
            f"✓ CHECKPOINT A — {state['feature_name']} [{state['repo_name']}]\n"
            f"  Esquema DB y herramientas MCP aprobados por SecOps.\n"
            f"  Iniciando construcción (Backend + Frontend).\n"
            f"{'─'*50}\n\n"
            f"Escribe PAUSA para detener, o ENTER / cualquier cosa para continuar.\n"
            f"(Timeout: 30 min — si no respondes, el pipeline continúa automáticamente)"
        ),
        "feature_id": state["feature_id"],
        "timeout_seconds": 1800,
    })

    pausado = founder_input.strip().upper() == "PAUSA"

    save_run_metadata(state["feature_id"], {
        "status": "paused_at_checkpoint_a" if pausado else "building",
    })

    return {
        "checkpoint_a_approved": not pausado,
        "current_agent": "checkpoint_a",
        "errors": ["Founder pausó en Checkpoint A"] if pausado else [],
    }


def checkpoint_b(state: FabricaState) -> dict:
    """
    Checkpoint B: notificación tras QA pass.
    En modo proyecto: auto-continúa sin esperar.
    """
    if state.get("project_mode"):
        save_run_metadata(state["feature_id"], {"status": "finalizing"})
        return {"checkpoint_b_approved": True, "current_agent": "checkpoint_b"}

    save_run_metadata(state["feature_id"], {
        "status": "checkpoint_b",
        "checkpoint_b_at": datetime.utcnow().isoformat(),
    })

    founder_input: str = interrupt({
        "tipo": "checkpoint",
        "checkpoint": "B",
        "mensaje": (
            f"\n{'─'*50}\n"
            f"✓ CHECKPOINT B — {state['feature_name']} [{state['repo_name']}]\n"
            f"  QA superado. Iniciando SecOps Rev.2 + Refactor final.\n"
            f"{'─'*50}\n\n"
            f"Escribe PAUSA para detener, o ENTER / cualquier cosa para continuar.\n"
            f"(Timeout: 30 min)"
        ),
        "feature_id": state["feature_id"],
        "timeout_seconds": 1800,
    })

    pausado = founder_input.strip().upper() == "PAUSA"

    save_run_metadata(state["feature_id"], {
        "status": "paused_at_checkpoint_b" if pausado else "finalizing",
    })

    return {
        "checkpoint_b_approved": not pausado,
        "current_agent": "checkpoint_b",
        "errors": ["Founder pausó en Checkpoint B"] if pausado else [],
    }


def qa_escalation(state: FabricaState) -> dict:
    """
    Escalación al Founder cuando QA agota el máximo de iteraciones sin pasar.
    Presenta los bugs al Founder y espera instrucción.
    """
    max_iter = MAX_QA_ITER_COMPLETO if state["mode"] == "completo" else MAX_QA_ITER_LITE

    save_run_metadata(state["feature_id"], {
        "status": "qa_escalated",
        "qa_escalated_at": datetime.utcnow().isoformat(),
    })

    founder_input: str = interrupt({
        "tipo": "qa_escalation",
        "mensaje": (
            f"\n{'!'*60}\n"
            f"⚠️  QA AGOTÓ {max_iter} ITERACIONES — {state['feature_name']}\n"
            f"{'!'*60}\n\n"
            f"BUGS PENDIENTES:\n"
            f"{state.get('qa_report', 'Ver output del Agente 4')}\n\n"
            f"Opciones:\n"
            f"  REDISEÑAR  — volver a Agente 2/3 con enfoque diferente\n"
            f"  ACEPTAR    — aceptar deuda técnica y documentar los bugs\n"
            f"  CANCELAR   — cancelar el feature\n\n"
            f"Escribe tu decisión:"
        ),
        "feature_id": state["feature_id"],
    })

    decision = founder_input.strip().upper()
    save_run_metadata(state["feature_id"], {"qa_decision": decision})

    # El graph router usará el estado para decidir qué hacer con esta decisión
    return {
        "current_agent": "qa_escalation",
        "errors": [f"QA escalado. Decisión del Founder: {decision}"],
    }
