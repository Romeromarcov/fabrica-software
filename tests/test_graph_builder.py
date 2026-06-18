"""Tests del graph_builder data-driven (PLAN_PLATAFORMA_V2 Fase 0, C3-base).

Verifica que la spec se resuelve desde yaml+registry, que el modelo efectivo por
agente respeta la cascada, que el StateGraph se construye/compila, y la PARIDAD con
el grafo de producción (`graph.py`): cada nodo de agente del registry existe como
nodo real en build_graph().
"""
import config

import graph as production_graph
import graph_builder as gb


def test_build_pipeline_spec_software():
    spec = gb.build_pipeline_spec("software")
    assert spec["name"] == "software"
    assert spec["entry"] == "A1"
    ids = [a["id"] for a in spec["agents"]]
    assert ids[0] == "A1"
    assert "A4" in ids and "A11" in ids


def test_spec_resolves_effective_models():
    spec = gb.build_pipeline_spec("software")
    by_id = {a["id"]: a for a in spec["agents"]}
    assert by_id["A4"]["model"] == config.MODEL_A4       # model explícito
    assert by_id["A9"]["model"] == "no-llm"              # sin LLM
    assert by_id["A11"]["model"] == config.MODEL_A11


def test_build_state_graph_compiles():
    g = gb.build_state_graph("software")
    compiled = g.compile()
    assert compiled is not None


def test_build_state_graph_uses_resolver():
    seen = []

    def resolver(agent):
        seen.append(agent["id"])
        return lambda state: state

    gb.build_state_graph("software", node_resolver=resolver)
    assert "A1" in seen and "A4" in seen


def test_parity_registry_nodes_exist_in_production_graph():
    # Cada agente del registry con node_name debe existir como nodo real en graph.py.
    prod_nodes = set(production_graph.build_graph().nodes.keys())
    for agent in gb.build_pipeline_spec("software")["agents"]:
        node = agent["node_name"]
        if node:
            assert node in prod_nodes, (
                f"node_name '{node}' del registry no existe en graph.py "
                f"(la migración data-driven se desincronizó)"
            )
