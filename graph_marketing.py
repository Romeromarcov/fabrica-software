"""
graph_marketing.py — Runtime del pipeline `marketing` (PLAN_PIPELINE_MARKETING §4).

Construye y compila el grafo ejecutable del dominio `marketing` reutilizando el builder
data-driven (`graph_builder.build_state_graph`) sobre `pipelines/marketing/pipeline.yaml`
+ `agents/registry.json`, con las funciones-nodo reales de `nodes/marketing.py`.

No reimplementa el cableado: el orden de los agentes (M0→…→M8) y el modelo efectivo por
agente (cascada registry→pipeline default→global) los resuelve el builder. Aquí se inyecta
el `node_resolver` que mapea cada agente a su función y fija su modelo.

`compile_marketing_graph()` aplica un checkpoint humano `interrupt_before` en M8 (publish
gate `never_full_auto` del pipeline.yaml): la pieza nunca se publica sin pasar por el último
gate. Sin side effects al importar.
"""
from __future__ import annotations

import logging
from typing import Callable

from graph_builder import build_state_graph
from nodes.marketing import MARKETING_NODES

logger = logging.getLogger(__name__)

PIPELINE_NAME = "marketing"


def _resolve_node(agent_spec: dict) -> Callable[[dict], dict]:
    """
    Mapea un agent_spec (del builder) a su función-nodo, fijando el modelo efectivo.
    El builder ya resolvió `agent_spec['model']` por cascada.
    """
    agent_id = agent_spec["id"]
    fn = MARKETING_NODES.get(agent_id)
    if fn is None:
        raise ValueError(f"pipeline marketing: agente '{agent_id}' sin función-nodo en nodes/marketing.py")
    model = agent_spec.get("model") or ""

    def _node(state: dict, _fn=fn, _model=model) -> dict:
        return _fn(state, model=_model)

    _node.__name__ = f"marketing_{agent_id}"
    return _node


def build_marketing_graph():
    """Devuelve el StateGraph (sin compilar) del pipeline marketing."""
    from state import MarketingState
    return build_state_graph(PIPELINE_NAME, node_resolver=_resolve_node, state_schema=MarketingState)


def compile_marketing_graph(checkpointer=None, interrupt_publish: bool = True):
    """
    Compila el grafo marketing. Por defecto interrumpe antes de M8 (publish gate humano,
    `never_full_auto`). Si `checkpointer` es None y se pide interrupt, usa MemorySaver
    (langgraph exige un checkpointer para soportar `interrupt_before`).
    """
    graph = build_marketing_graph()
    interrupt_before = ["M8"] if interrupt_publish else []
    if interrupt_before and checkpointer is None:
        from langgraph.checkpoint.memory import MemorySaver
        checkpointer = MemorySaver()
    return graph.compile(checkpointer=checkpointer, interrupt_before=interrupt_before)


def initial_marketing_state(
    *,
    objetivo: str = "",
    marca: str = "",
    canal: str = "instagram",
    pieza_nombre: str = "",
    brief: str = "",
    mode: str = "post",
) -> dict:
    """Estado inicial del pipeline marketing (contrato MarketingState)."""
    return {
        "objetivo": objetivo,
        "marca": marca,
        "canal": canal,
        "pieza_nombre": pieza_nombre,
        "brief": brief,
        "mode": mode,
        "current_agent": "",
        "errors": [],
        "cost_entries": [],
    }
