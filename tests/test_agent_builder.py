"""Tests del Agent Builder (PLAN_PLATAFORMA_V2 Fase 5).

La parte LLM se mockea (callable inyectable); el registry se redirige a un tmp_path.
"""
import json
from pathlib import Path

import pytest

import tools.agent_builder as ab
import tools.agent_registry as ar


# ── normalización ────────────────────────────────────────────────────────────

def test_normalize_fills_defaults():
    d = ab.normalize_agent_definition({"id": "SEO1", "role": "SEO", "pipeline": "marketing"})
    assert d["uses_llm"] is True
    assert d["model"] is None            # cascada
    assert d["depends_on"] == []
    assert d["hooks"] == []
    assert d["agent_key"] == "seo1"      # derivado del id
    assert d["judge"] == {"enabled": False, "model": None}


def test_normalize_does_not_mutate_shared_defaults():
    a = ab.normalize_agent_definition({"id": "A"})
    a["depends_on"].append("X")
    b = ab.normalize_agent_definition({"id": "B"})
    assert b["depends_on"] == []         # no se filtró el mutate


# ── validación ───────────────────────────────────────────────────────────────

def test_validate_ok():
    d = ab.normalize_agent_definition({"id": "SEO1", "role": "SEO", "pipeline": "marketing"})
    assert ab.validate_agent_definition(d) == []


def test_validate_missing_required():
    errs = ab.validate_agent_definition({"id": "X"})
    assert any("role" in e for e in errs)
    assert any("pipeline" in e for e in errs)


def test_validate_duplicate_id():
    d = ab.normalize_agent_definition({"id": "A4", "role": "x", "pipeline": "software"})
    errs = ab.validate_agent_definition(d, existing_ids={"A4"})
    assert any("ya existe" in e for e in errs)


def test_validate_bad_id_chars():
    d = ab.normalize_agent_definition({"id": "bad id!", "role": "x", "pipeline": "p"})
    errs = ab.validate_agent_definition(d)
    assert any("caracteres inválidos" in e for e in errs)


def test_validate_no_llm_must_not_declare_model():
    d = ab.normalize_agent_definition(
        {"id": "S", "role": "x", "pipeline": "p", "uses_llm": False, "model": "gemini-2.5-flash-lite"})
    assert any("sin LLM" in e for e in ab.validate_agent_definition(d))


def test_validate_list_field_type():
    d = ab.normalize_agent_definition({"id": "S", "role": "x", "pipeline": "p"})
    d["depends_on"] = "no-es-lista"
    assert any("depends_on" in e for e in ab.validate_agent_definition(d))


# ── build (LLM inyectado) ──────────────────────────────────────────────────────

def test_build_with_dict_llm():
    fake = {"id": "SEO1", "role": "SEO Specialist", "pipeline": "marketing", "uses_llm": True}
    d = ab.build_agent_definition("quiero un agente de SEO", llm=lambda _r: fake)
    assert d["id"] == "SEO1"
    assert d["agent_key"] == "seo1"


def test_build_with_json_string_llm():
    payload = json.dumps({"id": "LEGAL1", "role": "Legal", "pipeline": "legal", "uses_llm": True})
    d = ab.build_agent_definition("agente legal", llm=lambda _r: payload)
    assert d["id"] == "LEGAL1"


def test_build_invalid_json_raises():
    with pytest.raises(ValueError, match="JSON válido"):
        ab.build_agent_definition("x", llm=lambda _r: "esto no es json")


def test_build_non_dict_raises():
    with pytest.raises(ValueError, match="dict"):
        ab.build_agent_definition("x", llm=lambda _r: ["lista"])


# ── registro (doble gate) ──────────────────────────────────────────────────────

@pytest.fixture
def tmp_registry(tmp_path, monkeypatch):
    reg = {"version": 1, "agents": [
        {"id": "A1", "role": "PM", "pipeline": "software", "uses_llm": True, "model": None},
    ]}
    p = tmp_path / "registry.json"
    p.write_text(json.dumps(reg), encoding="utf-8")
    monkeypatch.setattr(ar, "_registry_path", lambda: p)
    ar.clear_cache()
    yield p
    ar.clear_cache()


def _enable(monkeypatch):
    monkeypatch.setattr("config.AGENT_BUILDER_ENABLED", True, raising=False)


def test_register_blocked_when_flag_off(tmp_registry, monkeypatch):
    monkeypatch.setattr("config.AGENT_BUILDER_ENABLED", False, raising=False)
    d = ab.normalize_agent_definition({"id": "SEO1", "role": "SEO", "pipeline": "marketing"})
    with pytest.raises(PermissionError, match="AGENT_BUILDER_ENABLED"):
        ab.register_agent(d, approved=True, registry_path=tmp_registry)


def test_register_requires_approval(tmp_registry, monkeypatch):
    _enable(monkeypatch)
    d = ab.normalize_agent_definition({"id": "SEO1", "role": "SEO", "pipeline": "marketing"})
    with pytest.raises(PermissionError, match="aprobación"):
        ab.register_agent(d, approved=False, registry_path=tmp_registry)


def test_register_rejects_invalid(tmp_registry, monkeypatch):
    _enable(monkeypatch)
    d = ab.normalize_agent_definition({"id": "X"})  # falta role/pipeline
    with pytest.raises(ValueError, match="inválida"):
        ab.register_agent(d, approved=True, registry_path=tmp_registry)


def test_register_rejects_duplicate(tmp_registry, monkeypatch):
    _enable(monkeypatch)
    d = ab.normalize_agent_definition({"id": "A1", "role": "x", "pipeline": "software"})
    with pytest.raises(ValueError, match="ya existe"):
        ab.register_agent(d, approved=True, registry_path=tmp_registry)


def test_register_appends_and_resolves_cascade(tmp_registry, monkeypatch):
    _enable(monkeypatch)
    # pipeline sin pipeline.yaml → la cascada cae al GLOBAL_DEFAULT_MODEL (último escalón).
    d = ab.normalize_agent_definition(
        {"id": "SEO1", "role": "SEO", "pipeline": "pipeline_inexistente", "uses_llm": True})
    data = ab.register_agent(d, approved=True, registry_path=tmp_registry)
    assert any(a["id"] == "SEO1" for a in data["agents"])
    # persistido en disco
    on_disk = json.loads(Path(tmp_registry).read_text())
    assert any(a["id"] == "SEO1" for a in on_disk["agents"])
    # cascada: model None + sin pipeline default → GLOBAL_DEFAULT_MODEL
    from config import GLOBAL_DEFAULT_MODEL
    assert ar.resolve_model("SEO1") == GLOBAL_DEFAULT_MODEL
