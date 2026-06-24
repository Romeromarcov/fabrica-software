"""Tests del Sistema de Aprendizaje Nivel 2 — `tools/quality_tracker.py`.

Cubre ROADMAP_AUTONOMIA I-2: registro de métricas por feature, cálculo de
tendencia y propuesta de actualización de estándares ante patrones recurrentes.
Cada test usa un `RUNS_DIR` temporal — sin side effects sobre el repo.
"""
import json

import pytest

from tools import quality_tracker as qt


@pytest.fixture
def runs_dir(tmp_path, monkeypatch):
    """Apunta el almacenamiento de métricas a un directorio temporal."""
    monkeypatch.setattr(qt, "_RUNS_DIR", tmp_path)
    return tmp_path


def _record(project, feature, **kw):
    defaults = dict(
        project_id=project,
        feature_id=feature,
        feature_name=feature,
        qa_iterations=1,
        secops_iterations=0,
        sandbox_passes=1,
        bug_categories=[],
    )
    defaults.update(kw)
    qt.record_feature_metrics(**defaults)


def test_record_appends_one_line_per_feature(runs_dir):
    _record("proj", "feat-a")
    _record("proj", "feat-b", qa_iterations=3)

    path = runs_dir / "proj" / "quality_metrics.jsonl"
    assert path.exists()
    lines = [ln for ln in path.read_text().splitlines() if ln.strip()]
    assert len(lines) == 2
    rec = json.loads(lines[1])
    assert rec["feature_id"] == "feat-b"
    assert rec["qa_iterations"] == 3


def test_quality_score_penalizes_iterations_and_rollback(runs_dir):
    # Feature perfecto: 1 QA iter, 0 secops, pasa sandbox, sin rollback → 100
    _record("proj", "perfecto")
    # Feature malo: 3 QA iters, 2 secops, no pasa sandbox, rollback
    _record("proj", "malo", qa_iterations=3, secops_iterations=2,
            sandbox_passes=0, had_rollback=True)

    path = runs_dir / "proj" / "quality_metrics.jsonl"
    recs = [json.loads(ln) for ln in path.read_text().splitlines() if ln.strip()]
    assert recs[0]["quality_score"] == 100
    # 100 - (2*15) - (2*10) - 20 - 30 = 0
    assert recs[1]["quality_score"] == 0


def test_record_without_project_id_is_noop(runs_dir):
    _record("", "feat-x")
    # No debe crear ningún archivo de métricas
    assert not any(runs_dir.rglob("quality_metrics.jsonl"))


def test_compute_trend_empty_when_no_data(runs_dir):
    trend = qt.compute_trend("vacio")
    assert trend["total_features"] == 0
    assert trend["direction"] == "sin datos"


def test_compute_trend_detects_improvement(runs_dir):
    # Primera mitad mala, segunda mitad buena → "mejorando"
    for i in range(3):
        _record("proj", f"old-{i}", qa_iterations=4, sandbox_passes=0)
    for i in range(3):
        _record("proj", f"new-{i}", qa_iterations=1, sandbox_passes=1)

    trend = qt.compute_trend("proj")
    assert trend["total_features"] == 6
    assert trend["direction"] == "mejorando"


def test_recurring_pattern_triggers_standards_proposal(runs_dir):
    for i in range(3):
        _record("proj", f"f-{i}", bug_categories=["missing-fk"])

    trend = qt.compute_trend("proj")
    assert "missing-fk" in trend["recurring_patterns"]

    proposal = qt.propose_standards_update("proj")
    assert proposal is not None
    assert "missing-fk" in proposal
    assert "CODING_STANDARDS.md" in proposal


def test_no_proposal_without_recurrence(runs_dir):
    _record("proj", "f-0", bug_categories=["missing-fk"])
    _record("proj", "f-1", bug_categories=["no-logger"])
    assert qt.propose_standards_update("proj") is None


def test_format_quality_summary_renders_feature_row(runs_dir):
    _record("proj", "feat-a", qa_iterations=2)
    summary = qt.format_quality_summary("proj", "feat-a")
    assert "Post-mortem de Calidad" in summary
    assert "Quality Score" in summary
