"""Agente 5 — Frontend Developer."""
from state import FabricaState
from nodes.base import call_agent
from tools.file_tools import save_agent_output
from config import MODEL_A5


def a5_frontend(state: FabricaState) -> dict:
    from tools.architecture_record import adr_context_block
    from tools.project_memory import get_memory_context
    from tools.stack_reader import read_stack, get_frontend_instructions
    adr_block    = adr_context_block(state["repo_path"])
    memory_block = get_memory_context(state.get("project_id"))

    # Instrucciones del stack frontend real del proyecto
    stack = read_stack(state["repo_path"])
    stack_block = ""
    frontend_instructions = get_frontend_instructions(stack)
    if frontend_instructions:
        stack_block = f"\n## INSTRUCCIONES DE STACK\n{frontend_instructions}\n"

    qa_context = ""
    if state.get("qa_report") and state["qa_iterations"] > 0:
        qa_context = f"""
REPORTE DE BUGS DEL AGENTE 7 (iteración {state['qa_iterations']}):
---
{state['qa_report']}
---
Corrige ÚNICAMENTE los bugs listados en el frontend.
"""

    task = f"""
Eres el Agente 5 — Frontend Developer.
{adr_block}{memory_block}{stack_block}
MASTER_PLAN del feature (especialmente secciones 5 y 6 — UI/UX):
---
{state['master_plan']}
---

ENDPOINTS DEL BACKEND (Agente 4) — usa estos para los services:
---
{state.get('backend_code', '')}
---
{qa_context}

Tu tarea: implementa el frontend completo.
Sigue las instrucciones de stack de arriba para la estructura de archivos.
Para CADA archivo de código usa EXACTAMENTE este formato (sin excepción):

```[extensión]
// === ruta/relativa/archivo.ext ===
[código completo del archivo]
```

Ejemplo para React/TypeScript:
```typescript
// === src/types/modulo.ts ===
export interface ModuloItem { ... }
```

Ejemplo para Vue:
```vue
// === src/components/ModuloCard.vue ===
<template>...</template>
```
"""
    output, cost = call_agent(
        agent_key="a5-frontend",
        agent_label="Agente 5 Frontend",
        task_content=task,
        model=MODEL_A5,
        include_static=["coding_standards"],
        repo_path=state["repo_path"],
    )
    save_agent_output(state["feature_id"], f"a5_frontend_iter{state['qa_iterations']}", output)
    return {
        "frontend_code": output,
        "current_agent": "a5_frontend",
        "cost_entries": [cost],
    }
