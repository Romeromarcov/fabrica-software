"""Tests del meta-agente de auto-mejora M9 (PLAN_PLATAFORMA_V2 Fase 9). Motor determinista."""
import tools.self_improvement as si


def test_no_data_no_proposals():
    assert si.propose_improvements({"quality": {}, "evals": {}, "recurring_errors": []}) == []


def test_high_qa_iters_triggers_alta():
    sig = {"quality": {"total_features": 5, "avg_qa_iters": 4.0, "avg_score": 90,
                       "direction": "estable", "zero_qa_pct": 80}}
    props = si.propose_improvements(sig)
    qa = [p for p in props if p["area"] == "qa_loop"]
    assert qa and qa[0]["severity"] == "alta"


def test_low_score_and_regression():
    sig = {"quality": {"total_features": 6, "avg_qa_iters": 1.0, "avg_score": 60,
                       "direction": "empeorando", "zero_qa_pct": 90}}
    areas = {p["area"] for p in si.propose_improvements(sig)}
    assert "quality_score" in areas
    assert "regression" in areas


def test_low_first_pass_is_media():
    sig = {"quality": {"total_features": 4, "avg_qa_iters": 1.0, "avg_score": 90,
                       "direction": "estable", "zero_qa_pct": 30}}
    fp = [p for p in si.propose_improvements(sig) if p["area"] == "first_pass"]
    assert fp and fp[0]["severity"] == "media"


def test_recurring_patterns_become_proposals():
    sig = {"quality": {"total_features": 5, "avg_qa_iters": 1.0, "avg_score": 95,
                       "direction": "estable", "zero_qa_pct": 100,
                       "recurring_patterns": ["tenant", "n+1"]}}
    areas = {p["area"] for p in si.propose_improvements(sig)}
    assert "recurring:tenant" in areas and "recurring:n+1" in areas


def test_evals_regression_triggers():
    sig = {"evals": {"runs": 5, "direction": "empeorando", "latest": 0.6, "previous": 0.9}}
    props = si.propose_improvements(sig)
    assert any(p["area"] == "evals" and p["severity"] == "alta" for p in props)


def test_recurring_errors_list_become_proposals():
    sig = {"recurring_errors": ["fuga de tenant no detectada"]}
    props = si.propose_improvements(sig)
    assert any(p["area"] == "missed_by_pipeline" for p in props)


def test_proposals_sorted_by_severity():
    sig = {"quality": {"total_features": 5, "avg_qa_iters": 4.0, "avg_score": 60,
                       "direction": "estable", "zero_qa_pct": 30}}
    sev = [p["severity"] for p in si.propose_improvements(sig)]
    order = {"alta": 0, "media": 1, "baja": 2}
    assert sev == sorted(sev, key=lambda s: order[s])


def test_format_report_runs():
    sig = {"quality": {"total_features": 3, "avg_qa_iters": 4.0, "avg_score": 60,
                       "direction": "empeorando", "zero_qa_pct": 20},
           "evals": {"runs": 2, "avg": 0.7, "direction": "estable"}}
    rep = si.format_improvement_report(sig)
    assert "Auto-mejora (M9)" in rep
    assert "ALTA" in rep


def test_format_report_empty():
    rep = si.format_improvement_report({"quality": {}, "evals": {}})
    assert "sin acciones" in rep


def test_gather_signals_safe_without_data(monkeypatch):
    # Sin project_id ni repo_path → estructura segura, sin crash.
    sig = si.gather_signals()
    assert set(sig) == {"quality", "evals", "recurring_errors"}
    assert sig["quality"] == {}
