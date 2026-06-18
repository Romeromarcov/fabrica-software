"""Tests de la orquestación entre pipelines (PLAN_PLATAFORMA_V2 Fase 8)."""
import pytest

from tools import pipeline_loader as pl
from tools import pipeline_orchestrator as po


@pytest.fixture
def pipelines(tmp_path, monkeypatch):
    """Crea pipelines temporales: uno con triggers (marketing) y otro sin (software)."""
    base = tmp_path / "pipelines"
    (base / "marketing").mkdir(parents=True)
    (base / "marketing" / "pipeline.yaml").write_text(
        "name: marketing\n"
        "default_model: gemini-3.5-flash\n"
        "agents: [M0]\n"
        "triggers:\n"
        "  - on: \"software.feature_merged\"\n"
        "    map: { feature_name: input.title, changelog: input.body }\n",
        encoding="utf-8",
    )
    (base / "software").mkdir(parents=True)
    (base / "software" / "pipeline.yaml").write_text(
        "name: software\nagents: [A1]\n", encoding="utf-8",
    )
    monkeypatch.setattr(pl, "_pipelines_dir", lambda: base)
    pl.clear_cache()
    yield base
    pl.clear_cache()


def test_map_event_to_input_resolves_input_paths():
    trig = {"map": {"feature_name": "input.title", "changelog": "input.body"}}
    out = po.map_event_to_input(trig, {"title": "Export CSV", "body": "detalles"})
    assert out == {"feature_name": "Export CSV", "changelog": "detalles"}


def test_map_literal_value():
    trig = {"map": {"kind": "announcement"}}
    assert po.map_event_to_input(trig, {})["kind"] == "announcement"


def test_triggers_for_event_matches(pipelines):
    trigs = po.triggers_for_event("software.feature_merged")
    assert len(trigs) == 1
    assert trigs[0]["pipeline"] == "marketing"


def test_triggers_for_event_no_match(pipelines):
    assert po.triggers_for_event("evento.inexistente") == []


def test_on_event_builds_dispatch_plan(pipelines):
    plan = po.on_event("software.feature_merged",
                       {"title": "Nuevo módulo", "body": "changelog aquí"})
    assert len(plan) == 1
    assert plan[0]["pipeline"] == "marketing"
    assert plan[0]["input"] == {"feature_name": "Nuevo módulo", "changelog": "changelog aquí"}
    assert plan[0]["triggered_by"] == "software.feature_merged"


def test_on_event_empty_when_no_trigger(pipelines):
    assert po.on_event("nada.matchea", {}) == []
