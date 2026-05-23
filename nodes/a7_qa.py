"""Agente 7 — QA Test. Genera tests y detecta bugs. Respeta el max_retries."""
from state import FabricaState
from nodes.base import call_agent
from tools.file_tools import save_agent_output
from config import MAX_QA_ITER_COMPLETO, MAX_QA_ITER_LITE, MODEL_A7


def a7_qa(state: FabricaState) -> dict:
    from tools.architecture_record import adr_context_block
    from tools.stack_reader import read_stack, get_qa_instructions
    adr_block = adr_context_block(state["repo_path"])

    # Instrucciones de testing del stack real
    stack = read_stack(state["repo_path"])
    qa_instructions = get_qa_instructions(stack)
    stack_block = f"\n## INSTRUCCIONES DE TESTING\n{qa_instructions}\n" if qa_instructions else ""

    iteration    = state["qa_iterations"] + 1
    max_iter     = MAX_QA_ITER_COMPLETO if state["mode"] == "completo" else MAX_QA_ITER_LITE
    secops_iter  = state.get("secops_iterations", 0)

    # Contexto adicional según el origen del retest
    retest_note = ""
    if secops_iter > 0:
        retest_note = (
            f"\n⚠️  RETEST POST-SECOPS (iteración SecOps {secops_iter}):\n"
            f"SecOps aplicó correcciones de seguridad al código. Verifica que:\n"
            f"1. Las vulnerabilidades de seguridad reportadas estén corregidas\n"
            f"2. La funcionalidad original siga operando correctamente\n"
        )

    task = f"""
Eres el Agente 7 — QA Test. Esta es la iteración QA {iteration} de máximo {max_iter}.
{adr_block}{stack_block}{retest_note}
CRITERIOS DE ACEPTACIÓN (del MASTER_PLAN):
---
{state['master_plan']}
---

CÓDIGO BACKEND:
---
{state.get('backend_code', '')}
---

CÓDIGO FRONTEND:
---
{state.get('frontend_code', '')}
---

Tu tarea: genera los tests completos y verifica los criterios de aceptación.
Sigue las instrucciones de testing del stack de arriba.
Si no hay instrucciones específicas de stack, usa las mejores prácticas del framework detectado.

MÍNIMO obligatorio para cualquier stack:
1. Tests de autenticación/permisos (401/403 para usuarios sin acceso)
2. Tests del happy path de cada endpoint o componente
3. Tests de casos límite (vacíos, nulos, valores extremos)
4. Tests de estados de error

Para cada test file usa el formato estándar:
```[extensión]
# === tests/test_[modulo].py === (o ruta equivalente del stack)
[código de tests completo]
```

Al final de tu output, escribe UNA de estas dos líneas exactas:
- "QA_RESULT: PASSED" — si el código supera todos los criterios
- "QA_RESULT: FAILED" — si hay bugs (lista los bugs con archivo:línea)

Si el resultado es FAILED, incluye una sección "## BUGS ENCONTRADOS" con formato:
BUG-001 | CRÍTICO | archivo.py:45 | descripción del bug
"""
    output, cost = call_agent(
        agent_key="a7-qa",
        agent_label=f"Agente 7 QA (iter {iteration})",
        task_content=task,
        model=MODEL_A7,
        include_static=["coding_standards"],
        repo_path=state["repo_path"],
    )
    save_agent_output(state["feature_id"], f"a7_qa_iter{iteration}", output)

    passed = "QA_RESULT: PASSED" in output

    return {
        "qa_report": output,
        "qa_passed": passed,
        "qa_iterations": iteration,
        "current_agent": "a7_qa",
        "cost_entries": [cost],
    }
