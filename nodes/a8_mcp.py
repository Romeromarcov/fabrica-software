"""Agente 8 — MCP Toolsmith. Diseña e implementa los servidores MCP."""
from state import FabricaState
from nodes.base import call_agent
from tools.file_tools import save_agent_output
from config import MODEL_A8


def a8_mcp(state: FabricaState) -> dict:
    task = f"""
Eres el Agente 8 — MCP Toolsmith.

MASTER_PLAN del feature (presta especial atención a la sección "Herramientas MCP necesarias"):
---
{state['master_plan']}
---

Tu tarea: diseña e implementa las herramientas MCP necesarias para este feature.

Si el MASTER_PLAN indica que no se necesitan herramientas MCP, responde con:
"Sin herramientas MCP requeridas para este feature." y explica brevemente por qué.

Si se necesitan herramientas, entrega:
1. Definición completa de cada herramienta con su inputSchema
2. Implementación de los handlers en Python (servidor erp/)
3. Si hay herramientas de desarrollo, van en servidor dev/ COMPLETAMENTE SEPARADO
4. Checklist de seguridad completado (al final de tu output)

Sigue la estructura de dos servidores separados: backend/mcp_servers/erp/ y backend/mcp_servers/dev/
"""
    output, cost = call_agent(
        agent_key="a8_mcp",
        agent_label="Agente 8 MCP",
        task_content=task,
        model=MODEL_A8,
        include_static=["project_context", "decision_log"],
        repo_path=state["repo_path"],
    )
    save_agent_output(state["feature_id"], "a8_mcp", output)
    return {
        "mcp_tools": output,
        "current_agent": "a8_mcp",
        "cost_entries": [cost],
    }
