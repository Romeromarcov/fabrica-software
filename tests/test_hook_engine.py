"""Tests del motor de hooks del ciclo de vida (PLAN_PLATAFORMA_V2 R2)."""
import pytest

from tools import hook_engine as he


@pytest.fixture(autouse=True)
def _clean_hooks():
    he.unregister_all()
    yield
    he.unregister_all()


def test_all_lifecycle_points_exist():
    for point in ("pre_agent", "post_agent", "pre_write", "post_qa",
                  "on_approval", "on_error", "pre_pr"):
        assert point in he.HOOK_POINTS


def test_register_invalid_point_raises():
    with pytest.raises(ValueError):
        he.register("no_existe", lambda c: None)


def test_run_hooks_chains_context():
    he.register("pre_agent", lambda c: {"a": 1})
    he.register("pre_agent", lambda c: {"b": c["a"] + 1})
    ctx = he.run_hooks("pre_agent", {"start": True})
    assert ctx == {"start": True, "a": 1, "b": 2}


def test_hook_returning_none_does_not_break_chain():
    calls = []
    he.register("post_agent", lambda c: calls.append("first"))   # devuelve None
    he.register("post_agent", lambda c: {"reached": True})
    ctx = he.run_hooks("post_agent", {})
    assert calls == ["first"]
    assert ctx["reached"] is True


def test_failing_hook_is_isolated():
    def boom(c):
        raise RuntimeError("explota")
    he.register("on_error", boom)
    he.register("on_error", lambda c: {"survived": True})
    ctx = he.run_hooks("on_error", {})
    assert ctx["survived"] is True  # el fallo de boom no rompe el resto


def test_run_unknown_point_raises():
    with pytest.raises(ValueError):
        he.run_hooks("no_existe", {})


def test_unregister_all_clears():
    he.register("pre_pr", lambda c: {"x": 1})
    assert he.registered("pre_pr")
    he.unregister_all("pre_pr")
    assert not he.registered("pre_pr")
