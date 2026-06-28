"""Agente 4 — Backend Developer."""
from state import FabricaState
from nodes.base import call_agent
from tools.file_tools import save_agent_output
from tools.learning_memory import lessons_for_context, recurring_error_patterns, hard_instruction_block
from tools.fewshot_builder import build_fewshots
from config import MODEL_A4


def a4_backend(state: FabricaState) -> dict:
    from tools.architecture_record import adr_context_block
    from tools.project_memory import get_memory_context
    from tools.stack_reader import read_stack, get_backend_instructions
    from tools.context_retriever import get_relevant_context
    adr_block         = adr_context_block(state["repo_path"])
    memory_block      = get_memory_context(state.get("project_id"))
    fingerprint_block = get_relevant_context(state["repo_path"])

    # Sistema de aprendizaje: lecciones del proyecto + few-shots
    lessons_block  = lessons_for_context(state["repo_path"], state.get("master_plan", ""))
    fewshot_block  = build_fewshots(state.get("project_id", ""), context="backend")

    # B3.3 Aprendizaje preventivo: patrones que fallaron ≥2 veces → instrucción DURA
    _recurring     = recurring_error_patterns(state["repo_path"], state.get("project_id", "") or "")
    hard_block     = hard_instruction_block(_recurring)
    if hard_block:
        import logging
        logging.getLogger(__name__).info(
            "A4 Backend: inyectando %d patrones recurrentes como instrucción OBLIGATORIA",
            len(_recurring),
        )

    # Inyectar instrucciones del stack real del proyecto
    stack = read_stack(state["repo_path"])
    stack_block = ""
    backend_instructions = get_backend_instructions(stack)
    if backend_instructions:
        stack_block = (
            "\n## INSTRUCCIONES DE STACK (plantilla genérica — precedencia BAJA)\n"
            f"{backend_instructions}\n"
            "⚠️ PRECEDENCIA: si el CODEBASE FINGERPRINT de arriba muestra la estructura REAL del "
            "repo (entrypoint, dónde van routers/modelos, estilo de import), REPLÍCALA EXACTAMENTE e "
            "IGNORA esta plantilla. No inventes `app/api/v1/...` ni imports `from app.` si el repo no "
            "los usa — usa el mismo layout y estilo de import que el código existente.\n"
        )

    qa_context = ""
    if state.get("qa_report") and state["qa_iterations"] > 0:
        qa_context = f"""
REPORTE DE BUGS DEL AGENTE 7 (iteración {state['qa_iterations']}):
---
{state['qa_report']}
---
Corrige ÚNICAMENTE los bugs listados. No cambies lo que ya funciona.
"""

    task = f"""
Eres el Agente 4 — Backend Developer.
{hard_block}{adr_block}{memory_block}{fingerprint_block}{lessons_block}{fewshot_block}{stack_block}
MASTER_PLAN del feature:
---
{state['master_plan']}
---

ESQUEMA DB APROBADO (Agente 2):
---
{state.get('db_schema', '')}
---

SECURITY CLEARANCE (Agente 8 Rev.1) — esquema aprobado, puedes construir sobre él.
{qa_context}

Tu tarea: implementa el backend completo.
Sigue las instrucciones de stack de arriba para la estructura de archivos.
Para CADA archivo de código usa EXACTAMENTE este formato (sin excepción):

```[extensión]
# === ruta/relativa/archivo.ext ===
[código completo del archivo]
```

Ejemplo para Django:
```python
# === apps/modulo/models.py ===
from django.db import models
...
```

Ejemplo para FastAPI:
```python
# === app/models/modulo.py ===
from sqlalchemy import Column, Integer
...
```
"""
    # F1 — A4 recibe los artefactos estructurados validados de A1 (MasterPlan) y A2 (DBSchema).
    from config import STRUCTURED_ARTIFACTS_ENABLED
    if STRUCTURED_ARTIFACTS_ENABLED:
        import logging as _l
        mp = state.get("master_plan_artifact")
        db = state.get("db_schema_artifact")
        _l.getLogger(__name__).info(
            "A4 recibió artefactos validados: MasterPlan=%s DBSchema=%s", bool(mp), bool(db))

    # F2 — Harness/ACI: en modo harness, A4 construye leyendo el repo real con tools
    # (mini-loop ReAct). Gated; flag off → call_agent directo de hoy (idéntico).
    from config import HARNESS_MODE_ENABLED
    if HARNESS_MODE_ENABLED:
        from nodes.base import call_agent_react
        output, costs = call_agent_react(
            agent_key="a4-backend",
            agent_label="Agente 4 Backend",
            task_content=task,
            model=MODEL_A4,
            repo_path=state["repo_path"],
        )
    else:
        output, cost = call_agent(
            agent_key="a4-backend",
            agent_label="Agente 4 Backend",
            task_content=task,
            model=MODEL_A4,
            repo_path=state["repo_path"],
        )
        costs = [cost]
    save_agent_output(state["feature_id"], f"a4_backend_iter{state['qa_iterations']}", output)
    return {
        "backend_code": output,
        "current_agent": "a4_backend",
        "cost_entries": costs,
    }
