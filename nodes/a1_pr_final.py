"""
Agente 1 — PM Final (cierre del ciclo).

Siempre es el primero (planificador) y el último (revisor/cierre).

Responsabilidades en el cierre:
  1. Revisión de cumplimiento: ¿se completó el MASTER_PLAN?
  2. Documentación: docstrings, @extend_schema, CHANGELOG
  3. Reporte de costos del ciclo
  4. Commit + PR en el repositorio
  5. Notificación Telegram al completar
"""
from __future__ import annotations
import logging
from datetime import datetime

from state import FabricaState
from nodes.base import call_agent
from tools.file_tools import save_agent_output, save_run_metadata
from tools.cost_tracker import format_cost_report
from tools.git_tools import current_branch, stage_all, commit, create_pr
from tools.telegram import notify_feature_done, notify_escalation
from config import MODEL_PM

logger = logging.getLogger(__name__)


def a1_pr_final(state: FabricaState) -> dict:
    cost_table  = format_cost_report(state.get("cost_entries", []))
    total_cost  = sum(e.get("cost_usd", 0) for e in state.get("cost_entries", []))
    repo_name   = state["repo_name"]
    repo_path   = state["repo_path"]

    # Resumen del ciclo SecOps
    secops_note = ""
    if state.get("secops_iterations", 0) > 0:
        secops_note = (
            f"\nSecOps aplicó correcciones de seguridad "
            f"({state['secops_iterations']} iteración/es de revisión)."
        )

    task = f"""
Eres el Agente 1 — PM (Project Manager). Eres el ÚLTIMO agente del ciclo.
Tu rol es cerrar el feature con calidad: revisar cumplimiento, documentar y crear el PR.

## MASTER_PLAN (objetivo original del feature)
---
{state['master_plan']}
---

## CÓDIGO FINAL (post-refactor y post-secops)

BACKEND:
---
{state.get('backend_code', 'No disponible')}
---

FRONTEND:
---
{state.get('frontend_code', 'No disponible')}
---

## REPORTE QA FINAL
---
{state.get('qa_report', 'No disponible')}
---

## REPORTE DE COSTOS
{cost_table}
{secops_note}

---

## TU TAREA EN CUATRO PARTES OBLIGATORIAS

### PARTE 1 — REVISIÓN DE CUMPLIMIENTO

Compara el código entregado con los objetivos del MASTER_PLAN.
Para cada objetivo/criterio de aceptación, marca:
  ✅ Cumplido | ⚠️ Parcial | ❌ No cumplido

Sé honesto. Si algo no se implementó, dilo.
Finaliza con: `CUMPLIMIENTO: COMPLETO | PARCIAL | INCOMPLETO`

### PARTE 2 — DOCUMENTACIÓN

Genera la documentación del código:
- Docstrings en funciones/clases donde el WHY no sea obvio (una línea, no el QUÉ)
- `@extend_schema` para cada endpoint nuevo o modificado (si aplica)
- Entrada en CHANGELOG.md bajo `[Unreleased]`:
  ```
  ### Added / Changed / Fixed
  - [descripción del cambio para el usuario final]
  ```
- Si el feature cambia el estado de algún módulo en PROJECT_CONTEXT.md, indica qué actualizar

### PARTE 3 — MENSAJE DEL PR

Genera el mensaje completo del Pull Request:

**Título:** `feat([modulo]): [descripción en una línea]`

**Cuerpo:**
- Descripción del feature (lenguaje de negocio, no técnico)
- Tabla de revisión de cumplimiento (del Paso 1)
- Archivos modificados (inferidos del código)
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

    # ── Commit + PR automático ────────────────────────────────────────────────
    pr_url   = ""
    branch   = current_branch(repo_path)

    # Extraer título del PR del output
    title_line = next(
        (l.lstrip("# ").strip() for l in pr_message.splitlines()
         if l.strip().startswith("feat(")),
        f"feat: {state['feature_name']}",
    )

    # Extraer mensaje de commit si el PM lo generó
    commit_msg_match = None
    import re
    commit_block = re.search(
        r"```\s*\n(feat\([^)]+\):.*?)```",
        pr_message, re.DOTALL,
    )
    commit_text = (
        commit_block.group(1).strip()
        if commit_block
        else f"{title_line}\n\n🤖 Fábrica de Software — repo: {repo_name}"
    )

    try:
        if stage_all(repo_path) and commit(commit_text, repo_path):
            pr_url = create_pr(title_line, pr_message, repo_path)
            if pr_url.startswith("ERROR"):
                logger.warning("PR no creado automáticamente: %s", pr_url)
                pr_url = ""
    except Exception as exc:
        logger.exception("Error al crear commit/PR: %s", exc)

    # ── Notificación Telegram ─────────────────────────────────────────────────
    notify_feature_done(
        feature_name=state["feature_name"],
        project_name=state.get("project_id"),   # None si es feature standalone
        cost_usd=total_cost + cost.get("cost_usd", 0),
        pr_url=pr_url,
    )

    return {
        "pr_message":    pr_message,
        "current_agent": "a1_pr_final",
        "cost_entries":  [cost],
        "errors":        [] if pr_url else ["PR no creado automáticamente — revisa el repo"],
    }
