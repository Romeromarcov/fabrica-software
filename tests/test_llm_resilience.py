"""
PLAN_BLINDAJE_TOTAL — Bloque E, E2: resiliencia LLM.

Suite OFFLINE (sin red): mockea por completo `openclaw.client.run_agent` (la superficie
que invoca el subprocess/HTTP del gateway) y parchea asyncio.sleep/time.sleep para que
los reintentos no esperen de verdad. Cubre:

  - E2.1 Backoff exponencial: el helper puro `backoff_delays` crece exponencialmente y
    queda topado en `cap`.
  - E2.1 Manejo de 429: un rate-limit transitorio reintenta (durmiendo, parcheado) y
    luego tiene éxito.
  - E2.2 CircuitBreaker: abre tras `threshold` fallos consecutivos y resetea en éxito.
  - E2.2 Fallback de modelo: con MODEL_FALLBACKS primario→alterno y el primario fallando
    siempre, el cliente intenta el modelo alterno.
"""
import asyncio

import pytest

import openclaw.client as oc


# ──────────────────────────────────────────────────────────────────────────────
# Helpers de test
# ──────────────────────────────────────────────────────────────────────────────

class _RateLimitError(Exception):
    """Imita el RateLimitError del SDK: status_code 429."""
    status_code = 429


@pytest.fixture(autouse=True)
def _no_sleep(monkeypatch):
    """Anula las esperas reales: backoff instantáneo en todos los tests."""
    async def _fake_async_sleep(_seconds):
        return None

    monkeypatch.setattr(oc.asyncio, "sleep", _fake_async_sleep)
    # Por si algún día se usa time.sleep en el módulo.
    import time as _time
    monkeypatch.setattr(_time, "sleep", lambda *_a, **_k: None)


@pytest.fixture(autouse=True)
def _fresh_breaker():
    """Resetea el breaker módulo-level antes y después de cada test."""
    oc.breaker.record_success()
    yield
    oc.breaker.record_success()


def _run(coro):
    return asyncio.run(coro)


# ──────────────────────────────────────────────────────────────────────────────
# E2.1 — Backoff exponencial (helper puro)
# ──────────────────────────────────────────────────────────────────────────────

def test_backoff_delays_crecen_exponencialmente():
    assert oc.backoff_delays(4, 2) == [2, 4, 8, 16]


def test_backoff_delays_topados_en_cap():
    delays = oc.backoff_delays(8, 2, cap=10)
    # 2, 4, 8, 16→10, 32→10, ...
    assert delays[:3] == [2, 4, 8]
    assert all(d <= 10 for d in delays)
    assert delays[-1] == 10


def test_backoff_delays_vacio_si_no_hay_reintentos():
    assert oc.backoff_delays(0, 2) == []


# ──────────────────────────────────────────────────────────────────────────────
# E2.1 — Detección y manejo de 429
# ──────────────────────────────────────────────────────────────────────────────

def test_is_rate_limit_error_por_status_code():
    assert oc._is_rate_limit_error(_RateLimitError("nope"))


def test_is_rate_limit_error_por_mensaje():
    assert oc._is_rate_limit_error(RuntimeError("HTTP 429 Too Many Requests"))
    assert oc._is_rate_limit_error(RuntimeError("rate limit exceeded"))


def test_is_rate_limit_error_falso_para_error_normal():
    assert not oc._is_rate_limit_error(RuntimeError("boom genérico"))


def test_retry_after_desde_mensaje():
    assert oc._retry_after_seconds(RuntimeError("please retry after 12 seconds")) == 12.0


def test_429_reintenta_y_luego_tiene_exito(monkeypatch):
    """Una llamada que falla con 429 y luego responde OK debe terminar con éxito,
    habiendo reintentado y dormido (sleep parcheado)."""
    calls = {"n": 0}
    slept: list[float] = []

    async def fake_run_agent(agent_key, task, timeout=600, model=None):
        calls["n"] += 1
        if calls["n"] == 1:
            raise _RateLimitError("429 too many requests")
        return "respuesta-ok"

    async def spy_sleep(seconds):
        slept.append(seconds)

    monkeypatch.setattr(oc, "run_agent", fake_run_agent)
    monkeypatch.setattr(oc.asyncio, "sleep", spy_sleep)

    out = _run(oc.run_agent_with_retry("a4_backend", "tarea", retries=3))

    assert out == "respuesta-ok"
    assert calls["n"] == 2          # 1 fallo + 1 éxito
    assert len(slept) == 1          # durmió una vez (el backoff del 429)
    assert slept[0] > 0


