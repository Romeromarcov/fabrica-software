"""Agente 6 — DB Architect. Diseña el esquema de base de datos."""
from state import FabricaState
from nodes.base import call_agent
from tools.file_tools import save_agent_output
from config import MODEL_A6


def a6_db(state: FabricaState) -> dict:
    task = f"""
Eres el Agente 6 — DB Architect.

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
    output, cost = call_agent(
        agent_key="a6_db",
        agent_label="Agente 6 DB",
        task_content=task,
        model=MODEL_A6,
        extra_context={"MASTER_PLAN": state["master_plan"]},
        repo_path=state["repo_path"],
    )
    save_agent_output(state["feature_id"], "a6_db", output)
    return {
        "db_schema": output,
        "current_agent": "a6_db",
        "cost_entries": [cost],
    }
