"""
Agente 1 — PM Final (cierre del ciclo).

Siempre es el primero (planificador) y el último (revisor/cierre).

Responsabilidades en el cierre:
  1. Revisión de cumplimiento REAL: lee los archivos escritos en disco (no el estado)
     y compara contra los criterios de aceptación del MASTER_PLAN
  2. Documentación: docstrings, @extend_schema, CHANGELOG
  3. Reporte de costos del ciclo
  4. G7: Crear feature branch 'feature/YYYYMMDD-slug'
  5. G6: git add selectivo de files_written (no git add .)
  6. Commit + Push + PR en el repositorio → dispara CI/CD automáticamente
  7. Notificación Telegram al completar
"""
from __future__ import annotations
import logging
import re
from datetime import datetime
from pathlib import Path

from state import FabricaState
from nodes.base import call_agent
from tools.file_tools import save_agent_output, save_run_metadata
from tools.cost_tracker import format_cost_report
from tools.git_tools import (
    current_branch,
    create_feature_branch,
    stage_files,
    stage_all,
    commit,
    push_branch,
    create_pr,
)
from tools.telegram import notify_feature_done
from config import MODEL_PM

logger = logging.getLogger(__name__)

_MAX_FILE_PREVIEW = 1000   # chars por archivo en el contexto de revisión
_MAX_FILES_IN_CTX = 25     # máximo archivos a incluir en el contexto del LLM


def _read_written_files(repo_path: str, files_written: list[str]) -> str:
    """
    Lee los archivos reales del disco para que el PM pueda verificar el cumplimiento.
    Limita el contexto para no exceder el token budget.
    """
    if not files_written or not repo_path:
        return ""

    lines = ["## ARCHIVOS ESCRITOS AL REPOSITORIO (contenido real en disco)\n"]
    shown = files_written[:_MAX_FILES_IN_CTX]
    omitted = len(files_written) - len(shown)

    for rel_path in shown:
        full = Path(repo_path) / rel_path
        if full.exists():
            try:
                content = full.read_text(encoding="utf-8", errors="replace")
                preview = content[:_MAX_FILE_PREVIEW]
                truncated = f"\n…[{len(content) - _MAX_FILE_PREVIEW} chars más]" if len(content) > _MAX_FILE_PREVIEW else ""
                lines.append(f"### `{rel_path}` ({len(content)} chars)\n```\n{preview}{truncated}\n```\n")
            except Exception as exc:
                lines.append(f"### `{rel_path}` ⚠️ Error al leer: {exc}\n")
        else:
            lines.append(f"### `{rel_path}` ⚠️ No encontrado en disco (dry-run o error de escritura)\n")

    if omitted:
        lines.append(f"\n_…y {omitted} archivo(s) más (omitidos para no exceder contexto)._\n")

    return "\n".join(lines)


