"""Tests de los handlers de salida pluggables (PLAN_PLATAFORMA_V2 Fase 4)."""
import pytest

from tools import output_handlers as oh


def test_builtin_handlers_registered():
    names = oh.available_handlers()
    for n in ("files", "noop", "github_pr", "notion", "email", "api_call"):
        assert n in names


def test_files_handler_writes(tmp_path):
    spec = {"type": "files", "destination": str(tmp_path)}
    payload = {"files": {"a.txt": "hola", "sub/b.md": "# título"}}
    res = oh.dispatch(spec, payload)
    assert res["status"] == "ok"
    assert (tmp_path / "a.txt").read_text() == "hola"
    assert (tmp_path / "sub" / "b.md").read_text() == "# título"
    assert set(res["written"]) == {"a.txt", "sub/b.md"}


def test_files_handler_bad_payload(tmp_path):
    res = oh.dispatch({"type": "files", "destination": str(tmp_path)},
                      {"files": ["no", "soy", "dict"]})
    assert res["status"] == "error"


def test_noop_handler():
    assert oh.dispatch({"type": "noop"}, {})["status"] == "ok"


def test_external_handlers_are_not_configured():
    for t in ("github_pr", "notion", "email", "api_call"):
        res = oh.dispatch({"type": t}, {"x": 1})
        # Honesto: no finge éxito.
        assert res["status"] == "not_configured"
        assert res["handler"] == t


def test_unknown_type_raises():
    with pytest.raises(ValueError):
        oh.dispatch({"type": "telepatia"}, {})


def test_missing_type_raises():
    with pytest.raises(ValueError):
        oh.dispatch({}, {})


def test_register_custom_handler():
    oh.register_handler("custom_test", lambda p, s: {"status": "ok", "handler": "custom_test"})
    assert oh.dispatch({"type": "custom_test"}, {})["handler"] == "custom_test"
