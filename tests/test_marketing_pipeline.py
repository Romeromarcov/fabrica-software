"""Tests del dominio `marketing` (PLAN_PIPELINE_MARKETING / V2 Fase 4, 2º dominio de referencia).

Verifica la definición data-driven (pipeline.yaml + registry + MarketingState). La EJECUCIÓN
del grafo (LLM por agente) es del runtime y queda fuera de alcance offline.
"""
import tools.agent_registry as ar
import graph_builder as gb
from tools.pipeline_loader import discover_pipelines, load_pipeline, pipeline_summaries


def test_marketing_discovered():
    assert "marketing" in discover_pipelines()


def test_marketing_yaml_valid():
    mk = load_pipeline("marketing")
    assert mk["name"] == "marketing"
    assert mk["entry"] == "M0"
    assert mk["state_schema"] == "MarketingState"
    assert mk["agents"] == ["M0", "M1", "M2", "M3", "M4", "M5", "M6", "M6_5", "M7", "M8"]


def test_marketing_modes_and_gates():
    mk = load_pipeline("marketing")
    assert set(mk["modes"]) == {"campaña", "post", "lightning"}
    assert "brand_check" in mk["gates"] and "compliance_check" in mk["gates"]
    assert mk["modes"]["lightning"]["agents"] == ["M1", "M4", "M8"]


def test_marketing_trigger_from_software():
    mk = load_pipeline("marketing")
    trig = mk["triggers"][0]
    # Quirk YAML 1.1: la clave `on:` se interpreta como booleano True (lo normaliza el
    # pipeline_orchestrator). Aceptamos ambas formas.
    event = trig.get("on") or trig.get(True)
    assert event == "software.feature_merged"
    assert trig["mode"] == "post"


def test_all_marketing_agents_in_registry():
    ar.clear_cache()
    ids = {a["id"] for a in ar.all_agents("marketing")}
    assert {"M0", "M1", "M2", "M3", "M4", "M5", "M6", "M6_5", "M7", "M8"} <= ids


def test_spec_resolves_all_agents():
    spec = gb.build_pipeline_spec("marketing")
    assert len(spec["agents"]) == 10
    # cada agente con LLM resuelve a un modelo no vacío vía cascada
    for a in spec["agents"]:
        assert a["model"]


def test_preview_and_publisher_are_no_llm():
    # M7 (Preview) y M8 (Publisher) son deterministas, como A9/A10 en software.
    assert ar.resolve_model("M7") == "no-llm"
    assert ar.resolve_model("M8") == "no-llm"


def test_marketing_agents_have_no_production_node():
    # Producción es el pipeline `software`; los agentes marketing no tienen nodo en graph.py.
    for a in ar.all_agents("marketing"):
        assert a.get("node_name") is None


def test_marketing_in_pipeline_summaries():
    names = {s["name"] for s in pipeline_summaries()}
    assert "marketing" in names and "software" in names


def test_marketing_state_importable():
    from state import MarketingState
    ann = MarketingState.__annotations__
    assert "needs_human_asset" in ann      # D1
    assert "compliance_clear" in ann        # M6
    assert "published" in ann               # M8


def test_software_pipeline_still_intact():
    # Añadir marketing no rompe el dominio de producción.
    assert len(gb.build_pipeline_spec("software")["agents"]) == 12
