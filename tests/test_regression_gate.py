"""
Tests F3.2 — gate de regresión sobre la suite existente del repo.

compute_regressions es puro (aceptación: test que pasaba y ahora falla → bloquea; fallo
preexistente → no bloquea). collect_failures se ejercita sobre un repo temporal real (pytest).
El bloqueo en A9 se prueba con regression_report mockeado.
"""
import subprocess
import textwrap
import pytest

from tools import regression_gate as rg


# ── compute_regressions (puro — la aceptación) ───────────────────────────────

def test_new_failure_blocks():
    """Un test que pasaba (no en baseline) y ahora falla → regresión → bloquea."""
    r = rg.compute_regressions(baseline_failures=set(), current_failures={"t.py::test_a"})
    assert r["ok"] is False
    assert r["new_failures"] == ["t.py::test_a"]


def test_preexisting_failure_does_not_block():
    """Un fallo que ya existía en el baseline NO cuenta como regresión."""
    r = rg.compute_regressions(
        baseline_failures={"t.py::test_viejo"}, current_failures={"t.py::test_viejo"})
    assert r["ok"] is True
    assert r["new_failures"] == []


def test_fixed_test_is_reported_not_blocking():
    r = rg.compute_regressions(baseline_failures={"t.py::test_x"}, current_failures=set())
    assert r["ok"] is True
    assert r["fixed"] == ["t.py::test_x"]


def test_mixed_new_and_preexisting():
    r = rg.compute_regressions(
        baseline_failures={"t.py::old"},
        current_failures={"t.py::old", "t.py::nuevo"})
    assert r["ok"] is False
    assert r["new_failures"] == ["t.py::nuevo"]   # solo el nuevo bloquea


# ── collect_failures (subprocess real sobre tmp repo) ────────────────────────

def test_collect_failures_detects_failing_test(tmp_path):
    (tmp_path / "test_demo.py").write_text(textwrap.dedent("""
        def test_ok():
            assert True
        def test_falla():
            assert 1 == 2
    """), encoding="utf-8")
    r = rg.collect_failures(str(tmp_path))
    assert r["ran"] is True
    assert any("test_falla" in f for f in r["failures"])
    assert not any("test_ok" in f for f in r["failures"])


def test_collect_failures_no_tests_is_not_ran(tmp_path):
    r = rg.collect_failures(str(tmp_path))
    assert r["ran"] is False
    assert r["failures"] == set()


def test_regression_report_no_tests_does_not_block(tmp_path):
    rep = rg.regression_report(str(tmp_path), baseline_failures=[])
    assert rep["ok"] is True and rep["ran"] is False


def test_regression_report_end_to_end(tmp_path):
    """Baseline vacío + un test que falla → regresión detectada sobre repo real."""
    (tmp_path / "test_demo.py").write_text(
        "def test_rompe():\n    assert False\n", encoding="utf-8")
    rep = rg.regression_report(str(tmp_path), baseline_failures=[])
    assert rep["ran"] is True
    assert rep["ok"] is False
    assert any("test_rompe" in f for f in rep["new_failures"])


# ── bloqueo en A9 ────────────────────────────────────────────────────────────

def test_a9_blocks_on_regression(monkeypatch):
    import nodes.a9_sandbox as a9
    monkeypatch.setattr(a9, "run_all_checks",
                        lambda *a, **k: {"passed": True, "summary": "ok", "gate_failures": []})
    monkeypatch.setattr("tools.file_tools.save_agent_output", lambda *a, **k: None)
    monkeypatch.setattr("config.REGRESSION_GATE_ENABLED", True, raising=False)
    monkeypatch.setattr("tools.regression_gate.regression_report",
                        lambda repo, base, **k: {"ok": False, "ran": True,
                                                 "new_failures": ["t.py::test_roto"], "fixed": []})

    state = {"repo_path": "/r", "feature_id": "F1",
             "test_baseline_failures": [], "sandbox_iterations": 0, "files_written": []}
    out = a9.a9_sandbox(state)
    assert out["sandbox_passed"] is False
    assert any("REGRESIÓN" in e for e in out["errors"])
    assert any(gf["gate"] == "regression" for gf in out["sandbox_gate_failures"])


def test_a9_does_not_block_when_gate_disabled(monkeypatch):
    import nodes.a9_sandbox as a9
    monkeypatch.setattr(a9, "run_all_checks",
                        lambda *a, **k: {"passed": True, "summary": "ok", "gate_failures": []})
    monkeypatch.setattr("tools.file_tools.save_agent_output", lambda *a, **k: None)
    monkeypatch.setattr("config.REGRESSION_GATE_ENABLED", False, raising=False)

    state = {"repo_path": "/r", "feature_id": "F1",
             "test_baseline_failures": [], "sandbox_iterations": 0, "files_written": []}
    out = a9.a9_sandbox(state)
    assert out["sandbox_passed"] is True
