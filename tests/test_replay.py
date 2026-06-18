"""Tests del replay/debugging de pipelines (PLAN_PLATAFORMA_V2 M2, Fase 1)."""
import json

import pytest

from tools import replay


@pytest.fixture
def run(tmp_path, monkeypatch):
    """Crea un RUNS_DIR temporal con un feature y algunos checkpoints."""
    monkeypatch.setattr(replay, "_runs_dir", lambda: tmp_path)
    feature = "feat-replay"
    d = tmp_path / feature
    d.mkdir()
    (d / "metadata.json").write_text(json.dumps({"status": "completado"}), encoding="utf-8")
    (d / "MASTER_PLAN.md").write_text("# plan", encoding="utf-8")
    for node in ("a1_planificador", "a4_backend", "a6_refactor"):
        (d / f"output_{node}.md").write_text(f"salida de {node}", encoding="utf-8")
    return feature, tmp_path


def test_canonical_order_starts_with_a1():
    order = replay.canonical_node_order()
    assert order[0] == "a1_planificador"
    assert "a4_backend" in order


def test_list_checkpoints(run):
    feature, _ = run
    cps = replay.list_checkpoints(feature)
    assert cps == ["a1_planificador", "a4_backend", "a6_refactor"]


def test_list_checkpoints_missing_feature(run):
    assert replay.list_checkpoints("no-existe") == []


def test_load_run_state_reconstructs(run):
    feature, _ = run
    state = replay.load_run_state(feature)
    assert state["feature_id"] == feature
    assert state["metadata"]["status"] == "completado"
    assert state["master_plan"] == "# plan"
    assert "a4_backend" in state["outputs"]


def test_load_run_state_missing_raises(run):
    with pytest.raises(FileNotFoundError):
        replay.load_run_state("no-existe")


def test_replay_plan_from_a6(run):
    feature, _ = run
    plan = replay.replay_plan(feature, "a6_refactor")
    assert plan["valid"]
    assert plan["to_rerun"][0] == "a6_refactor"
    # reutiliza los checkpoints previos disponibles (a1, a4)
    assert "a1_planificador" in plan["reused"]
    assert "a4_backend" in plan["reused"]
    # a6 en adelante se re-ejecuta (no se reutiliza)
    assert "a6_refactor" not in plan["reused"]


def test_replay_plan_invalid_node(run):
    feature, _ = run
    plan = replay.replay_plan(feature, "nodo_inexistente")
    assert not plan["valid"]
    assert "error" in plan


def test_format_replay_plan_readable(run):
    feature, _ = run
    text = replay.format_replay_plan(feature, "a4_backend")
    assert "Plan de replay" in text
    assert "a4_backend" in text


def test_format_replay_plan_invalid(run):
    feature, _ = run
    text = replay.format_replay_plan(feature, "xxx")
    assert text.startswith("❌")