def a1_pr_final(state: FabricaState) -> dict:
    cost_table  = format_cost_report(state.get("cost_entries", []))
    total_cost  = sum(e.get("cost_usd", 0) for e in state.get("cost_entries", []))
    repo_name   = state["repo_name"]
    repo_path   = state["repo_path"]
    files_written: list[str] = state.get("files_written", [])
    migration_note: str = state.get("migration_note") or ""

    # Resumen del ciclo SecOps
    secops_note = ""
    if state.get("secops_iterations", 0) > 0:
        secops_note = (
            f"\nSecOps aplicó correcciones de seguridad "
            f"({state['secops_iterations']} iteración/es de revisión)."
        )

    # ── Leer archivos reales del disco para revisión de cumplimiento ──────────
    actual_files_context = _read_written_files(repo_path, files_written)

    files_list_md = ""
    if files_written:
        files_list_md = "\n**Archivos escritos al repo:**\n" + "\n".join(f"- `{f}`" for f in sorted(files_written))

    migration_section = ""
    if migration_note:
        migration_section = f"\n## MIGRACIONES DJANGO\n{migration_note}\n"

    task = f"""
Eres el Agente 1 — PM (Project Manager). Eres el ÚLTIMO agente del ciclo.
Tu rol es cerrar el feature con calidad: verificar cumplimiento REAL, documentar y crear el PR.

## MASTER_PLAN (objetivo original y criterios de aceptación)
---
{state['master_plan']}
---

{actual_files_context}

## REPORTE QA FINAL
---
{state.get('qa_report', 'No disponible')}
---

## REPORTE DE COSTOS
{cost_table}
{secops_note}
{migration_section}
---

## TU TAREA EN CUATRO PARTES OBLIGATORIAS

### PARTE 1 — REVISIÓN DE CUMPLIMIENTO REAL

Lee el código REAL que fue escrito al repositorio (sección "ARCHIVOS ESCRITOS AL REPOSITORIO").
Compara cada criterio de aceptación del MASTER_PLAN contra el código en disco.
Para cada criterio, marca:
  ✅ Cumplido — el código en disco lo implementa correctamente
  ⚠️ Parcial — está implementado pero incompleto o con caveats
  ❌ No cumplido — no está en el código escrito

Sé estrictamente honesto. Si no encontraste evidencia del criterio en el código escrito → ❌.
Finaliza esta parte con: `CUMPLIMIENTO: COMPLETO | PARCIAL | INCOMPLETO`

### PARTE 2 — DOCUMENTACIÓN

Genera la documentación del código:
- Docstrings en funciones/clases donde el WHY no sea obvio (una línea, no el QUÉ)
- `@extend_schema` para cada endpoint nuevo o modificado (si aplica)
- Entrada en CHANGELOG.md bajo `[Unreleased]`:
  ```
  ### Added / Changed / Fixed
  - [descripción del cambio para el usuario final]
  ```
- Si hay migraciones Django, añadir nota: "⚠️ Ejecutar `python manage.py migrate` al desplegar"
- Si el feature cambia el estado de algún módulo en PROJECT_CONTEXT.md, indica qué actualizar

### PARTE 3 — MENSAJE DEL PR

Genera el mensaje completo del Pull Request:

**Título:** `feat([modulo]): [descripción en una línea]`

**Cuerpo:**
- Descripción del feature (lenguaje de negocio, no técnico)
- Tabla de revisión de cumplimiento (del Paso 1)
{files_list_md}
- Cobertura de tests (del reporte QA)
- Clearance de seguridad (✅ si SecOps no bloqueó)
- Tabla de costos del ciclo
- Deuda técnica pendiente (si la hay)
- Próximos pasos sugeridos

### PARTE 4 — COMMIT MESSAGE

Genera el mensaje de commit (convención Conventional Commits):
```
feat([modulo]): [descripción corta]

[descripción extensa opcional]

🤖 Generado por Fábrica de Software
Repo: {repo_name}
Costo: ${total_cost:.4f} USD
```

Al final escribe: `✅ CICLO COMPLETADO`
"""
    pr_message, cost = call_agent(
        agent_key="a1_pm",
        agent_label="Agente 1 PM (Cierre)",
        task_content=task,
        model=MODEL_PM,
        include_static=[],
        repo_path=repo_path,
    )

    save_agent_output(state["feature_id"], "a1_pr_final", pr_message)
    save_run_metadata(state["feature_id"], {
        "completed_at":   datetime.utcnow().isoformat(),
        "total_cost_usd": total_cost + cost.get("cost_usd", 0),
        "status":         "completado",
    })

    # ── Extraer título y mensaje de commit del output del PM ──────────────────
    title_line = next(
        (l.lstrip("# ").strip() for l in pr_message.splitlines()
         if l.strip().startswith("feat(")),
        f"feat: {state['feature_name']}",
    )

    commit_block = re.search(
        r"```\s*\n(feat\([^)]+\):.*?)```",
        pr_message, re.DOTALL,
    )
    commit_text = (
        commit_block.group(1).strip()
        if commit_block
        else f"{title_line}\n\n🤖 Fábrica de Software — repo: {repo_name}"
    )

    # ── G7: Crear feature branch antes del commit ─────────────────────────────
    pr_url = ""
    feature_branch = state.get("feature_branch") or ""

    try:
        if not feature_branch:
            feature_branch = create_feature_branch(state["feature_name"], repo_path)
            if not feature_branch:
                logger.warning("No se pudo crear feature branch — usando rama actual")
                feature_branch = current_branch(repo_path)

        # ── G6: Stage selectivo de archivos escritos por A10 ─────────────────
        staged = False
        if files_written:
            staged = stage_files(files_written, repo_path)
            if not staged:
                logger.warning("stage_files falló — fallback a stage_all")
                staged = stage_all(repo_path)
        else:
            # Sin archivos escritos (dry-run o feature 100% en state)
            staged = stage_all(repo_path)

        if staged and commit(commit_text, repo_path):
            # Push de la feature branch + crear PR
            push_branch(feature_branch, repo_path)
            pr_url = create_pr(title_line, pr_message, repo_path)
            if pr_url.startswith("ERROR"):
                logger.warning("PR no creado automáticamente: %s", pr_url)
                pr_url = ""
            else:
                logger.info("PR creado: %s", pr_url)
        else:
            logger.warning("commit falló — posiblemente nothing to commit")

    except Exception as exc:
        logger.exception("Error al crear commit/PR: %s", exc)

    # ── Notificación Telegram ─────────────────────────────────────────────────
    notify_feature_done(
        feature_name=state["feature_name"],
        project_name=state.get("project_id"),
        cost_usd=total_cost + cost.get("cost_usd", 0),
        pr_url=pr_url,
    )

    return {
        "pr_message":     pr_message,
        "feature_branch": feature_branch,
        "current_agent":  "a1_pr_final",
        "cost_entries":   [cost],
        "errors":         [] if pr_url else ["PR no creado automáticamente — revisa el repo"],
    }
