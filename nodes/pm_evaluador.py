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
from tools.quality_tracker import compute_trend, propose_standards_update
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

    # Code Writer output (qué archivos se escribieron)
    a10_path = run_dir / "output_a10_code_writer.md"
    if a10_path.exists():
        parts.append(f"\n### ARCHIVOS ESCRITOS (A10)\n{a10_path.read_text(encoding='utf-8')[:500]}")

    return "\n\n".join(parts) if parts else "Sin outputs disponibles."


def _read_written_files_from_disk(feature_id: str, repo_path: str) -> str:
    """
    Lee el contenido real de los archivos escritos al disco por A10.
    Primario para verificar cumplimiento — no depende de OpenClaw.
    """
    from pathlib import Path as _Path

    run_dir = RUNS_DIR / feature_id
    meta_path = run_dir / "metadata.json"

    # Obtener lista de archivos escritos desde metadata (guardados por A1 PR Final)
    files_written: list[str] = []
    if meta_path.exists():
        try:
            meta = json.loads(meta_path.read_text())
            # files_written puede estar en metadata si A1 lo guardó
            files_written = meta.get("files_written", [])
        except Exception:
            pass

    # Si no hay lista en metadata, intentar leerla del output de A10
    if not files_written:
        a10_path = run_dir / "output_a10_code_writer.md"
        if a10_path.exists():
            content = a10_path.read_text(encoding="utf-8")
            # Parsear las líneas "- `ruta/archivo.ext`"
            for line in content.splitlines():
                m = re.search(r"`([^`]+\.[a-zA-Z0-9]+)`", line)
                if m and "/" in m.group(1):
                    files_written.append(m.group(1))

    if not files_written or not repo_path:
        return ""

    _MAX_PER_FILE = 800
    _MAX_FILES    = 20
    lines = [f"## ARCHIVOS ESCRITOS AL DISCO ({len(files_written)} total)\n"]

    for rel_path in files_written[:_MAX_FILES]:
        full = _Path(repo_path) / rel_path
        if full.exists():
            try:
                content = full.read_text(encoding="utf-8", errors="replace")
                preview = content[:_MAX_PER_FILE]
                extra   = f"\n…[+{len(content)-_MAX_PER_FILE} chars]" if len(content) > _MAX_PER_FILE else ""
                lines.append(f"### `{rel_path}`\n```\n{preview}{extra}\n```\n")
            except Exception as e:
                lines.append(f"### `{rel_path}` — error al leer: {e}\n")
        else:
            lines.append(f"### `{rel_path}` — ⚠️ no encontrado en disco\n")

    if len(files_written) > _MAX_FILES:
        lines.append(f"_…y {len(files_written)-_MAX_FILES} archivo(s) más._\n")

    return "\n".join(lines)


def pm_evaluador(state: ProjectState) -> dict:
    idx     = state["current_feature_index"]   # advance_index corre DESPUÉS de pm_evaluador
    backlog = list(state["backlog"])

    if idx < 0 or idx >= len(backlog):
        logger.warning("pm_evaluador llamado con índice fuera de rango: %d", idx)
        return {}

    feature    = backlog[idx]
    feature_id = feature.get("feature_id", "")
    run_summary = _read_run_outputs(feature_id) if feature_id else "Sin feature_id"

    # ── Leer archivos reales del disco (nativo, siempre disponible) ──────────
    real_files_context = ""
    if feature_id:
        real_files_context = _read_written_files_from_disk(feature_id, state.get("repo_path", ""))

    # ── Instrucción de verificación: OpenClaw refuerza la lectura nativa ──────
    verification_instruction = ""
    if USE_OPENCLAW:
        verification_instruction = f"""
VERIFICACIÓN ADICIONAL CON OPENCLAW:
Los archivos ya están listados abajo (lectura nativa), pero también puedes usar
tus herramientas de filesystem en {state['repo_path']} para verificar:
- Que los tests pasan: `python manage.py test` o `pytest`
- Imports correctos y sin errores de sintaxis
- Integración entre archivos (que los imports entre módulos funcionen)
"""
    else:
        verification_instruction = """
NOTA: OpenClaw no activo — usando lectura nativa de archivos (ver sección ARCHIVOS EN DISCO).
"""

    # Calcular progreso
    completed = sum(1 for f in backlog if f["status"] == "completed")
    total     = len(backlog)

    # ── Métricas de calidad del proyecto (Bloque I-2) ─────────────────────────
    quality_block = ""
    project_id = state.get("project_id", "")
    if project_id:
        trend = compute_trend(project_id, last_n=10)
        if trend.get("total_features", 0) > 0:
            direction_emoji = {"mejorando": "📈", "estable": "➡️", "empeorando": "📉"}.get(
                trend["direction"], "❓"
            )
            quality_block = (
                f"\n## MÉTRICAS DE CALIDAD DEL PIPELINE\n"
                f"- Features completados: {trend['total_features']}\n"
                f"- QA iterations promedio: {trend['avg_qa_iters']}\n"
                f"- Quality score promedio: {trend['avg_score']}/100\n"
                f"- Tendencia: {direction_emoji} {trend['direction']}\n"
                f"- Features con ≤1 iteración QA: {trend['zero_qa_pct']}%\n"
            )
            if trend.get("recurring_patterns"):
                quality_block += f"- Patrones recurrentes: {', '.join(trend['recurring_patterns'])}\n"

        proposal = propose_standards_update(project_id)
        if proposal:
            quality_block += f"\n{proposal}\n"

    task = f"""
Eres el PM Evaluador — tu función es verificar si el feature fue completado correctamente
y mantener el norte del proyecto.

## PROYECTO
**Nombre:** {state['project_name']}
**Repositorio:** {state['repo_path']}
**Progreso:** {completed}/{total} features completados
{quality_block}

## ROADMAP DEL PROYECTO
{(state.get('roadmap') or '')[:1500]}
---

## FEATURE EVALUADO
**Nombre:** {feature['name']}
**Descripción:** {feature['description']}
**Fase:** {feature['phase']}
**Criterios de aceptación:**
{feature['acceptance_criteria']}

## OUTPUTS DEL PIPELINE (logs del proceso)
{run_summary}

{real_files_context}

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
