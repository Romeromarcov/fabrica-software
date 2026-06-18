"""Tests del router NL de la meta-capa (PLAN_PLATAFORMA_V2 Fase 7 🟢). Determinista."""
import tools.factory_router as fr


def test_route_create_agent():
    r = fr.route_request("crea un agente de SEO que optimice metadatos")
    assert r["target"] == fr.AGENT_BUILDER
    assert r["method"] == "rules"


def test_route_create_pipeline():
    r = fr.route_request("crea un pipeline legal para revisar contratos")
    assert r["target"] == fr.PIPELINE_BUILDER


def test_route_modify_prompt_to_factory_modifier():
    r = fr.route_request("modifica el prompt de A4 para que use type hints")
    assert r["target"] == fr.FACTORY_MODIFIER


def test_route_add_step_to_factory_modifier():
    r = fr.route_request("añade un paso de traducción antes de A1")
    assert r["target"] == fr.FACTORY_MODIFIER


def test_pipeline_creation_beats_agent_word():
    # menciona "pipeline" + crear → pipeline_builder aunque diga "agentes"
    r = fr.route_request("crea un nuevo pipeline de marketing con varios agentes")
    assert r["target"] == fr.PIPELINE_BUILDER


def test_unknown_when_no_signal():
    r = fr.route_request("¿qué tal el clima hoy?")
    assert r["target"] == fr.UNKNOWN


def test_llm_fallback_used_when_rules_dont_match():
    r = fr.route_request("haz algo con eso", llm=lambda _t: "agent_builder")
    assert r["target"] == fr.AGENT_BUILDER
    assert r["method"] == "llm"


def test_llm_invalid_label_stays_unknown():
    r = fr.route_request("haz algo con eso", llm=lambda _t: "no-sé")
    assert r["target"] == fr.UNKNOWN


def test_is_executable_gating():
    assert fr.is_executable(fr.AGENT_BUILDER) is True
    assert fr.is_executable(fr.PIPELINE_BUILDER) is True
    # factory_modifier (auto-modificación) NO es ejecutable autónomamente.
    assert fr.is_executable(fr.FACTORY_MODIFIER) is False


def test_modify_agent_existing_not_create():
    # "modifica un agente" → modificar la fábrica, no crear uno nuevo.
    r = fr.route_request("modifica el agente A6 para que sea más estricto")
    assert r["target"] == fr.FACTORY_MODIFIER
