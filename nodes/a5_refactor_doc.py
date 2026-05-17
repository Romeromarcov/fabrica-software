"""Agente 5 — Refactor + Doc. El filtro final antes del PR."""
from state import FabricaState
from nodes.base import call_agent
from tools.file_tools import save_agent_output
from config import MODEL_A5


def a5_refactor_doc(state: FabricaState) -> dict:
    task = f"""
Eres el Agente 5 — Refactor + Doc. Eres el ÚLTIMO agente que toca el código.

CÓDIGO BACKEND (Agente 2):
---
{state.get('backend_code', '')}
---

CÓDIGO FRONTEND (Agente 3):
---
{state.get('frontend_code', '')}
---

TESTS (Agente 4 — iteración final):
---
{state.get('qa_report', '')}
---

SECURITY CLEARANCE (Agente 7 Rev.2):
---
{state.get('security_block_2') or 'Security Clearance emitido — sin bloqueantes'}
---

MASTER_PLAN (para CHANGELOG y @extend_schema):
---
{state['master_plan']}
---

Tu tarea en DOS PARTES INDIVISIBLES:

PARTE 1 — REFACTOR (Anti-Frankenstein):
Aplica CODING_STANDARDS.md sobre todo el código. Corrige:
- Logger no definido al tope del archivo
- bare excepts → except Exception as e: + logger.exception()
- unique global en campo multi-tenant → unique_together con id_empresa
- get_queryset sin filtro de empresa
- any en TypeScript → tipos explícitos
- useEffect para fetch → TanStack Query
- console.log en producción → eliminar
- Lógica de negocio en ViewSets → mover a services
- Componentes >300 líneas → dividir
- Código muerto, imports sin usar → eliminar

PARTE 2 — DOC:
- Docstrings solo donde el WHY no es obvio (una línea, no el QUÉ)
- @extend_schema para cada endpoint nuevo
- Entrada en CHANGELOG.md bajo [Unreleased]
- Si el feature cambia el estado de algún módulo en PROJECT_CONTEXT.md, indícalo

Al final escribe:
"## REPORTE AGENTE 5" con la tabla de cambios y el checklist.
La última línea DEBE ser exactamente: "✅ LISTO PARA PR"
"""
    output, cost = call_agent(
        agent_key="a5_refactor",
        agent_label="Agente 5 Refactor+Doc",
        task_content=task,
        model=MODEL_A5,
        repo_path=state["repo_path"],
    )
    save_agent_output(state["feature_id"], "a5_refactor_doc", output)

    approved = "✅ LISTO PARA PR" in output

    return {
        "refactor_doc_output": output,
        "refactor_doc_approved": approved,
        "current_agent": "a5_refactor_doc",
        "cost_entries": [cost],
        "errors": [] if approved else ["Agente 5 no emitió '✅ LISTO PARA PR' — revisar output"],
    }
