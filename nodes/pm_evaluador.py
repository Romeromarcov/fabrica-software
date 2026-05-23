"""
PM Evaluador — verifica si un feature fue completado correctamente.

Estrategia:
1. Lee los outputs del run completado (MASTER_PLAN, PR message, QA report)
2. Usa OpenClaw (si está habilitado) para verificar el repo real
3. Emite veredicto: COMPLETADO / PARCIAL / FALLIDO
4. Puede sugerir nuevos features o ajustes al backlog
"""
import json
import re
import logging
from project_state import ProjectState, FeatureTask
from nodes.base import call_agent, USE_OPENCLAW
from tools.file_tools import save_run_metadata, RUNS_DIR
from config import MODEL_A1

logger = logging.getLogger(__name__)


def _read_run_outputs(feature_id: str) -> str:
    """Recopila los outputs del run para dárselos al evaluador."""
    run_dir = RUNS_DIR / feature_id
    if not run_dir.exists():
        return f"Run {feature_id} no encontrado en data/runs/"

    parts = []

    # Metadata
    meta_path = run_dir / "metadata.json"
    if meta_path.exists():
        meta = json.loads(meta_path.read_text())
        parts.append(f"**STATUS:** {meta.get('status', '?')}")
        parts.append(f"**COST:** ${meta.get('total_cost_usd', 0):.4f} USD")

    # PR message (el más informativo)
    pr_path = run_dir / "output_a1_pr_final.md"
    if pr_path.exists():
        parts.append(f"\n### PR FINAL\n{pr_path.read_text(encoding='utf-8')[:2000]}")

    # QA report — A-12: el QA lo genera A7, no A4
    qa_files = sorted(run_dir.glob("output_a7_qa_iter*.md"))
    if qa_files:
        parts.append(f"\n### ÚLTIMO QA REPORT\n{qa_files[-1].read_text(encoding='utf-8')[:1500]}")

    # Refactor doc — A-12: lo genera A6, no A5
    a6_path = run_dir / "output_a6_refactor.md"
    if a6_path.exists():
        parts.append(f"\n### REPORTE REFACTOR (A6)\n{a6_path.read_text(encoding='utf-8')[:1000]}")

    return "\n\n".join(parts) if parts else "Sin outputs disponibles."


