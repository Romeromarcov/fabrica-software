"""Agente 3 — Frontend Developer."""
from state import FabricaState
from nodes.base import call_agent
from tools.file_tools import save_agent_output
from config import MODEL_A3


def a3_frontend(state: FabricaState) -> dict:
    qa_context = ""
    if state.get("qa_report") and state["qa_iterations"] > 0:
        qa_context = f"""
REPORTE DE BUGS DEL AGENTE 4 (iteración {state['qa_iterations']}):
---
{state['qa_report']}
---
Corrige ÚNICAMENTE los bugs listados en el frontend.
"""

    task = f"""
Eres el Agente 3 — Frontend Developer.

MASTER_PLAN del feature (especialmente secciones 5 y 6 — UI/UX):
---
{state['master_plan']}
---

ENDPOINTS DEL BACKEND (Agente 2) — usa estos para los services:
---
{state.get('backend_code', '')}
---
{qa_context}

Tu tarea: implementa el frontend completo.
Entrega en este orden:
1. `src/types/[modulo].ts` — interfaces TypeScript (sin `any`)
2. `src/services/[modulo]Service.ts` — usando api.ts, nunca fetch directo
3. `src/hooks/use[Feature].ts` — TanStack Query, nunca useEffect para servidor
4. `src/components/[Feature]/` — componentes MUI directos, máx. 300 líneas cada uno
5. `src/pages/[Feature]Page.tsx` — composición de componentes
6. Fragmento de route para agregar a routes/

Para cada archivo:
```typescript
// === src/[ruta]/[archivo].ts ===
[código completo]
```
"""
    output, cost = call_agent(
        agent_key="a3_frontend",
        agent_label="Agente 3 Frontend",
        task_content=task,
        model=MODEL_A3,
        include_static=["coding_standards"],
        repo_path=state["repo_path"],
    )
    save_agent_output(state["feature_id"], f"a3_frontend_iter{state['qa_iterations']}", output)
    return {
        "frontend_code": output,
        "current_agent": "a3_frontend",
        "cost_entries": [cost],
    }
