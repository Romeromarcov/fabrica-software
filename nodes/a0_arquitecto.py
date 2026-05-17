"""
Agente 0 — Arquitecto de Proyecto.

Dos modos:
  is_new_project=True  → propone stack tecnológico + arquitectura + roadmap completo
  is_new_project=False → lee el repo existente y genera el plan de features siguientes

Usa OpenClaw cuando está disponible para escanear el repo real.
En modo directo, usa PROJECT_CONTEXT y DECISION_LOG como insumo.
"""
import json
import re
from project_state import ProjectState, FeatureTask, Phase
from nodes.base import call_agent
from tools.file_tools import save_run_metadata
from tools.file_parser import uploads_as_context
from config import MODEL_A1   # El Arquitecto usa el mismo modelo que el PM


def a0_arquitecto(state: ProjectState) -> dict:
    repo_name = state["repo_name"]
    repo_path = state["repo_path"]
    is_new    = state["is_new_project"]

    # ── Leer archivos subidos por el Founder ──────────────────────────────────
    uploads_block = uploads_as_context(state["project_id"])

    if is_new:
        task = f"""
Eres el Agente 0 — Arquitecto de Proyecto.

El Founder quiere CREAR UN PROYECTO NUEVO desde cero.

**Nombre del proyecto:** {state['project_name']}
**Brief / descripción:** {state['project_brief']}
**Repositorio destino:** {repo_path}

{uploads_block}

Tu tarea es generar el plan maestro completo del proyecto. Debes entregar:

## PARTE 1 — STACK TECNOLÓGICO

Propón el stack más adecuado para este proyecto. Incluye:
- Lenguaje(s) y versiones
- Framework backend + ORM/DB
- Framework frontend (si aplica)
- Infraestructura (Docker, cloud, CI/CD)
- Herramientas de testing

Justifica cada elección con las alternativas consideradas.

## PARTE 2 — ARQUITECTURA

Diseña la arquitectura del sistema:
- Componentes principales y sus responsabilidades
- Diagrama de arquitectura (texto)
- Patrones de diseño recomendados
- Decisiones arquitectónicas clave (para el DECISION_LOG)

## PARTE 3 — ROADMAP

Divide el proyecto en fases y features. Usa EXACTAMENTE este formato JSON al final
del output (entre las marcas ```json y ```):

```json
{{
  "phases": [
    {{
      "name": "Fase 1 — Fundamentos",
      "description": "Descripción de la fase",
      "goal": "Objetivo medible al completar esta fase"
    }}
  ],
  "backlog": [
    {{
      "name": "Setup inicial y autenticación",
      "description": "Descripción detallada del feature",
      "phase": "Fase 1 — Fundamentos",
      "priority": 1,
      "suggested_mode": "completo",
      "acceptance_criteria": "El usuario puede registrarse, iniciar sesión y recuperar contraseña"
    }}
  ]
}}
```

Ordena el backlog por dependencias y prioridad (1 = más urgente).
Para cada feature, suggested_mode debe ser "completo" (nuevo esquema DB / MCP) o "lite" (no requiere DB nueva).
"""
    else:
        task = f"""
Eres el Agente 0 — Arquitecto de Proyecto.

El Founder quiere generar un PLAN DE DESARROLLO para un proyecto existente.

**Nombre del proyecto:** {state['project_name']}
**Objetivo:** {state['project_brief']}
**Repositorio:** {repo_path}

{uploads_block}

Tu tarea es analizar el estado actual del proyecto y generar el roadmap de features a implementar.

## ANÁLISIS DEL ESTADO ACTUAL

Lee los documentos de contexto (PROJECT_CONTEXT, DECISION_LOG, CODING_STANDARDS)
para entender qué existe hoy, qué decisiones se tomaron y qué está pendiente.

Identifica:
1. Módulos ya implementados (con su estado de madurez)
2. Deuda técnica conocida
3. Features mencionados como "pendientes" en el DECISION_LOG
4. Gaps de funcionalidad evidente

## ROADMAP

Genera un plan con fases y features prioritarios. Usa EXACTAMENTE este formato JSON
al final del output (entre las marcas ```json y ```):

```json
{{
  "phases": [
    {{
      "name": "Fase 1 — Nombre",
      "description": "Descripción",
      "goal": "Objetivo medible"
    }}
  ],
  "backlog": [
    {{
      "name": "Nombre del feature",
      "description": "Descripción detallada",
      "phase": "Fase 1 — Nombre",
      "priority": 1,
      "suggested_mode": "completo",
      "acceptance_criteria": "Criterio concreto y verificable"
    }}
  ]
}}
```

Prioriza features que:
- Desbloquean otros features (dependencias)
- Tienen mayor valor de negocio
- Reducen deuda técnica crítica
"""

    output, cost = call_agent(
        agent_key="a1_pm",          # Reutiliza el perfil PM de OpenClaw
        agent_label="Agente 0 Arquitecto",
        task_content=task,
        model=MODEL_A1,
        include_static=["project_context", "coding_standards", "decision_log"],
        repo_path=repo_path,
    )

    # ── Parsear el JSON del roadmap ───────────────────────────────────────────
    phases: list[Phase] = []
    backlog: list[FeatureTask] = []
    tech_stack = ""

    json_match = re.search(r"```json\s*(\{.*?\})\s*```", output, re.DOTALL)
    if json_match:
        try:
            data = json.loads(json_match.group(1))
            for p in data.get("phases", []):
                phases.append(Phase(
                    name=p.get("name", ""),
                    description=p.get("description", ""),
                    goal=p.get("goal", ""),
                ))
            for i, f in enumerate(data.get("backlog", []), 1):
                backlog.append(FeatureTask(
                    name=f.get("name", f"Feature {i}"),
                    description=f.get("description", ""),
                    phase=f.get("phase", ""),
                    priority=f.get("priority", i),
                    suggested_mode=f.get("suggested_mode", "completo"),
                    acceptance_criteria=f.get("acceptance_criteria", ""),
                    feature_id=None,
                    status="pending",
                    evaluation_notes=None,
                ))
        except (json.JSONDecodeError, KeyError):
            pass  # El output se guarda igual; el humano puede editar el backlog

    # Extraer stack si es proyecto nuevo
    if is_new:
        stack_match = re.search(
            r"##\s*PARTE\s*1.*?STACK.*?\n(.*?)##\s*PARTE\s*2",
            output, re.DOTALL | re.IGNORECASE,
        )
        tech_stack = stack_match.group(1).strip() if stack_match else ""

    save_run_metadata(state["project_id"], {
        "project_name": state["project_name"],
        "repo_name": repo_name,
        "is_new_project": is_new,
        "phases_count": len(phases),
        "backlog_count": len(backlog),
        "uploaded_files": state.get("uploaded_files", []),
        "project_status": "awaiting_approval",
    })

    return {
        "roadmap": output,
        "phases": phases,
        "backlog": backlog,
        "tech_stack": tech_stack,
        "project_status": "awaiting_approval",
        "cost_entries": [cost],
    }