def pm_evaluador(state: ProjectState) -> dict:
    idx     = state["current_feature_index"]   # advance_index corre DESPUÉS de pm_evaluador
    backlog = list(state["backlog"])

    if idx < 0 or idx >= len(backlog):
        logger.warning("pm_evaluador llamado con índice fuera de rango: %d", idx)
        return {}

    feature    = backlog[idx]
    feature_id = feature.get("feature_id", "")
    run_summary = _read_run_outputs(feature_id) if feature_id else "Sin feature_id"

    # ── Construir tarea del evaluador ─────────────────────────────────────────
    verification_instruction = ""
    if USE_OPENCLAW:
        verification_instruction = f"""
VERIFICACIÓN EN EL REPOSITORIO REAL:
Usa tus herramientas de filesystem para verificar en {state['repo_path']} que:
1. Los archivos mencionados en el PR realmente existen y tienen contenido
2. Los tests pasan (si puedes ejecutar `python manage.py test` o `pytest`)
3. No hay imports rotos ni errores de sintaxis evidentes

Reporta exactamente qué encontraste (rutas reales, nombres de funciones clave).
"""
    else:
        verification_instruction = """
NOTA: OpenClaw no está activo. Basa tu evaluación en los outputs del pipeline.
"""

    # Calcular progreso
    completed = sum(1 for f in backlog if f["status"] == "completed")
    total     = len(backlog)

    task = f"""
Eres el PM Evaluador — tu función es verificar si el feature fue completado correctamente
y mantener el norte del proyecto.

## PROYECTO
**Nombre:** {state['project_name']}
**Repositorio:** {state['repo_path']}
**Progreso:** {completed}/{total} features completados

## ROADMAP DEL PROYECTO
{(state.get('roadmap') or '')[:1500]}
---

## FEATURE EVALUADO
**Nombre:** {feature['name']}
**Descripción:** {feature['description']}
**Fase:** {feature['phase']}
**Criterios de aceptación:**
{feature['acceptance_criteria']}

## OUTPUTS DEL PIPELINE
{run_summary}

{verification_instruction}

## TU TAREA

**PASO 1 — EVALUACIÓN**
Determina si el feature cumplió sus criterios de aceptación.
Al final de esta sección escribe EXACTAMENTE una de:
- `VEREDICTO: COMPLETADO` — todos los criterios cumplidos
- `VEREDICTO: PARCIAL` — la mayoría cumplidos, deuda técnica aceptable
- `VEREDICTO: FALLIDO` — criterios críticos incumplidos

**PASO 2 — ESTADO DEL PROYECTO**
Con base en el progreso actual, responde:
1. ¿El proyecto va por buen camino hacia el objetivo?
2. ¿Hay algo que debería reordenarse en el backlog restante?
3. ¿Detectas necesidades no contempladas originalmente?

**PASO 3 — SUGERENCIAS** (opcional pero valioso)
Si detectas features adicionales necesarios o ajustes al plan, listarlos en formato:
```sugerencias
SUGERENCIA-001: [nombre del feature] — [descripción breve] — Prioridad: [alta/media/baja]
SUGERENCIA-002: ...
```
Solo incluye sugerencias reales y fundamentadas.
"""

    output, cost = call_agent(
        agent_key="a1_pm",
        agent_label=f"PM Evaluador ({feature['name'][:30]})",
        task_content=task,
        model=MODEL_A1,
        include_static=[],
        repo_path=state["repo_path"],
    )

    # ── Parsear veredicto ─────────────────────────────────────────────────────
    verdict_match = re.search(r"VEREDICTO:\s*(COMPLETADO|PARCIAL|FALLIDO)", output, re.IGNORECASE)
    verdict = verdict_match.group(1).upper() if verdict_match else "PARCIAL"

    new_status: str
    if verdict == "COMPLETADO":
        new_status = "completed"
    elif verdict == "PARCIAL":
        new_status = "completed"   # Parcial se acepta y avanza
    else:
        new_status = "failed"

    # ── Actualizar backlog ────────────────────────────────────────────────────
    backlog[idx] = FeatureTask(
        **{**backlog[idx], "status": new_status, "evaluation_notes": output[:500]},
    )

    # ── Parsear sugerencias ───────────────────────────────────────────────────
    suggestions: list[str] = []
    sug_match = re.search(r"```sugerencias\s*(.*?)\s*```", output, re.DOTALL)
    if sug_match:
        for line in sug_match.group(1).splitlines():
            line = line.strip()
            if line.startswith("SUGERENCIA-"):
                suggestions.append(line)

    # ── Calcular progreso ─────────────────────────────────────────────────────
    completed_now = sum(1 for f in backlog if f["status"] in ("completed", "failed"))
    progress = round(completed_now / total * 100, 1) if total else 0.0

    # ── Persistir evaluación ──────────────────────────────────────────────────
    save_run_metadata(state["project_id"], {
        f"eval_{feature['name'][:30]}": {"verdict": verdict, "notes": output[:300]},
    })

    logger.info(
        "PM Evaluador: %s → %s | progreso %s%%",
        feature["name"], verdict, progress,
    )

    eval_entry = {
        "feature": feature["name"],
        "feature_id": feature_id,
        "verdict": verdict,
        "summary": output[:300],
    }

    return {
        "backlog": backlog,
        "suggestions": state.get("suggestions", []) + suggestions,
        "progress_pct": progress,
        "evaluation_history": [eval_entry],
        "cost_entries": [cost],
    }
