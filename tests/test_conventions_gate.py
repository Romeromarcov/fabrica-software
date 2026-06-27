"""
Tests F3.2 — gate de convenciones del repo.

detect_conventions sobre un repo temporal real; check_code (puro) verifica las violaciones de
alta confianza; el bloqueo blando en A9 se prueba con conventions_report mockeado. Diseño
conservador: sin convenciones detectadas o código conforme → no bloquea.
"""
from tools import conventions_gate as cg


# ── detect_conventions ───────────────────────────────────────────────────────

def test_detect_module_logger_and_fk_prefix(tmp_path):
    (tmp_path / "app").mkdir()
    (tmp_path / "app" / "util.py").write_text(
        "import logging\nlogger = logging.getLogger(__name__)\n", encoding="utf-8")
    (tmp_path / "app" / "models.py").write_text(
        "from django.db import models\nid_empresa = models.ForeignKey('E', on_delete=models.CASCADE)\n",
        encoding="utf-8")
    conv = cg.detect_conventions(str(tmp_path))
    assert conv["module_logger"] is True
    assert conv["fk_id_prefix"] is True


def test_detect_none_in_empty_repo(tmp_path):
    conv = cg.detect_conventions(str(tmp_path))
    assert conv == {"module_logger": False, "fk_id_prefix": False}


# ── check_code (puro) ────────────────────────────────────────────────────────

def test_check_flags_bad_logger():
    v = cg.check_code('logging.getLogger("mi.modulo")', {"module_logger": True})
    assert len(v) == 1 and v[0]["rule"] == "module_logger"


def test_check_accepts_name_logger():
    v = cg.check_code("logger = logging.getLogger(__name__)", {"module_logger": True})
    assert v == []


def test_check_flags_fk_without_prefix():
    code = "empresa = models.ForeignKey('E', on_delete=models.CASCADE)"
    v = cg.check_code(code, {"fk_id_prefix": True})
    assert len(v) == 1 and v[0]["rule"] == "fk_id_prefix"


def test_check_accepts_fk_with_prefix():
    code = "id_empresa = models.ForeignKey('E', on_delete=models.CASCADE)"
    assert cg.check_code(code, {"fk_id_prefix": True}) == []


def test_check_noop_when_convention_absent():
    # Si el repo no sigue la convención, no se evalúa esa regla.
    assert cg.check_code('logging.getLogger("x")', {"module_logger": False}) == []


# ── conventions_report ───────────────────────────────────────────────────────

def test_report_not_checked_without_conventions(tmp_path):
    rep = cg.conventions_report(str(tmp_path), "cualquier codigo")
    assert rep["ok"] is True and rep["checked"] is False


def test_report_blocks_on_violation(tmp_path):
    (tmp_path / "m.py").write_text("logger = logging.getLogger(__name__)\n", encoding="utf-8")
    rep = cg.conventions_report(str(tmp_path), 'logging.getLogger("bad")')
    assert rep["checked"] is True and rep["ok"] is False
    assert rep["violations"][0]["rule"] == "module_logger"


# ── bloqueo en A9 ────────────────────────────────────────────────────────────

def test_a9_routes_convention_violation_to_a6(monkeypatch):
    import nodes.a9_sandbox as a9
    monkeypatch.setattr(a9, "run_all_checks",
                        lambda *a, **k: {"passed": True, "summary": "ok", "gate_failures": []})
    monkeypatch.setattr("tools.file_tools.save_agent_output", lambda *a, **k: None)
    monkeypatch.setattr("config.CONVENTIONS_GATE_ENABLED", True, raising=False)
    monkeypatch.setattr("config.REGRESSION_GATE_ENABLED", False, raising=False)
    monkeypatch.setattr("tools.conventions_gate.conventions_report",
                        lambda repo, code: {"ok": False, "checked": True,
                                            "violations": [{"rule": "fk_id_prefix", "message": "x"}]})

    state = {"repo_path": "/r", "feature_id": "F1", "sandbox_iterations": 0,
             "files_written": [], "backend_code": "empresa = models.ForeignKey()"}
    out = a9.a9_sandbox(state)
    assert out["sandbox_passed"] is False
    assert any(gf["gate"] == "conventions" and gf["hard"] is False
               for gf in out["sandbox_gate_failures"])


def test_a9_no_block_when_conventions_gate_disabled(monkeypatch):
    import nodes.a9_sandbox as a9
    monkeypatch.setattr(a9, "run_all_checks",
                        lambda *a, **k: {"passed": True, "summary": "ok", "gate_failures": []})
    monkeypatch.setattr("tools.file_tools.save_agent_output", lambda *a, **k: None)
    monkeypatch.setattr("config.CONVENTIONS_GATE_ENABLED", False, raising=False)
    monkeypatch.setattr("config.REGRESSION_GATE_ENABLED", False, raising=False)
    state = {"repo_path": "/r", "feature_id": "F1", "sandbox_iterations": 0, "files_written": []}
    assert a9.a9_sandbox(state)["sandbox_passed"] is True
