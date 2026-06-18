"""Tests del Pipeline Builder (PLAN_PLATAFORMA_V2 Fase 6). LLM mockeado; base_dir en tmp_path."""
import json
from pathlib import Path

import pytest
import yaml

import tools.pipeline_builder as pb


# ── normalización / validación ────────────────────────────────────────────────

def test_normalize_fills_defaults():
    d = pb.normalize_pipeline_definition({"name": "legal", "entry": "L1", "agents": ["L1"]})
    assert d["state_schema"] == "PipelineState"
    assert d["gates"] == []
    assert d["output"] == {"type": "noop"}
    assert d["default_model"] is None


def test_validate_ok():
    d = pb.normalize_pipeline_definition({"name": "legal", "entry": "L1", "agents": ["L1", "L2"]})
    assert pb.validate_pipeline_definition(d) == []


def test_validate_missing_required():
    errs = pb.validate_pipeline_definition({"name": "legal"})
    assert any("entry" in e for e in errs)
    assert any("agents" in e for e in errs)


def test_validate_entry_not_in_agents():
    d = pb.normalize_pipeline_definition({"name": "legal", "entry": "X", "agents": ["L1"]})
    assert any("no está en la lista de agents" in e for e in pb.validate_pipeline_definition(d))


def test_validate_duplicate_name():
    d = pb.normalize_pipeline_definition({"name": "software", "entry": "A1", "agents": ["A1"]})
    errs = pb.validate_pipeline_definition(d, existing_names={"software"})
    assert any("ya existe" in e for e in errs)


def test_validate_bad_name_chars():
    d = pb.normalize_pipeline_definition({"name": "mal nombre!", "entry": "A1", "agents": ["A1"]})
    assert any("caracteres inválidos" in e for e in pb.validate_pipeline_definition(d))


def test_validate_agents_must_be_str_list():
    d = pb.normalize_pipeline_definition({"name": "legal", "entry": "L1", "agents": [1, 2]})
    assert any("lista de ids" in e for e in pb.validate_pipeline_definition(d))


# ── build (LLM inyectado) ──────────────────────────────────────────────────────

def test_build_with_dict_llm():
    fake = {"name": "legal", "entry": "L1", "agents": ["L1", "L2"], "description": "Pipeline legal"}
    d = pb.build_pipeline_definition("crea un pipeline legal", llm=lambda _r: fake)
    assert d["name"] == "legal"
    assert d["output"] == {"type": "noop"}   # default normalizado


def test_build_with_json_string():
    payload = json.dumps({"name": "ventas", "entry": "V1", "agents": ["V1"]})
    d = pb.build_pipeline_definition("pipeline de ventas", llm=lambda _r: payload)
    assert d["name"] == "ventas"


def test_build_invalid_json_raises():
    with pytest.raises(ValueError, match="JSON válido"):
        pb.build_pipeline_definition("x", llm=lambda _r: "no json")


# ── registro (doble gate + escritura) ──────────────────────────────────────────

@pytest.fixture
def base_dir(tmp_path):
    # pipeline existente para probar colisión de nombres
    (tmp_path / "software").mkdir()
    (tmp_path / "software" / "pipeline.yaml").write_text("name: software\nagents: [A1]\n")
    return tmp_path


def _enable(monkeypatch):
    monkeypatch.setattr("config.PIPELINE_BUILDER_ENABLED", True, raising=False)


def test_register_blocked_when_flag_off(base_dir, monkeypatch):
    monkeypatch.setattr("config.PIPELINE_BUILDER_ENABLED", False, raising=False)
    d = pb.normalize_pipeline_definition({"name": "legal", "entry": "L1", "agents": ["L1"]})
    with pytest.raises(PermissionError, match="PIPELINE_BUILDER_ENABLED"):
        pb.register_pipeline(d, approved=True, base_dir=base_dir)


def test_register_requires_approval(base_dir, monkeypatch):
    _enable(monkeypatch)
    d = pb.normalize_pipeline_definition({"name": "legal", "entry": "L1", "agents": ["L1"]})
    with pytest.raises(PermissionError, match="aprobación"):
        pb.register_pipeline(d, approved=False, base_dir=base_dir)


def test_register_rejects_duplicate(base_dir, monkeypatch):
    _enable(monkeypatch)
    d = pb.normalize_pipeline_definition({"name": "software", "entry": "A1", "agents": ["A1"]})
    with pytest.raises(ValueError, match="ya existe"):
        pb.register_pipeline(d, approved=True, base_dir=base_dir)


def test_register_writes_yaml(base_dir, monkeypatch):
    _enable(monkeypatch)
    d = pb.normalize_pipeline_definition(
        {"name": "legal", "entry": "L1", "agents": ["L1", "L2"], "description": "Legal"})
    path = pb.register_pipeline(d, approved=True, base_dir=base_dir)
    assert path == base_dir / "legal" / "pipeline.yaml"
    written = yaml.safe_load(Path(path).read_text())
    assert written["name"] == "legal"
    assert written["agents"] == ["L1", "L2"]
    assert written["entry"] == "L1"
