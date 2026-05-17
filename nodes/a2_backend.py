"""Agente 2 — Backend Developer."""
from state import FabricaState
from nodes.base import call_agent
from tools.file_tools import save_agent_output
from config import MODEL_A2


def a2_backend(state: FabricaState) -> dict:
    qa_context = ""
    if state.get("qa_report") and state["qa_iterations"] > 0:
        qa_context = f"""
REPORTE DE BUGS DEL AGENTE 4 (iteración {state['qa_iterations']}):
---
{state['qa_report']}
---
Corrige ÚNICAMENTE los bugs listados. No cambies lo que ya funciona.
"""

    task = f"""
Eres el Agente 2 — Backend Developer.

MASTER_PLAN del feature:
---
{state['master_plan']}
---

ESQUEMA DB APROBADO (Agente 6):
---
{state.get('db_schema', '')}
---

SECURITY CLEARANCE (Agente 7 Rev.1) — esquema aprobado, puedes construir sobre él.
{qa_context}

Tu tarea: implementa el backend completo.
Entrega en este orden:
1. `apps/[modulo]/models.py` — usando exactamente el esquema del Agente 6
2. `apps/[modulo]/serializers.py` — separados por caso de uso (list vs detalle)
3. `apps/[modulo]/services.py` — toda la lógica de negocio aquí
4. `apps/[modulo]/views.py` — ViewSets que delegan a services
5. `apps/[modulo]/signals.py` — auditoría via LogAuditoria
6. `apps/[modulo]/urls.py` — router registration

Para cada archivo, usa el formato:
```python
# === apps/[modulo]/[archivo].py ===
[código completo]
```
"""
    output, cost = call_agent(
        agent_key="a2_backend",
        agent_label="Agente 2 Backend",
        task_content=task,
        model=MODEL_A2,
        repo_path=state["repo_path"],
    )
    save_agent_output(state["feature_id"], f"a2_backend_iter{state['qa_iterations']}", output)
    return {
        "backend_code": output,
        "current_agent": "a2_backend",
        "cost_entries": [cost],
    }
