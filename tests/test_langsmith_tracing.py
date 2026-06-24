"""Tests de la observabilidad LangSmith (PLAN_MAESTRO F0.1).

Se ejercita el camino NO-OP (sin API key / tracing off) y el enrutado de habilitación.
No se requiere conexión real a LangSmith: el tracer solo se construye si está habilitado
Y la dep está instalada, y aquí se mockea la disponibilidad.
"""
import pytest

from tools import langsmith_tracing as ls


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    for k in ("LANGCHAIN_TRACING_V2", "LANGSMITH_TRACING",
              "LANGCHAIN_API_KEY", "LANGSMITH_API_KEY",
              "LANGCHAIN_PROJECT", "LANGSMITH_PROJECT"):
        monkeypatch.delenv(k, raising=False)
    yield


def test_available_is_bool():
    assert isinstance(ls.langsmith_available(), bool)


def test_disabled_without_env():
    assert ls.enabled() is False
    assert ls.tracing_callbacks() == []


def test_disabled_when_flag_on_but_no_api_key(monkeypatch):
    monkeypatch.setenv("LANGCHAIN_TRACING_V2", "true")
    assert ls.enabled() is False
    assert ls.tracing_callbacks() == []


def test_disabled_when_api_key_but_flag_off(monkeypatch):
    monkeypatch.setenv("LANGCHAIN_API_KEY", "ls__fake")
    assert ls.enabled() is False


def test_enabled_requires_flag_key_and_availability(monkeypatch):
    monkeypatch.setenv("LANGCHAIN_TRACING_V2", "true")
    monkeypatch.setenv("LANGCHAIN_API_KEY", "ls__fake")
    monkeypatch.setattr(ls, "langsmith_available", lambda: True)
    assert ls.enabled() is True


def test_project_name_default_and_override(monkeypatch):
    assert ls.project_name() == "fabrica-software"
    monkeypatch.setenv("LANGCHAIN_PROJECT", "mi-proyecto")
    assert ls.project_name() == "mi-proyecto"


def test_tracing_callbacks_returns_tracer_when_enabled(monkeypatch):
    monkeypatch.setenv("LANGCHAIN_TRACING_V2", "true")
    monkeypatch.setenv("LANGCHAIN_API_KEY", "ls__fake")
    monkeypatch.setattr(ls, "langsmith_available", lambda: True)

    class _FakeTracer:
        def __init__(self, project_name=None):
            self.project_name = project_name

    import sys, types
    fake_mod = types.ModuleType("langchain_core.tracers")
    fake_mod.LangChainTracer = _FakeTracer
    monkeypatch.setitem(sys.modules, "langchain_core.tracers", fake_mod)

    cbs = ls.tracing_callbacks()
    assert len(cbs) == 1
    assert isinstance(cbs[0], _FakeTracer)
    assert cbs[0].project_name == "fabrica-software"


def test_thread_config_injects_callbacks_only_when_enabled(monkeypatch):
    """_thread_config (cli) inyecta callbacks solo si LangSmith está habilitado."""
    import cli
    monkeypatch.setattr("tools.langsmith_tracing.tracing_callbacks", lambda: [])
    cfg = cli._thread_config("feat-1")
    assert cfg == {"configurable": {"thread_id": "feat-1"}}
    assert "callbacks" not in cfg

    sentinel = [object()]
    monkeypatch.setattr("tools.langsmith_tracing.tracing_callbacks", lambda: sentinel)
    cfg2 = cli._thread_config("feat-2")
    assert cfg2["callbacks"] == sentinel
    assert cfg2["configurable"]["thread_id"] == "feat-2"
