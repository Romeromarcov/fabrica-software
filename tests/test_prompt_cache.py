"""Tests de la caché local de prompts (PLAN_PLATAFORMA_V2 M5, Fase 2)."""
import time

import pytest

from tools import prompt_cache as pc


@pytest.fixture(autouse=True)
def _tmp_cache(tmp_path, monkeypatch):
    monkeypatch.setattr(pc, "_cache_dir", lambda: tmp_path / "prompts")
    yield


def test_key_is_deterministic_and_content_addressed():
    k1 = pc.make_key("gpt-5.5", "sys", "tarea", "fp")
    k2 = pc.make_key("gpt-5.5", "sys", "tarea", "fp")
    k3 = pc.make_key("gpt-5.5", "sys", "tarea DISTINTA", "fp")
    assert k1 == k2
    assert k1 != k3


def test_set_then_get_round_trip():
    k = pc.make_key("m", "s", "t")
    assert pc.get(k) is None
    pc.set(k, "respuesta cacheada")
    assert pc.get(k) == "respuesta cacheada"


def test_ttl_expires_entry():
    k = pc.make_key("m", "s", "t-ttl")
    pc.set(k, "vieja")
    # TTL de 0 segundos no expira (desactivado); TTL negativo-efectivo simulado:
    # forzamos mtime antiguo.
    path = pc._path_for(k)
    import os
    old = time.time() - 10_000
    os.utime(path, (old, old))
    assert pc.get(k, ttl_seconds=3600) is None      # expiró
    assert not path.exists()                          # y se limpió


def test_ttl_zero_never_expires():
    k = pc.make_key("m", "s", "t-keep")
    pc.set(k, "permanece")
    assert pc.get(k, ttl_seconds=0) == "permanece"


def test_clear_removes_entries():
    pc.set(pc.make_key("m", "s", "a"), "x")
    pc.set(pc.make_key("m", "s", "b"), "y")
    assert pc.clear() == 2
    assert pc.get(pc.make_key("m", "s", "a")) is None


def test_get_missing_returns_none():
    assert pc.get("deadbeef" * 8) is None


def test_base_call_uses_cache_on_second_call(monkeypatch):
    """Integración: con la caché on y proveedor no-anthropic, la 2ª llamada no toca el LLM."""
    import nodes.base as base
    from state import CostEntry

    monkeypatch.setattr(base, "USE_OPENCLAW", False)
    monkeypatch.setattr("tools.file_tools.read_static", lambda *a, **k: "")
    monkeypatch.setattr("tools.file_tools.read_system_prompt", lambda *a, **k: "SYS")
    monkeypatch.setattr("config.SEMANTIC_CACHE_ENABLED", True, raising=False)

    calls = {"n": 0}

    def fake_openai(**kw):
        calls["n"] += 1
        return "RESPUESTA LLM", CostEntry(agent="A4", model="gpt-5.5",
                                          input_tokens=1, output_tokens=1, cost_usd=0.01)

    monkeypatch.setattr(base, "_call_openai_compat", fake_openai)

    kwargs = dict(agent_key="a4_backend", agent_label="A4", model="gpt-5.5",
                  task_content="tarea unica de cache", include_static=[])
    t1, c1 = base.call_agent(**kwargs)
    t2, c2 = base.call_agent(**kwargs)

    assert t1 == t2 == "RESPUESTA LLM"
    assert calls["n"] == 1                 # la 2ª vino de caché
    assert c2["cost_usd"] == 0.0           # sin costo en el hit
