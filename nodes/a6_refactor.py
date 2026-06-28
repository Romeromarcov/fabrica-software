"""
Agente 6 — Refactor, Unificador y Corrector de Código.

Posición en el pipeline:
  A2+A3 → A4+A5 → **A6** → A7 QA (↺ si QA falla, vuelve a A6) → A8 SecOps → PM Final

Responsabilidades:
  - Revisar y unificar el trabajo de A2 (DB), A3 (MCP), A4 (Backend), A5 (Frontend)
  - Refactorizar para cumplir CODING_STANDARDS
  - Corregir errores críticos detectados (propios o reportados por QA)
  - NO documenta (la documentación es responsabilidad del PM Final)
"""
from state import FabricaState
from nodes.base import call_agent
from tools.file_tools import save_agent_output
from tools.telegram import notify_escalation
from config import MODEL_A6


def a6_refactor(state: FabricaState) -> dict:
    from tools.architecture_record import adr_context_block
    from tools.context_retriever import get_relevant_context
    adr_block = adr_context_block(state["repo_path"])
    # F6 — A6 unifica/corrige el código: debe respetar el LAYOUT y estilo de import REALES del
    # repo (fingerprint), para no reintroducir una estructura genérica `app/...` al refactorizar.
    fingerprint_block = get_relevant_context(state["repo_path"])

    # Contexto adicional si venimos de un retry de QA
    qa_feedback = ""
    if state.get("qa_report") and state.get("qa_iterations", 0) > 0:
        qa_feedback = f"""
⚠️  CONTEXTO: Este es el intento #{state['qa_iterations']} — QA falló en la ronda anterior.
INFORME DE QA:
---
{state.get('qa_report', '')[:2000]}
---
Ten en cuenta estos fallos al revisar el código. Los bugs que reportó QA deben
estar corregidos en el código que estás revisando ahora.
"""

    # IV-1: Contexto de sandbox con fallos por gate (quirúrgico)
    sandbox_feedback = ""
    gate_failures: list[dict] = state.get("sandbox_gate_failures", [])
    if gate_failures and not state.get("sandbox_passed", True) and state.get("sandbox_iterations", 0) > 0:
        from tools.code_sandbox import format_failures_for_agent
        # Reconstruir el dict result mínimo que espera format_failures_for_agent
        sandbox_feedback = format_failures_for_agent({"gate_failures": gate_failures})
        # Encabezado adicional para A6
        sandbox_feedback = f"\n{sandbox_feedback}\n"
    elif state.get("sandbox_results") and not state.get("sandbox_passed", True) and state.get("sandbox_iterations", 0) > 0:
        # Fallback si no hay gate_failures estructurados
        sandbox_feedback = f"""
SANDBOX EXECUTION FAILURES — MAXIMA PRIORIDAD:
---
{state.get('sandbox_results', '')[:3000]}
---
Estos errores fueron detectados ejecutando el codigo REAL. Corrigelos antes de aprobar.
"""

    # Incluir outputs de infraestructura si existen (modo completo)
    infra_block = ""
    if state.get("db_schema") or state.get("mcp_tools"):
        infra_block = f"""
ESQUEMA DE BASE DE DATOS (Agente 2):
---
{state.get('db_schema', 'No aplica (modo lite)') or 'No aplica (modo lite)'}
---

HERRAMIENTAS MCP (Agente 3):
---
{state.get('mcp_tools', 'No aplica (modo lite)') or 'No aplica (modo lite)'}
---
"""

    task = f"""
Eres el Agente 6 — Revisor y Unificador de Código.
{adr_block}{fingerprint_block}
⚠️ Respeta el LAYOUT y estilo de import REALES del repo (fingerprint arriba). No muevas el código
a una estructura genérica `app/api/v1/...` ni cambies el estilo de import si el repo no lo usa.

Tu posición en el pipeline: A2+A3 → A4+A5 → **TÚ** → A7 QA → A8 SecOps → PR

Tienes acceso a TODO el trabajo del pipeline: esquema DB, herramientas MCP,
backend y frontend. Tu misión es unificar y asegurar coherencia entre todas
las capas antes de que QA ejecute los tests.

MASTER_PLAN (referencia del feature):
---
{state['master_plan']}
---
{infra_block}
CÓDIGO BACKEND (Agente 4):
---
{state.get('backend_code', 'Sin output del Agente 4')}
---

CÓDIGO FRONTEND (Agente 5):
---
{state.get('frontend_code', 'Sin output del Agente 5')}
---
{qa_feedback}{sandbox_feedback}

## PARTE 1 — REVISIÓN Y UNIFICACIÓN (obligatoria)

Revisa TODOS los outputs como un sistema coherente. Detecta y corrige:

**Coherencia entre capas (infraestructura ↔ código):**
- ¿Los modelos Django coinciden con el esquema DB propuesto por A2?
- ¿El backend usa las herramientas MCP definidas por A3 (si las hay)?
- ¿Los serializers/schemas reflejan exactamente los campos del modelo DB?
- ¿Los endpoints del backend coinciden con las llamadas del frontend?
- ¿Los tipos/interfaces TS coinciden con lo que devuelve la API?
- ¿Los nombres de campos son consistentes en todas las capas?

**Errores de código obvios:**
- Logger no definido al inicio del archivo
- `bare except` → `except Exception as e: logger.exception()`
- `unique` global en campo multi-tenant → `unique_together` con `id_empresa`
- `get_queryset` sin filtro de empresa
- `any` en TypeScript → tipos explícitos
- Lógica de negocio en ViewSets → mover a services
- `console.log` sin condición de entorno → eliminar o envolver

**Estilo y estructura:**
- Imports sin usar → eliminar
- Código muerto o comentado → eliminar
- `useEffect` para fetch de datos → sugerencia TanStack Query (no bloquea)
- Componentes >300 líneas → señalar para división (no bloquea)

## REPORTE FINAL

Al final incluye "## REPORTE AGENTE 6" con:
| Categoría | Problema encontrado | Corrección aplicada |
|-----------|--------------------|--------------------|
| ...       | ...                | ...                |

**Criterio de aprobación:**
- Si encontraste problemas y los corregiste → aprobado
- Si el código tiene errores CRÍTICOS imposibles de resolver sin re-implementar → reporta el bloqueante
- Casos como inconsistencias menores, TODOs, sugerencias → no bloquean

La última línea DEBE ser exactamente una de:
- `✅ LISTO PARA QA` — código revisado y unificado, QA puede proceder
- `🚫 BLOQUEANTE CRÍTICO: [descripción en una línea]` — re-implementación necesaria
"""
    output, cost = call_agent(
        agent_key="a6_refactor",
        agent_label="Agente 6 Revisor/Unificador",
        task_content=task,
        model=MODEL_A6,
        repo_path=state["repo_path"],
    )
    save_agent_output(state["feature_id"], "a6_refactor", output)

    approved = "✅ LISTO PARA QA" in output
    bloqueante = "🚫 BLOQUEANTE CRÍTICO" in output

    # M4 (PLAN_PLATAFORMA_V2): diff inteligente entrada↔salida. Mide cuánto reescribió
    # A6 respecto al código que recibió de A4/A5. Observacional por defecto; si
    # INTELLIGENT_DIFF_GATE está on y el ratio supera el umbral, escala (sobre-refactor).
    import logging as _diff_log
    _diff_logger = _diff_log.getLogger(__name__)
    refactor_change_ratio = 0.0
    try:
        from config import INTELLIGENT_DIFF_GATE, INTELLIGENT_DIFF_THRESHOLD
        from tools.code_diff import diff_report
        before_code = (state.get("backend_code", "") or "") + "\n" + (state.get("frontend_code", "") or "")
        rep = diff_report(before_code, output, threshold=INTELLIGENT_DIFF_THRESHOLD)
        refactor_change_ratio = rep.change_ratio
        if INTELLIGENT_DIFF_GATE and rep.exceeds_threshold and before_code.strip():
            _diff_logger.warning(
                "A6: ratio de cambio %.2f supera el umbral %.2f — posible sobre-refactor",
                rep.change_ratio, rep.threshold,
            )
            notify_escalation(
                feature_name=state.get("feature_name", state["feature_id"]),
                reason=(f"A6 diff inteligente — reescritura {rep.change_ratio:.0%} "
                        f"(> {rep.threshold:.0%}); revisar sobre-refactor"),
                project_name=state.get("project_name"),
            )
    except Exception as _diff_exc:
        _diff_logger.warning("diff inteligente A6 falló (ignorado): %s", _diff_exc)

    # Actualizar memoria del proyecto cuando el código es aprobado
    if approved and state.get("project_id"):
        try:
            from tools.project_memory import update_memory
            update_memory(
                project_id=state["project_id"],
                feature_name=state.get("feature_name", ""),
                feature_id=state["feature_id"],
                backend_code=state.get("backend_code", ""),
                frontend_code=state.get("frontend_code", ""),
                db_schema=state.get("db_schema", ""),
            )
        except Exception:
            pass  # Best-effort

    if bloqueante:
        razon = output.split("🚫 BLOQUEANTE CRÍTICO:")[-1][:200].strip()
        notify_escalation(
            feature_name=state.get("feature_name", state["feature_id"]),
            reason=f"A6 Revisor/Refactor — Bloqueante crítico: {razon}",
            project_name=state.get("project_name"),
        )

    return {
        "refactor_doc_output": output,
        "refactor_doc_approved": approved,
        "refactor_change_ratio": refactor_change_ratio,
        "current_agent": "a6_refactor",
        "cost_entries": [cost],
        "errors": (
            []
            if approved
            else [
                f"Agente 6 — Bloqueante crítico detectado: {output.split('🚫 BLOQUEANTE CRÍTICO:')[-1][:150].strip()}"
                if bloqueante
                else "Agente 6 no emitió token de aprobación — revisar output"
            ]
        ),
    }
