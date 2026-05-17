"""Agente 1 — Fase A: Planificador (Product Owner). Genera el MASTER_PLAN."""
import re
from state import FabricaState
from nodes.base import call_agent
from tools.file_tools import save_master_plan, save_run_metadata
from config import MODEL_A1
from datetime import datetime


def a1_planificador(state: FabricaState) -> dict:
    repo_name = state["repo_name"]
    repo_path = state["repo_path"]
    is_auto   = state["mode"] == "auto"

    # En modo proyecto, el roadmap ya fue aprobado — añadirlo como contexto
    project_context = ""
    if state.get("project_mode") and state.get("project_id"):
        from tools.file_tools import RUNS_DIR
        import json
        proj_meta_path = RUNS_DIR / state["project_id"] / "metadata.json"
        if proj_meta_path.exists():
            meta = json.loads(proj_meta_path.read_text())
            roadmap = meta.get("roadmap", "")
            if roadmap:
                project_context = f"""
CONTEXTO DEL PROYECTO (ROADMAP aprobado por el Founder):
---
{roadmap[:3000]}
---
Este feature forma parte del roadmap anterior. Tu MASTER_PLAN debe ser coherente
con la arquitectura y decisiones ya tomadas en el roadmap.
"""

    mode_instruction = ""
    if is_auto:
        mode_instruction = """
5. **MODO DE EJECUCIÓN**: Decide qué modo es más apropiado para este feature:
   - COMPLETO: features nuevos que requieren nuevo esquema DB, herramientas MCP o revisión SecOps profunda
   - LITE: bugfixes, ajustes de UI, cambios de configuración, features pequeños sin DB nueva
   En la última línea de tu output antes del MASTER_PLAN, escribe EXACTAMENTE:
   `MODO_SELECCIONADO: COMPLETO` o `MODO_SELECCIONADO: LITE`
"""

    task = f"""
Eres el Agente 1 en FASE A (Planificador / Product Owner).

El Founder ha solicitado el siguiente feature para el proyecto **{repo_name}**:
**Nombre:** {state['feature_name']}
**Modo configurado:** {state['mode'].upper()}
**Repositorio:** {repo_path}
{project_context}

Tu tarea:
1. Analiza la naturaleza del feature y los módulos afectados.
2. Identifica conflictos con el DECISION_LOG.
3. Genera el MASTER_PLAN completo usando la estructura del template en agents/agent_01_pm/templates/MASTER_PLAN_TEMPLATE.md.
4. Al final del MASTER_PLAN, incluye una sección "AWAITING_APPROVAL" con el texto:
   → Escribe exactamente: "Plan aprobado. Pasa a ejecución." para continuar.
{mode_instruction}
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

    # Resolver modo "auto" leyendo la decisión del agente
    resolved_mode = state["mode"]
    if is_auto:
        m = re.search(r"MODO_SELECCIONADO:\s*(COMPLETO|LITE)", output, re.IGNORECASE)
        if m:
            resolved_mode = m.group(1).lower()
        else:
            resolved_mode = "completo"  # default seguro si el agente no lo indicó

    path = save_master_plan(state["feature_id"], output)
    save_run_metadata(state["feature_id"], {
        "feature_name": state["feature_name"],
        "repo_name": repo_name,
        "mode": resolved_mode,
        "mode_was_auto": is_auto,
        "started_at": datetime.utcnow().isoformat(),
        "master_plan_path": path,
    })

    return {
        "master_plan": output,
        "master_plan_path": path,
        "mode": resolved_mode,
        "current_agent": "a1_planificador",
        "cost_entries": [cost],
    }
