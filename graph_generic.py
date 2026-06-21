"""
graph_generic.py — Runtime GENÉRICO para cualquier pipeline (PLAN_PLATAFORMA_V2, Fase 4 v0).

Hace lanzable cualquier `pipelines/<name>/pipeline.yaml` SIN escribir funciones-nodo por
dominio: reutiliza `graph_builder` (que ya arma el cableado lineal de cualquier pipeline) e
inyecta un `node_resolver` genérico. Cada agente se ejecuta como una llamada LLM construida a
partir de su `role` + `prompt_file` (si existe) + el brief + las salidas de los agentes previos.

Es una v0 honesta: ejecución lineal, sin gates de dominio ni checkpoints (esos requieren
lógica específica, como el runtime dedicado de marketing/software). Sirve para que un pipeline
recién creado en /meta sea ejecutable de inmediato; luego puede especializarse con nodos propios.
"""
from __future__ import annotations

import logging
import operator
from typing import Annotated, Callable, TypedDict

from graph_builder import build_state_graph
from nodes.base import call_agent

logger = logging.getLogger(__name__)


class GenericPipelineState(TypedDict, total=False):
    brief: str
    outputs: Annotated[list[dict], operator.add]   # [{agent, role, output}]
    current_agent: str
    errors: Annotated[list[str], operator.add]
    cost_entries: Annotated[list, operator.add]


def _read_prompt(agent_spec: dict) -> str:
    """Lee el prompt_file del agente si está definido y existe; si no, cadena vacía."""
    pf = agent_spec.get("prompt_file")
    if not pf:
        return ""
    try:
        from config import FABRICA_DIR
        from pathlib import Path
        path = Path(FABRICA_DIR) / pf
        if path.exists():
            return path.read_text(encoding="utf-8")
    except Exception as exc:  # noqa: BLE001
        logger.debug("no se pudo leer prompt_file %s: %s", pf, exc)
    return ""


def _make_generic_node(agent_spec: dict) -> Callable[[dict], dict]:
    agent_id = agent_spec["id"]
    role = agent_spec.get("role") or agent_id
    model = agent_spec.get("model") or ""
    schema = agent_spec.get("output_schema")
    prompt = _read_prompt(agent_spec)

    def _node(state: dict) -> dict:
        prior = "\n\n".join(
            f"### {o['agent']} — {o['role']}\n{o['output']}"
            for o in state.get("outputs", [])
        )
        parts = []
        if prompt:
            parts.append(prompt)
        parts.append(f"Eres el agente '{agent_id}' con el rol: {role}.")
        parts.append(f"Brief de la tarea:\n{state.get('brief', '')}")
        if prior:
            parts.append(f"Salidas de los agentes previos:\n{prior}")
        if schema:
            parts.append(f"Formato de salida esperado (orientativo): {schema}")
        parts.append("Produce tu contribución a esta etapa del pipeline.")
        task = "\n\n".join(parts)

        try:
            output, cost = call_agent(
                agent_key="generic", agent_label=f"{agent_id} ({role})",
                task_content=task, model=model,
            )
            return {
                "outputs": [{"agent": agent_id, "role": role, "output": output or ""}],
                "current_agent": agent_id,
                "cost_entries": [cost] if cost else [],
            }
        except Exception as exc:  # noqa: BLE001
            logger.exception("generic node %s error: %s", agent_id, exc)
            return {
                "outputs": [{"agent": agent_id, "role": role, "output": f"[error: {exc}]"}],
                "current_agent": agent_id,
                "errors": [f"{agent_id}: {exc}"],
            }

    _node.__name__ = f"generic_{agent_id}"
    return _node


def build_generic_graph(pipeline_name: str):
    """StateGraph genérico (sin compilar) para el pipeline indicado."""
    return build_state_graph(
        pipeline_name, node_resolver=_make_generic_node, state_schema=GenericPipelineState,
    )


def compile_generic_graph(pipeline_name: str):
    """Compila el grafo genérico (sin checkpointer; ejecución lineal directa)."""
    return build_generic_graph(pipeline_name).compile()


def run_generic_pipeline(pipeline_name: str, brief: str, *, thread_id: str = "gen") -> dict:
    """Ejecuta el pipeline genérico de punta a punta y devuelve el estado final."""
    app = compile_generic_graph(pipeline_name)
    state = {"brief": brief, "outputs": [], "errors": [], "cost_entries": []}
    return app.invoke(state, {"configurable": {"thread_id": thread_id}})
