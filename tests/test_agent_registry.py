"""Tests del Agent Registry (PLAN_PLATAFORMA_V2 Fase 0, C2-base).

Verifica que el registry carga, que cubre A0–A11, que la resolución de modelo en
cascada (agente → pipeline → global) funciona y que es fiel a config.py (la migración
no cambió los modelos por agente).
"""
import config
import pytest

from tools import agent_registry as ar


def test_registry_loads_and_has_agents():
    reg = ar.load_registry()
    assert reg["version"] >= 1
    assert len(reg["agents"]) >= 12


def test_registry_covers_core_agents():
    ids = {a["id"] for a in ar.all_agents()}
    for expected in ["A1", "A2", "A3", "A4", "A5", "A6", "A7", "A8", "A9", "A10", "A11"]:
        assert expected in ids, f"falta {expected} en el registry"


def test_model_is_faithful_to_config():
    # La migración debe preservar el modelo por agente declarado en config.py.
    assert ar.resolve_model("A4") == config.MODEL_A4
    assert ar.resolve_model("A5") == config.MODEL_A5
    assert ar.resolve_model("A1") == config.MODEL_A1
    assert ar.resolve_model("A8") == config.MODEL_A8


def test_no_llm_agents_resolve_to_no_llm():
    assert ar.resolve_model("A9") == "no-llm"   # sandbox
    assert ar.resolve_model("A10") == "no-llm"  # code writer


def test_cascade_falls_back_to_pipeline_then_global(monkeypatch):
    # Agente sin model declarado → toma el default del pipeline.
    fake = {"id": "AX", "pipeline": "software", "uses_llm": True, "model": None,
            "model_fallbacks": []}
    monkeypatch.setattr(ar, "get_agent", lambda _id: fake)
    assert ar.resolve_model("AX", pipeline_default="modelo-pipeline") == "modelo-pipeline"
    # Sin pipeline default → cae al global de config.
    assert ar.resolve_model("AX", pipeline_default=None) in (
        config.GLOBAL_DEFAULT_MODEL,
        # por si el loader del pipeline aporta uno; ambos son válidos
        ar.pipeline_default_model("software"),
    )


def test_agent_model_overrides_pipeline_default():
    # A4 tiene model explícito → la cascada NO lo degrada al default del pipeline.
    assert ar.resolve_model("A4", pipeline_default="otro-modelo") == config.MODEL_A4


def test_get_agent_unknown_raises():
    with pytest.raises(KeyError):
        ar.get_agent("NO_EXISTE")


def test_model_fallbacks_returns_list():
    assert isinstance(ar.model_fallbacks("A4"), list)
