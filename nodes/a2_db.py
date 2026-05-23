"""Agente 2 — DB Architect. Diseña el esquema de base de datos."""
from state import FabricaState
from nodes.base import call_agent
from tools.file_tools import save_agent_output
from config import MODEL_A2


def a2_db(state: FabricaState) -> dict:
    from tools.architecture_record import adr_context_block
    from tools.project_memory import get_memory_context
    adr_block    = adr_context_block(state["repo_path"])
    memory_block = get_memory_context(state.get("project_id"))

    task = f"""
Eres el Agente 2 — DB Architect.
{adr_block}{memory_block}

MASTER_PLAN del feature a implementar:
---
{state['master_plan']}
---

Tu tarea: diseña el esquema completo de base de datos para este feature.

Entrega obligatoriamente:
1. Todos los modelos Django nuevos o modificados (heredando de BaseModel)
2. Migraciones completas (makemigrations output conceptual)
3. Índices necesarios (especialmente los parciales para soft-delete)
4. Queries frecuentes esperadas (para validar que los índices las cubren)
5. Diagrama ER textual de las relaciones entre modelos nuevos y existentes

Sigue al pie de la letra las reglas de CODING_STANDARDS y DECISION_LOG.
"""
    # BUG-018: MASTER_PLAN ya está incrustado en task_content, no pasarlo de nuevo
    output, cost = call_agent(
        agent_key="a2-db",
        agent_label="Agente 2 DB",
        task_content=task,
        model=MODEL_A2,
        repo_path=state["repo_path"],
    )
    save_agent_output(state["feature_id"], "a2_db", output)
    return {
        "db_schema": output,
        "current_agent": "a2_db",
        "cost_entries": [cost],
    }
