"""
Nodos de interacción humana del pipeline.
Usan langgraph.types.interrupt() para suspender el proceso y esperar input del Founder.
El estado se persiste en SQLite vía SqliteSaver — sobrevive reinicios del proceso.
"""
from langgraph.types import interrupt
from state import FabricaState
from config import MAX_QA_ITER_COMPLETO, MAX_QA_ITER_LITE, VETO_WINDOW_MINUTES
from tools.file_tools import save_run_metadata
from datetime import datetime, timezone, timedelta


FRASE_APROBACION = "Plan aprobado. Pasa a ejecución."


def confidence_auto_approve(state: FabricaState) -> dict:
    """
    Bloque III: plan con CONFIDENCE >= 85 y RISK=LOW en project_mode.
    Auto-aprueba sin ventana de veto y notifica al Founder por Telegram.
    """
    from tools.telegram import send_message
    conf  = state.get("confidence_score", 70)
    risk  = state.get("risk_level", "MEDIUM")
    fname = state["feature_name"]

    send_message(
        f"✅ *Auto-aprobado* (confianza {conf}/100 · Riesgo 🟢 {risk})\n"
        f"*Feature:* {fname}\n"
        f"El pipeline continúa sin intervención humana."
    )
    save_run_metadata(state["feature_id"], {
        "status":         "auto_approved",
        "confidence":     conf,
        "risk_level":     risk,
        "approved_at":    datetime.now(timezone.utc).isoformat(),
        "approval_mode":  "confidence_auto",
    })
    return {
        "founder_approval": True,
        "current_agent":    "confidence_auto_approve",
    }


def veto_window(state: FabricaState) -> dict:
    """
    Bloque III: plan con confianza media o riesgo MEDIUM en project_mode.
    Notifica al Founder y suspende VETO_WINDOW_MINUTES minutos.
    Si el Founder no responde (o responde CONTINUAR), aprueba automáticamente.
    Si responde VETAR, rechaza el plan.
    """
    from tools.telegram import notify_veto_window as tg_veto

    conf    = state.get("confidence_score", 70)
    risk    = state.get("risk_level", "MEDIUM")
    fname   = state["feature_name"]
    fid     = state["feature_id"]
    minutes = VETO_WINDOW_MINUTES

    deadline = datetime.now(timezone.utc) + timedelta(minutes=minutes)
    deadline_iso = deadline.isoformat()

    # Resumen corto del plan para el mensaje Telegram
    plan_text = state.get("master_plan", "") or ""
    plan_summary = plan_text[:400].strip()

    save_run_metadata(fid, {
        "status":       "veto_window",
        "paused_at":    datetime.now(timezone.utc).isoformat(),
        "veto_expires": deadline_iso,
        "confidence":   conf,
        "risk_level":   risk,
    })

    tg_veto(
        feature_name=fname,
        feature_id=fid,
        confidence=conf,
        risk=risk,
        plan_summary=plan_summary,
        deadline_minutes=minutes,
    )

    founder_input: str = interrupt({
        "tipo":            "veto_window",
        "mensaje":         (
            f"\n{'─'*50}\n"
            f"⏳ VENTANA DE VETO — {fname}\n"
            f"   Confianza: {conf}/100 · Riesgo: {risk}\n"
            f"{'─'*50}\n\n"
            f"El pipeline continuará en {minutes} min si no actúas.\n"
            f"Escribe VETAR para detener, o CONTINUAR (o nada) para aprobar ahora."
        ),
        "feature_id":      fid,
        "veto_expires":    deadline_iso,
        "timeout_seconds": minutes * 60,
    })

    vetado = founder_input.strip().upper() == "VETAR"

    save_run_metadata(fid, {
        "status":   "vetado" if vetado else "approved",
        "vetado":   vetado,
        "approved_at": datetime.now(timezone.utc).isoformat() if not vetado else None,
        "approval_mode": "veto_window",
    })

    updates: dict = {
        "founder_approval": not vetado,
        "veto_deadline":    deadline_iso,
        "current_agent":    "veto_window",
    }
    if vetado:
        updates["errors"] = [f"Founder vetó el plan de '{fname}'."]
    return updates


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
    Escalación al Founder cuando QA o SecOps agota el máximo de iteraciones.
    Notifica por Telegram y suspende hasta que el Founder responda.
    """
    from tools.telegram import notify_escalation

    max_iter    = MAX_QA_ITER_COMPLETO if state["mode"] == "completo" else MAX_QA_ITER_LITE
    secops_iter = state.get("secops_iterations", 0)

    if secops_iter > 0:
        razon = (
            f"SecOps agotó {secops_iter} iteraciones de corrección↔QA. "
            f"Vulnerabilidad no resuelta automáticamente."
        )
    else:
        razon = f"QA agotó {max_iter} iteraciones sin pasar."

    save_run_metadata(state["feature_id"], {
        "status":         "escalated",
        "escalated_at":   datetime.utcnow().isoformat(),
        "escalation_reason": razon,
    })

    # Notificar al humano por Telegram antes de suspender
    notify_escalation(
        feature_name=state["feature_name"],
        reason=razon,
        project_name=state.get("project_id"),
    )

    founder_input: str = interrupt({
        "tipo": "qa_escalation",
        "mensaje": (
            f"\n{'!'*60}\n"
            f"⚠️  ESCALACIÓN — {state['feature_name']}\n"
            f"{'!'*60}\n\n"
            f"MOTIVO: {razon}\n\n"
            f"ÚLTIMO REPORTE:\n"
            f"{state.get('qa_report', 'Ver outputs del pipeline')[:1500]}\n\n"
            f"Opciones:\n"
            f"  REDISEÑAR — reiniciar con enfoque diferente\n"
            f"  ACEPTAR   — aceptar deuda técnica y continuar\n"
            f"  CANCELAR  — cancelar el feature\n"
        ),
        "feature_id": state["feature_id"],
    })

    decision = founder_input.strip().upper()
    save_run_metadata(state["feature_id"], {"escalation_decision": decision})

    # F6 — El grafo enruta según la decisión (antes la escalación siempre detenía el pipeline).
    result: dict = {
        "current_agent": "qa_escalation",
        "escalation_decision": decision,
    }
    if decision == "REDISEÑAR" or decision == "REDISENAR":
        # Reintento con enfoque distinto: reset del contador de QA para no re-escalar de inmediato.
        result["qa_iterations"] = 0
    elif decision != "ACEPTAR":
        # CANCELAR o respuesta no reconocida → se detiene (con el motivo registrado).
        result["errors"] = [f"Escalación cancelada. Decisión del Founder: {decision}"]
    return result
