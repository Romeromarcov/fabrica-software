"""Tests de pipeline_summaries + `fabrica-cli pipelines` (PLAN_PLATAFORMA_V2 Fase 4, slice CLI)."""
import tools.pipeline_loader as pl


def test_summaries_software_present():
    # El pipeline `software` (migración A0–A11) siempre existe en disco.
    sums = pl.pipeline_summaries()
    names = {s["name"] for s in sums}
    assert "software" in names
    sw = next(s for s in sums if s["name"] == "software")
    assert sw["ok"] is True
    assert sw["entry"] == "A1"
    assert len(sw["agents"]) > 0
    assert sw["description"]


def test_summaries_never_raises_on_bad_yaml(tmp_path, monkeypatch):
    base = tmp_path / "pipelines"
    (base / "broken").mkdir(parents=True)
    (base / "broken" / "pipeline.yaml").write_text("name: broken\n", encoding="utf-8")  # sin agents
    monkeypatch.setattr(pl, "_pipelines_dir", lambda: base)
    pl.clear_cache()
    sums = pl.pipeline_summaries()
    broken = next(s for s in sums if s["name"] == "broken")
    assert broken["ok"] is False
    assert broken["error"]
    pl.clear_cache()


def test_summaries_empty_when_no_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(pl, "_pipelines_dir", lambda: tmp_path / "nope")
    assert pl.pipeline_summaries() == []


def test_cli_pipelines_command_runs(capsys):
    import cli
    cli.cmd_pipelines()
    out = capsys.readouterr().out
    assert "Pipelines disponibles" in out
    assert "software" in out
