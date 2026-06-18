"""Tests del cargador de pipelines (PLAN_PLATAFORMA_V2 Fase 0/4)."""
import pytest

from tools import pipeline_loader as pl


def test_discover_finds_software():
    assert "software" in pl.discover_pipelines()


def test_load_software_pipeline():
    p = pl.load_pipeline("software")
    assert p["name"] == "software"
    assert p["entry"] == "A1"
    assert "A4" in p["agents"]
    assert p["default_model"]


def test_load_unknown_pipeline_raises():
    with pytest.raises(FileNotFoundError):
        pl.load_pipeline("no_existe_jamas")


def test_pipeline_without_agents_raises(tmp_path, monkeypatch):
    base = tmp_path / "pipelines"
    (base / "vacio").mkdir(parents=True)
    (base / "vacio" / "pipeline.yaml").write_text("name: vacio\n", encoding="utf-8")
    monkeypatch.setattr(pl, "_pipelines_dir", lambda: base)
    pl.clear_cache()
    with pytest.raises(ValueError):
        pl.load_pipeline("vacio")
    pl.clear_cache()
