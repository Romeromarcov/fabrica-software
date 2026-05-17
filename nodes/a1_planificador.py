"""Agente 1 — Fase A: Planificador (Product Owner). Genera el MASTER_PLAN."""
from state import FabricaState
from nodes.base import call_agent
from tools.file_tools import save_master_plan, save_run_metadata
from config import MODEL_A1
from datetime import datetime


def a1_planificador(state: FabricaState) -> dict:
    repo_name = state["repo_name"]
    repo_path = state["repo_path"]

    task = f"""
Eres el Agente 1 en FASE A (Planificador / Product Owner).

El Founder ha solicitado el siguiente feature para el proyecto **{repo_name}**:
**Nombre:** {state['feature_name']}
**Modo seleccionado:** {state['mode'].upper()}
**Repositorio:** {repo_path}

Tu tarea:
1. Analiza si el modo elegido es correcto según la naturaleza del feature.
2. Identifica los módulos existentes afectados y posibles conflictos con el DECISION_LOG.
3. Genera el MASTER_PLAN completo usando la estructura del template en agents/agent_01_pm/templates/MASTER_PLAN_TEMPLATE.md.
4. Al final del MASTER_PLAN, incluye una sección "AWAITING_APPROVAL" con el texto:
   → Escribe exactamente: "Plan aprobado. Pasa a ejecución." para continuar.

IMPORTANTE: NO generes código de implementación. Solo el plan.
"""

    output, cost = call_agent(
        agent_key="a1_pm",
        agent_label="Agente 1 PM (Planificador)",
        task_content=task,
        model=MODEL_A1,
        include_static=["project_context", "decision_log"],
        repo_path=repo_path,
    )

    path = save_master_plan(state["feature_id"], output)
    save_run_metadata(state["feature_id"], {
        "feature_name": state["feature_name"],
        "mode": state["mode"],
        "started_at": datetime.utcnow().isoformat(),
        "master_plan_path": path,
    })

    return {
        "master_plan": output,
        "master_plan_path": path,
        "current_agent": "a1_planificador",
        "cost_entries": [cost],
    }
