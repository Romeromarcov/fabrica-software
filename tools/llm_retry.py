"""
Reintento de errores transitorios para el PATH DIRECTO (nodes/base.call_agent).

La resiliencia E2.1/E2.2 (backoff + breaker) solo vivía en `openclaw/client.py`,
así que la ruta directa (USE_OPENCLAW=false — la que usa prod) NO tenía reintento:
un único 503 UNAVAILABLE transitorio de Gemini mataba al agente. Este módulo
añade reintento de errores transitorios (429 + 5xx + conexión/timeout) reutilizando
los helpers de backoff y el CircuitBreaker del cliente OpenClaw.
"""
from __future__ import annotations
import asyncio
import logging
import time
from typing import Callable, TypeVar

# Reutilizamos el backoff exponencial y la detección de 429 del cliente OpenClaw
# para no duplicar lógica ya testeada (E2.1).
from openclaw.client import backoff_delays, _is_rate_limit_error, _retry_after_seconds

logger = logging.getLogger(__name__)

T = TypeVar("T")

# Códigos HTTP de servidor que justifican reintento (errores transitorios del proveedor).
_SERVER_ERROR_CODES = (500, 502, 503, 504)

# Nombres de clase de excepción que tratamos como transitorios (SDKs OpenAI/Anthropic/httpx).
_SERVER_ERROR_CLASSES = {"InternalServerError", "APITimeoutError", "APIConnectionError"}

# Substrings (lower) que delatan un 5xx/sobrecarga aunque no haya status_code estructurado.
_SERVER_ERROR_MARKERS = ("503", "unavailable", "overloaded")


def is_transient_error(exc: BaseException) -> bool:
    """
    True si la excepción es reintentable (transitoria):
      - rate-limit (429): vía `_is_rate_limit_error` (status_code, clase o mensaje).
      - errores de servidor 5xx (500/502/503/504): por status_code, clase o mensaje.
      - conexión/timeout: OSError, TimeoutError, asyncio.TimeoutError.

    Falsa para errores claros de cliente (400/401/403/404, ValueError, KeyError, …).
    """
    # 429 — rate limit (reutiliza la lógica de OpenClaw).
    if _is_rate_limit_error(exc):
        return True

    # 5xx — error de servidor por status code estructurado.
    if getattr(exc, "status_code", None) in _SERVER_ERROR_CODES:
        return True

    # 5xx — por nombre de clase (SDKs no siempre exponen status_code).
    if type(exc).__name__ in _SERVER_ERROR_CLASSES:
        return True

    # Conexión/timeout — transitorios por naturaleza.
    if isinstance(exc, (OSError, TimeoutError, asyncio.TimeoutError)):
        return True

    # 5xx/sobrecarga — última red por mensaje (p.ej. Gemini "503 UNAVAILABLE").
    msg = str(exc).lower()
    return any(marker in msg for marker in _SERVER_ERROR_MARKERS)


def retry_after_seconds(exc: BaseException) -> float | None:
    """Extrae Retry-After (segundos) del error si está disponible (reutiliza OpenClaw)."""
    return _retry_after_seconds(exc)


def retry_sync(
    call: Callable[[], T],
    *,
    label: str = "LLM",
    max_retries: int | None = None,
    base_delay: float | None = None,
    breaker=None,
    sleep: Callable[[float], None] = time.sleep,
) -> T:
    """
    Envoltura SÍNCRONA de reintento para una llamada al proveedor LLM.

    `call` es un callable sin argumentos que devuelve lo que sea. Cuando `max_retries`
    o `base_delay` son None se leen dinámicamente de config en cada invocación.

    En cada intento:
      - Si `breaker` está y `breaker.allow()` es False → relanza de inmediato (fallo rápido).
      - Llama a `call()`; en éxito `breaker.record_success()` (si hay breaker) y devuelve.
      - En excepción: si NO es transitoria → relanza de inmediato (no toca el breaker).
        Si es transitoria: `breaker.record_failure()` (si hay breaker), loguea warning y,
        si quedan intentos, duerme max(retry_after, backoff[intento]) y reintenta; si no
        quedan intentos, relanza la última excepción.

    `sleep` es inyectable para tests (sin esperas reales).
    """
    if max_retries is None or base_delay is None:
        try:
            import config
            if max_retries is None:
                max_retries = config.LLM_MAX_RETRIES
            if base_delay is None:
                base_delay = config.LLM_BACKOFF_BASE_SECONDS
        except Exception:
            # Defaults seguros si config no carga.
            if max_retries is None:
                max_retries = 4
            if base_delay is None:
                base_delay = 2.0

    delays = backoff_delays(max_retries, base_delay)
    last_exc: BaseException | None = None

    # max_retries reintentos ⇒ max_retries+1 intentos totales.
    for attempt in range(max_retries + 1):
        # Fallo rápido si el breaker está ABIERTO (no invocamos al proveedor).
        if breaker is not None and not breaker.allow():
            raise RuntimeError(
                f"CircuitBreaker ABIERTO — {label}: proveedor LLM con fallos en "
                "cascada; llamada abortada (fallo rápido)."
            )

        try:
            result = call()
        except Exception as exc:  # noqa: BLE001 — clasificamos y RE-LANZAMOS los no transitorios; NO es un swallow.
            # Errores claros de cliente (400/401/…, ValueError) se relanzan sin reintento
            # ni tocar el breaker (no son fallos del proveedor).
            if not is_transient_error(exc):
                raise
            last_exc = exc
            if breaker is not None:
                breaker.record_failure()
            if attempt >= max_retries:
                logger.warning(
                    "%s error transitorio (%s) — sin reintentos restantes (intento %d/%d)",
                    label, exc, attempt + 1, max_retries + 1,
                )
                break
            backoff = delays[attempt] if attempt < len(delays) else (delays[-1] if delays else base_delay)
            wait = max(retry_after_seconds(exc) or 0.0, backoff)
            logger.warning(
                "%s error transitorio (%s) — backoff %.1fs (intento %d/%d)",
                label, exc, wait, attempt + 1, max_retries + 1,
            )
            sleep(wait)
            continue
        else:
            if breaker is not None:
                breaker.record_success()
            return result

    assert last_exc is not None
    raise last_exc
