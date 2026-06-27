"""Tests de la observabilidad OpenTelemetry (PLAN_PLATAFORMA_V2 M7, Fase 3).

Se ejercita el camino NO-OP (opentelemetry no requerido en CI / flag off). El span
debe ser un context manager seguro en todos los casos.
"""
import pytest

from tools import otel_tracing as ot


@pytest.fixture(autouse=True)
def _reset():
    ot.reset_for_tests()
    yield
    ot.reset_for_tests()


def test_available_is_bool():
    assert isinstance(ot.otel_available(), bool)


def test_disabled_by_default(monkeypatch):
    monkeypatch.setattr("config.OTEL_ENABLED", False, raising=False)
    assert ot.enabled() is False


def test_span_is_noop_context_manager_when_disabled(monkeypatch):
    monkeypatch.setattr("config.OTEL_ENABLED", False, raising=False)
    ran = False
    with ot.span("agent.a4", **{"llm.model": "x"}):
        ran = True
    assert ran  # el cuerpo se ejecuta sin error


def test_init_tracing_noop_when_disabled(monkeypatch):
    monkeypatch.setattr("config.OTEL_ENABLED", False, raising=False)
    assert ot.init_tracing() is False


def test_span_yields_even_if_enabled_but_sdk_missing(monkeypatch):
    # Forzamos enabled=True pero sin SDK → debe degradar a no-op sin lanzar.
    monkeypatch.setattr("config.OTEL_ENABLED", True, raising=False)
    monkeypatch.setattr(ot, "otel_available", lambda: False)
    ran = False
    with ot.span("agent.a5"):
        ran = True
    assert ran


def test_base_call_agent_span_does_not_break(monkeypatch):
    """La envoltura de span en call_agent no altera el resultado (no-op por defecto)."""
    import nodes.base as base
    from state import CostEntry

    monkeypatch.setattr(base, "USE_OPENCLAW", False)
    monkeypatch.setattr("tools.file_tools.read_static", lambda *a, **k: "")
    monkeypatch.setattr("tools.file_tools.read_system_prompt", lambda *a, **k: "SYS")
    monkeypatch.setattr("config.OTEL_ENABLED", False, raising=False)
    monkeypatch.setattr(base, "_call_anthropic",
                        lambda **k: ("ok", CostEntry(agent="A4", model="claude-sonnet-4-6",
                                                     input_tokens=1, output_tokens=1, cost_usd=0.0)))
    text, _ = base.call_agent(agent_key="a4_backend", agent_label="A4",
                              model="claude-sonnet-4-6", task_content="t", include_static=[])
    assert text == "ok"


def test_span_propagates_body_exception_cleanly(monkeypatch):
    """F6: una excepción dentro de span() debe PROPAGARSE como tal (no 'generator didn't stop')."""
    monkeypatch.setattr("config.OTEL_ENABLED", True, raising=False)
    ot.reset_for_tests()
    import pytest as _pytest
    with _pytest.raises(ValueError, match="boom"):
        with ot.span("agent.test"):
            raise ValueError("boom")
