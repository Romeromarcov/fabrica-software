"""Tests de la estimación de dry run (PLAN_PLATAFORMA_V2 M10, Fase 3)."""
import pytest

from tools import dry_run
from tools import quality_tracker as qt


@pytest.fixture
def runs_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(qt, "_RUNS_DIR", tmp_path)
    return tmp_path


def test_estimate_no_history_uses_tier_heuristic(runs_dir):
    est = dry_run.estimate("", "Implementar reportes PDF de ventas")
    assert est["based_on_history"] is False
    assert est["risk_tier"] in ("LOW", "MEDIUM", "HIGH")
    assert est["expected_qa_iters"] > 0
    assert est["expected_minutes"] > 0


def test_high_risk_text_raises_tier():
    est = dry_run.estimate("", "Modificar apps/core auth JWT y migrations de settings")
    assert est["risk_tier"] == "HIGH"
    assert any("HIGH" in n for n in est["notes"])


def test_path_hint_raises_tier():
    est = dry_run.estimate("", "cambio menor", files_hint=["apps/core/models.py"])
    assert est["risk_tier"] == "HIGH"


def test_estimate_uses_history_when_available(runs_dir):
    # Sembrar >=3 features con muchas iteraciones → proyección desde historial.
    for i in range(4):
        qt.record_feature_metrics(
            project_id="proj", feature_id=f"f{i}", feature_name=f"f{i}",
            qa_iterations=3, secops_iterations=0, sandbox_passes=1, bug_categories=[],
        )
    est = dry_run.estimate("proj", "feature normal de CRUD")
    assert est["based_on_history"] is True
    assert est["history_features"] == 4
    assert any("features previos" in n for n in est["notes"])


def test_low_score_history_adds_iteration(runs_dir):
    # Features con score bajo (rollback + sandbox fail + muchas iters).
    for i in range(4):
        qt.record_feature_metrics(
            project_id="bad", feature_id=f"b{i}", feature_name=f"b{i}",
            qa_iterations=4, secops_iterations=2, sandbox_passes=0,
            bug_categories=["x"], had_rollback=True,
        )
    est = dry_run.estimate("bad", "feature CRUD")
    assert any("score < 70" in n for n in est["notes"])


def test_format_estimate_renders_table(runs_dir):
    out = dry_run.format_estimate("", "Crear endpoint de inventario")
    assert "Dry run" in out
    assert "Tier de riesgo" in out
    assert "Iteraciones QA" in out
