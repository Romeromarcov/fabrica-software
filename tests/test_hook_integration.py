"""Integración del hook engine en base.call_agent (PLAN_PLATAFORMA_V2 R2).

Verifica que sin hooks el comportamiento es idéntico y que un hook pre_agent puede
influir en la llamada (opt-in). Se mockea el dispatch al proveedor — sin red.
"""
import pytest

import nodes.base as base
from state import CostEntry
from tools import hook_engine as he


@pytest.fixture(autouse=True)
def _clean(monkeypatch):
    he.unregister_all()
    monkeypatch.setattr(base, "USE_OPENCLAW", False)
    # Evita lecturas de skills/docs del repo durante el test.
    monkeypatch.setattr("tools.file_tools.read_static", lambda *a, **k: "")
    yield
    he.unregister_all()


def _fake_cost() -> CostEntry:
    return {"agent": "x", "model": "m", "input_tokens": 1, "output_tokens": 1,
            "cost_usd": 0.0}


def test_no_hooks_passes_task_unchanged(monkeypatch):
    captured = {}

    def fake_anthropic(**kwargs):
        captured.update(kwargs)
        return "salida", _fake_cost()

    monkeypatch.setattr(base, "_call_anthropic", fake_anthropic)
    text, _ = base.call_agent(
        agent_key="a4_backend", agent_label="A4", model="claude-sonnet-4-6",
        task_content="TAREA ORIGINAL", include_static=[],
    )
    assert text == "salida"
    assert captured["task_content"] == "TAREA ORIGINAL"


def test_pre_agent_hook_can_override_task(monkeypatch):
    captured = {}

    def fake_anthropic(**kwargs):
        captured.update(kwargs)
        return "ok", _fake_cost()

    monkeypatch.setattr(base, "_call_anthropic", fake_anthropic)
    he.register("pre_agent", lambda c: {"task_content": c["task_content"] + " [MOD]"})

    base.call_agent(
        agent_key="a4_backend", agent_label="A4", model="claude-sonnet-4-6",
        task_content="BASE", include_static=[],
    )
    assert captured["task_content"] == "BASE [MOD]"


def test_post_agent_hook_receives_output(monkeypatch):
    seen = {}

    monkeypatch.setattr(base, "_call_anthropic", lambda **k: ("RESULTADO", _fake_cost()))
    he.register("post_agent", lambda c: seen.update(c))

    base.call_agent(
        agent_key="a4_backend", agent_label="A4", model="claude-sonnet-4-6",
        task_content="x", include_static=[],
    )
    assert seen.get("output_text") == "RESULTADO"