def test_agota_reintentos_y_relanza(monkeypatch):
    """Si todas las llamadas fallan (sin fallback), se relanza la excepción y el
    breaker registra el fallo."""
    async def always_fail(agent_key, task, timeout=600, model=None):
        raise RuntimeError("proveedor caído")

    monkeypatch.setattr(oc, "run_agent", always_fail)
    # Sin fallbacks configurados para este modelo.
    monkeypatch.setattr(oc, "_model_for_agent", lambda _k: "modelo-sin-fallback")

    with pytest.raises(RuntimeError, match="proveedor caído"):
        _run(oc.run_agent_with_retry("a4_backend", "tarea", retries=2))


# ──────────────────────────────────────────────────────────────────────────────
# E2.2 — Circuit breaker
# ──────────────────────────────────────────────────────────────────────────────

def test_breaker_abre_tras_umbral_y_resetea_en_exito():
    br = oc.CircuitBreaker(threshold=3)
    assert br.allow() is True

    br.record_failure()
    br.record_failure()
    assert br.allow() is True       # aún por debajo del umbral
    assert not br.is_open()

    br.record_failure()             # 3er fallo consecutivo → ABRE
    assert br.is_open()
    assert br.allow() is False

    br.record_success()             # un éxito RESETEA
    assert br.allow() is True
    assert not br.is_open()
    assert br.failures == 0


def test_breaker_abierto_falla_rapido_sin_llamar_proveedor(monkeypatch):
    """Con el breaker ABIERTO, run_agent_with_retry no debe invocar run_agent."""
    called = {"n": 0}

    async def fake_run_agent(*a, **k):
        called["n"] += 1
        return "no-deberia-llegar"

    monkeypatch.setattr(oc, "run_agent", fake_run_agent)
    # Forzar breaker abierto.
    monkeypatch.setattr(oc.breaker, "_open", True, raising=False)

    with pytest.raises(RuntimeError, match="CircuitBreaker ABIERTO"):
        _run(oc.run_agent_with_retry("a4_backend", "tarea", retries=1))

    assert called["n"] == 0         # falló rápido, sin tocar el proveedor


# ──────────────────────────────────────────────────────────────────────────────
# E2.2 — Fallback de modelo
# ──────────────────────────────────────────────────────────────────────────────

def test_fallback_intenta_modelo_alterno(monkeypatch):
    """Con MODEL_FALLBACKS primario→alterno y el primario fallando siempre, el cliente
    debe intentar el modelo alterno (registrando qué modelo se pidió)."""
    requested: list[str | None] = []

    async def fake_run_agent(agent_key, task, timeout=600, model=None):
        requested.append(model)
        if model is None:
            # El primario (model=None) siempre falla.
            raise RuntimeError("primario caído")
        return f"ok-con-{model}"

    monkeypatch.setattr(oc, "run_agent", fake_run_agent)
    monkeypatch.setattr(oc, "_model_for_agent", lambda _k: "glm-5.1")
    # Inyectar la cadena de fallback (parchea la fuente que lee run_agent_with_retry).
    import config
    monkeypatch.setattr(
        config, "parse_model_fallbacks",
        lambda: {"glm-5.1": "claude-sonnet-4-6"},
    )

    out = _run(oc.run_agent_with_retry("a4_backend", "tarea", retries=1))

    assert out == "ok-con-claude-sonnet-4-6"
    # Primero intentó el primario (None) varias veces, luego el alterno.
    assert None in requested
    assert "claude-sonnet-4-6" in requested


def test_sin_fallback_configurado_no_intenta_alterno(monkeypatch):
    """Sin entrada en MODEL_FALLBACKS para el modelo del agente, no hay segundo modelo."""
    requested: list[str | None] = []

    async def fake_run_agent(agent_key, task, timeout=600, model=None):
        requested.append(model)
        raise RuntimeError("todo falla")

    monkeypatch.setattr(oc, "run_agent", fake_run_agent)
    monkeypatch.setattr(oc, "_model_for_agent", lambda _k: "glm-5.1")
    import config
    monkeypatch.setattr(config, "parse_model_fallbacks", lambda: {})

    with pytest.raises(RuntimeError, match="todo falla"):
        _run(oc.run_agent_with_retry("a4_backend", "tarea", retries=1))

    # Solo se pidió el modelo primario (None); nunca un alterno.
    assert all(m is None for m in requested)
