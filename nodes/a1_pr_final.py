"""Agente 1 — Fase B cierre: genera el mensaje del PR Final con reporte de costos."""
from state import FabricaState
from nodes.base import call_agent
from tools.file_tools import save_agent_output, save_run_metadata
from tools.cost_tracker import format_cost_report
from tools.git_tools import current_branch, stage_all, commit, create_pr
from config import MODEL_PM
from datetime import datetime
import logging

logger = logging.getLogger(__name__)


def a1_pr_final(state: FabricaState) -> dict:
    cost_table = format_cost_report(state.get("cost_entries", []))

    task = f"""
Eres el Agente 1 en FASE B (cierre) — generando el PR Final.

MASTER_PLAN del feature:
---
{state['master_plan']}
---

REPORTE AGENTE 5 (Refactor + Doc):
---
{state.get('refactor_doc_output', '')}
---

{cost_table}

Tu tarea: genera el mensaje completo del Pull Request.

El PR debe incluir:
1. Título: `feat([modulo]): [descripción en una línea]`
2. Descripción: resumen del feature para el Founder (lenguaje de negocio, no técnico)
3. Lista de archivos modificados (extraída del output del Agente 5)
4. Tests: cantidad de tests, módulos cubiertos, % cobertura estimado
5. Seguridad: confirmación de Security Clearance del Agente 7
6. La tabla de costos (ya incluida arriba)
7. Próximos pasos sugeridos (deuda técnica si la hay)

El PR es la entrega final al Founder. Sé claro y conciso.
"""
    repo_path = state["repo_path"]
    repo_name = state["repo_name"]

    pr_message, cost = call_agent(
        agent_key="a1_pm",
        agent_label="Agente 1 PM (PR Final)",
        task_content=task,
        model=MODEL_PM,
        include_static=[],  # No necesita docs estáticos en el cierre
        repo_path=repo_path,
    )

    save_agent_output(state["feature_id"], "a1_pr_final", pr_message)
    save_run_metadata(state["feature_id"], {
        "completed_at": datetime.utcnow().isoformat(),
        "total_cost_usd": sum(e["cost_usd"] for e in state.get("cost_entries", [])),
    })

    # Intentar crear el PR automáticamente vía gh
    pr_url = ""
    branch = current_branch(repo_path)
    title_line = next(
        (l for l in pr_message.splitlines() if l.startswith("feat(")),
        f"feat: {state['feature_name']}"
    )
    if stage_all(repo_path) and commit(
        f"{title_line}\n\nGenerado por Fábrica de Software — repo: {repo_name}",
        repo_path,
    ):
        pr_url = create_pr(title_line, pr_message, repo_path)
        if pr_url.startswith("ERROR"):
            logger.warning("PR no creado automáticamente: %s", pr_url)
            pr_url = ""

    return {
        "pr_message": pr_message,
        "current_agent": "a1_pr_final",
        "cost_entries": [cost],
        "errors": [] if pr_url or True else [f"PR no creado: {pr_url}"],
    }
