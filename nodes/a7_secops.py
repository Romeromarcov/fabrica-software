"""Agente 7 — SecOps. Dos funciones: revisión 1 (esquema) y revisión 2 (código)."""
from state import FabricaState
from nodes.base import call_agent
from tools.file_tools import save_agent_output
from config import MODEL_A7


def _parse_clearance(output: str) -> tuple[bool, str | None]:
    """Detecta si el output contiene Security Clearance o Security Block."""
    upper = output.upper()
    if "SECURITY BLOCK" in upper:
        return False, output
    if "SECURITY CLEARANCE" in upper or "APROBADO" in upper:
        return True, None
    # Ambiguo — ser conservador y bloquear
    return False, f"Output ambiguo del Agente 7. Revisar manualmente:\n{output[:500]}"


def a7_revision_1(state: FabricaState) -> dict:
    """Revisión 1: esquema DB y herramientas MCP (antes de construcción)."""
    task = f"""
Eres el Agente 7 — SecOps. Estás en la REVISIÓN 1 (esquema y herramientas, antes de construcción).

OUTPUT DEL AGENTE 6 (DB Architect):
---
{state.get('db_schema', 'No disponible')}
---

OUTPUT DEL AGENTE 8 (MCP Toolsmith):
---
{state.get('mcp_tools', 'No disponible')}
---

Tu tarea: revisa la seguridad del esquema de DB y las herramientas MCP.

Usa tus checklists de:
- Esquema DB (multi-tenant, hashing, PCI-DSS, datos personales)
- Herramientas MCP (validación JWT, rate limiting, separación erp/dev)

Termina con uno de estos dos outputs exactos:
- "## SECURITY CLEARANCE" — si todo está bien (con lista de hallazgos menores si los hay)
- "## SECURITY BLOCK" — si hay vulnerabilidades Alta/Crítica (con tabla de vulnerabilidades)
"""
    output, cost = call_agent(
        agent_key="a7_secops",
        agent_label="Agente 7 SecOps (Rev.1)",
        task_content=task,
        model=MODEL_A7,
        include_static=["decision_log"],
        repo_path=state["repo_path"],
    )
    save_agent_output(state["feature_id"], "a7_rev1", output)
    cleared, block_msg = _parse_clearance(output)
    return {
        "security_clearance_1": cleared,
        "security_block_1": block_msg,
        "current_agent": "a7_revision_1",
        "cost_entries": [cost],
    }


def a7_revision_2(state: FabricaState) -> dict:
    """Revisión 2: código implementado (después de QA)."""
    task = f"""
Eres el Agente 7 — SecOps. Estás en la REVISIÓN 2 (código implementado, después de QA).

BACKEND (Agente 2):
---
{state.get('backend_code', 'No disponible')}
---

FRONTEND (Agente 3):
---
{state.get('frontend_code', 'No disponible')}
---

MCP TOOLS (Agente 8):
---
{state.get('mcp_tools', 'No disponible')}
---

Tu tarea: revisa OWASP Top 10 sobre el código implementado.
Presta especial atención a:
- A01: get_queryset() sin filtro de id_empresa
- A02: secrets en código, conexiones sin TLS
- A03: SQL injection, command injection
- A07: endpoints sin autenticación
- XSS: dangerouslySetInnerHTML en React

Termina con "## SECURITY CLEARANCE" o "## SECURITY BLOCK".
"""
    output, cost = call_agent(
        agent_key="a7_secops",
        agent_label="Agente 7 SecOps (Rev.2)",
        task_content=task,
        model=MODEL_A7,
        include_static=["decision_log"],
        repo_path=state["repo_path"],
    )
    save_agent_output(state["feature_id"], "a7_rev2", output)
    cleared, block_msg = _parse_clearance(output)
    return {
        "security_clearance_2": cleared,
        "security_block_2": block_msg,
        "current_agent": "a7_revision_2",
        "cost_entries": [cost],
    }
