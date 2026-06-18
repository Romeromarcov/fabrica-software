"""
graph_builder.py — Construcción data-driven de pipelines (PLAN_PLATAFORMA_V2 Fase 0, C3-base).

Arma la descripción de un pipeline (y un StateGraph de LangGraph) **en runtime** a
partir de `agents/registry.json` + `pipelines/<nombre>/pipeline.yaml`, en vez de
tenerlo hardcodeado.

Estado de la migración (honesto): `graph.py` sigue siendo el **path de producción**
del pipeline `software` con todo su routing condicional (modos completo/lite/lightning,
checkpoints humanos, escalaciones). Este builder:
  1. Resuelve la **spec data-driven** del pipeline (agentes ordenados + modelo efectivo
     por agente vía cascada + prompt + schema + gates + checkpoints). Consumible por
     UI/tooling y por el runtime multi-pipeline (Fase 4).
  2. Construye un **StateGraph lineal validable** sobre esa spec (prueba el mecanismo;
     acepta un `node_resolver` para inyectar las funciones-nodo reales).

La migración del routing condicional de `graph.py` a este builder es el incremento
siguiente; este módulo es su cimiento, no su reemplazo.
"""
from __future__ import annotations

import logging
from typing import Callable, Optional

from tools.agent_registry import all_agents, get_agent, resolve_model
from tools.pipeline_loader import load_pipeline

logger = logging.getLogger(__name__)


def build_pipeline_spec(name: str) -> dict:
    """
    Resuelve la spec completa de un pipeline desde yaml + registry.

    Devuelve un dict con:
      name, default_model, entry, gates, human_checkpoints, output,
      agents: [ {id, role, node_name, uses_llm, model (efectivo), prompt_file,
                 output_schema, depends_on, activation_flags, hooks} ]
    """
    pipeline = load_pipeline(name)
    default_model = pipeline.get("default_model")

    agents_spec: list[dict] = []
    for agent_id in pipeline["agents"]:
        agent = get_agent(agent_id)
        if agent.get("pipeline") != name:
            raise ValueError(
                f"Agente '{agent_id}' pertenece a pipeline "
                f"'{agent.get('pipeline')}', no a '{name}'"
            )
        agents_spec.append({
            "id":               agent_id,
            "role":             agent.get("role"),
            "node_name":        agent.get("node_name"),
            "uses_llm":         agent.get("uses_llm", True),
            "model":            resolve_model(agent_id, pipeline_default=default_model),
            "prompt_file":      agent.get("prompt_file"),
            "output_schema":    agent.get("output_schema"),
            "depends_on":       agent.get("depends_on", []),
            "activation_flags": agent.get("activation_flags", []),
            "hooks":            agent.get("hooks", []),
        })

    return {
        "name":              pipeline.get("name", name),
        "description":       pipeline.get("description", ""),
        "default_model":     default_model,
        "entry":             pipeline.get("entry"),
        "gates":             pipeline.get("gates", []),
        "human_checkpoints": pipeline.get("human_checkpoints", []),
        "output":            pipeline.get("output", {}),
        "agents":            agents_spec,
    }


def registry_agent_ids(pipeline: str) -> set[str]:
    """Ids de agentes del registry para un pipeline (para parity tests vs graph.py)."""
    return {a["id"] for a in all_agents(pipeline)}


def _passthrough(name: str) -> Callable[[dict], dict]:
    """Nodo no-op para construir/validar el grafo sin importar los nodos reales."""
    def _node(state: dict) -> dict:
        return state
    _node.__name__ = f"passthrough_{name}"
    return _node


def build_state_graph(
    name: str,
    node_resolver: Optional[Callable[[dict], Callable]] = None,
):
    """
    Construye un StateGraph LINEAL desde la spec del pipeline.

    Args:
        name: nombre del pipeline.
        node_resolver: función `agent_spec -> callable(state)->state`. Si es None,
            usa nodos passthrough (permite validar el cableado sin side effects).

    Devuelve el `StateGraph` SIN compilar (el caller decide checkpointer/compile).
    """
    from langgraph.graph import StateGraph, END

    spec = build_pipeline_spec(name)
    g = StateGraph(dict)

    ordered = spec["agents"]
    if not ordered:
        raise ValueError(f"pipeline '{name}' no tiene agentes")

    for agent in ordered:
        node_id = agent["id"]
        fn = node_resolver(agent) if node_resolver else _passthrough(node_id)
        g.add_node(node_id, fn)

    g.set_entry_point(ordered[0]["id"])
    for prev, nxt in zip(ordered, ordered[1:]):
        g.add_edge(prev["id"], nxt["id"])
    g.add_edge(ordered[-1]["id"], END)

    logger.info("graph_builder: pipeline '%s' armado con %d nodos", name, len(ordered))
    return g
