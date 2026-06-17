"""
Reintento de errores transitorios en el PATH DIRECTO (tools/llm_retry + nodes.base).

Suite OFFLINE (sin red): el `sleep` se inyecta/parchea para que el backoff no espere
de verdad. Cubre:

  - is_transient_error: 503/429/OSError/TimeoutError → True; 400/ValueError → False.
  - retry_sync: reintenta transitorios, relanza no-transitorios al instante, agota
    reintentos relanzando la última excepción, y falla rápido con breaker abierto.
  - Integración: call_agent (USE_OPENCLAW=False) reintenta un 503 transitorio del
    proveedor directo y termina con éxito.
"""
import asyncio

import pytest

import config
from tools import llm_retry


# ──────────────────────────────────────────────────────────────────────────────
# Helpers de test
# ──────────────────────────────────────────────────────────────────────────────

class _HttpError(Exception):
    """Imita un error de SDK con status_code estructurado."""
    def __init__(self, msg, status_code):
        super().__init__(msg)
        self.status_code = status_code


class _RateLimitError(Exception):
    """Imita el RateLimitError del SDK: status_code 429."""
    status_code = 429


def _503():
    return _HttpError("503 Service Unavailable", 503)


# ──────────────────────────────────────────────────────────────────────────────
# is_transient_error
# ──────────────────────────────────────────────────────────────────────────────

def test_transient_503_por_status_code():
    assert llm_retry.is_transient_error(_HttpError("boom", 503))


def test_transient_429_rate_limit():
    assert llm_retry.is_transient_error(_RateLimitError("429 too many requests"))


def test_transient_conexion_y_timeout():
    assert llm_retry.is_transient_error(OSError("connection reset"))
    assert llm_retry.is_transient_error(TimeoutError("timed out"))
    assert llm_retry.is_transient_error(asyncio.TimeoutError())


def test_transient_503_por_mensaje_sin_status():
    assert llm_retry.is_transient_error(RuntimeError("Gemini 503 UNAVAILABLE"))
    assert llm_retry.is_transient_error(RuntimeError("model is overloaded"))


def test_no_transient_para_errores_de_cliente():
    assert not llm_retry.is_transient_error(_HttpError("bad request", 400))
    assert not llm_retry.is_transient_error(ValueError("input inválido"))
    assert not llm_retry.is_transient_error(KeyError("missing"))


# ──────────────────────────────────────────────────────────────────────────────
# retry_sync
# ──────────────────────────────────────────────────────────────────────────────

def test_retry_sync_reintenta_transitorio_y_tiene_exito():
    calls = {"n": 0}
    slept: list[float] = []

    def call():
        calls["n"] += 1
        if calls["n"] <= 2:
            raise _503()
        return "ok"

    out = llm_retry.retry_sync(call, sleep=slept.append)

    assert out == "ok"
    assert calls["n"] == 3          # 2 fallos + 1 éxito
    assert len(slept) == 2          # durmió antes de cada reintento
    assert all(s > 0 for s in slept)


def test_retry_sync_relanza_no_transitorio_sin_reintentar():
    calls = {"n": 0}
    slept: list[float] = []

    def call():
        calls["n"] += 1
        raise ValueError("input inválido")

    with pytest.raises(ValueError, match="input inválido"):
        llm_retry.retry_sync(call, sleep=slept.append)

    assert calls["n"] == 1          # sin reintento
    assert slept == []              # sin esperas


def test_retry_sync_agota_reintentos_y_relanza_503():
    calls = {"n": 0}
    slept: list[float] = []

    def call():
        calls["n"] += 1
        raise _503()

    with pytest.raises(_HttpError):
        llm_retry.retry_sync(call, sleep=slept.append)

    # max_retries reintentos ⇒ max_retries+1 intentos totales.
    assert calls["n"] == config.LLM_MAX_RETRIES + 1


def test_retry_sync_breaker_abierto_falla_rapido():
    calls = {"n": 0}

    class _OpenBreaker:
        def allow(self):
            return False
        def record_success(self):  # pragma: no cover
            pass
        def record_failure(self):  # pragma: no cover
            pass

    def call():
        calls["n"] += 1
        return "no-deberia-llegar"

    with pytest.raises(RuntimeError, match="CircuitBreaker ABIERTO"):
        llm_retry.retry_sync(call, breaker=_OpenBreaker(), sleep=lambda *_: None)

    assert calls["n"] == 0          # falló rápido, sin invocar al proveedor


# ──────────────────────────────────────────────────────────────────────────────
# Integración — call_agent (path directo) reintenta un 503
# ──────────────────────────────────────────────────────────────────────────────

def test_call_agent_directo_reintenta_503(monkeypatch, tmp_path):
    import nodes.base as base
    import tools.event_bus as eb

    # Offline + sin OpenClaw + eventos a tmp.
    monkeypatch.setattr(base, "USE_OPENCLAW", False, raising=False)
    monkeypatch.setattr(eb, "RUNS_DIR", tmp_path, raising=False)
    monkeypatch.setattr(base, "_provider", lambda _m: "google", raising=False)

    # Sin docs estáticos / skills en el camino.
    monkeypatch.setattr(base, "read_static", lambda *a, **k: "", raising=False)

    calls = {"n": 0}

    def fake_compat(*, provider, agent_key, agent_label, model,
                    static_keys, extra_context, task_content):
        calls["n"] += 1
        if calls["n"] == 1:
            raise _HttpError("503 UNAVAILABLE", 503)
        return "respuesta-ok", {"cost_usd": 0.0, "input_tokens": 1, "output_tokens": 1}

    monkeypatch.setattr(base, "_call_openai_compat", fake_compat, raising=False)
    # Sin esperas reales en el reintento.
    monkeypatch.setattr(base.retry_sync.__globals__["time"], "sleep", lambda *_: None)

    text, cost_entry = base.call_agent(
        agent_key="a4_backend",
        agent_label="A4",
        task_content="haz algo",
        model="gemini-2.0-flash",
    )

    assert text == "respuesta-ok"
    assert calls["n"] == 2          # 1 fallo (503) + 1 éxito
