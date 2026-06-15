"""
Cliente async para OpenClaw.
Invoca `openclaw agent --agent <id> --message <task> --json` como subprocess.

El binario openclaw se instala via npm en el Dockerfile del contenedor fabrica.
"""
from __future__ import annotations
import asyncio
import json
import logging
import os
import random
import re

logger = logging.getLogger(__name__)

OPENCLAW_TOKEN = os.getenv("OPENCLAW_GATEWAY_TOKEN", "")
OPENCLAW_URL   = os.getenv("OPENCLAW_URL", "http://openclaw:18789")

# Tope del backoff exponencial (segundos) para que un base alto no espere minutos.
_BACKOFF_CAP_SECONDS = 60.0

# ══════════════════════════════════════════════════════════════════════════════
# E2.1 — Backoff exponencial (helper puro, testeable sin red)
# ══════════════════════════════════════════════════════════════════════════════

def backoff_delays(max_retries: int, base: float,
                   cap: float = _BACKOFF_CAP_SECONDS) -> list[float]:
    """
    Devuelve la secuencia de esperas (segundos) ANTES de cada reintento.

    Crecimiento exponencial: base * 2**intento, topado en `cap`.
    Para max_retries=4, base=2 → [2, 4, 8, 16]. Sin jitter (determinista) para
    que sea fácil de testear; el jitter se aplica aparte en el cliente.
    """
    out: list[float] = []
    for attempt in range(max(0, max_retries)):
        out.append(min(base * (2 ** attempt), cap))
    return out


def _is_rate_limit_error(exc: BaseException) -> bool:
    """Detecta errores de rate-limit (HTTP 429) por status code, tipo o mensaje."""
    status = getattr(exc, "status_code", None) or getattr(exc, "status", None)
    if status == 429:
        return True
    if type(exc).__name__ in ("RateLimitError",):
        return True
    msg = str(exc).lower()
    return "429" in msg or "rate limit" in msg or "too many requests" in msg


def _retry_after_seconds(exc: BaseException) -> float | None:
    """Extrae Retry-After (segundos) de un error 429 si está disponible."""
    # Cabecera HTTP en respuestas tipo httpx/openai SDK
    resp = getattr(exc, "response", None)
    headers = getattr(resp, "headers", None) if resp is not None else None
    if headers:
        try:
            val = headers.get("Retry-After") or headers.get("retry-after")
            if val is not None:
                return float(val)
        except (ValueError, TypeError):
            pass
    # Mensaje "retry after 12s" / "retry after 12 seconds"
    match = re.search(r"retry[\s\-]?after[:\s]+(\d+(?:\.\d+)?)", str(exc).lower())
    if match:
        try:
            return float(match.group(1))
        except ValueError:
            return None
    return None


# ══════════════════════════════════════════════════════════════════════════════
# E2.2 — Circuit breaker en-proceso
# ══════════════════════════════════════════════════════════════════════════════

class CircuitBreaker:
    """
    Breaker simple por proceso: cuenta fallos consecutivos del proveedor.

    Tras `threshold` fallos consecutivos ABRE (allow() → False) para fallar rápido
    y evitar que 100 features caigan en cascada. Un éxito lo RESETEA (vuelve a CLOSED).
    Estado compartido por proceso (instancia módulo-level `breaker`).
    """

    def __init__(self, threshold: int = 5):
        self.threshold = max(1, threshold)
        self._failures = 0
        self._open = False

    @property
    def failures(self) -> int:
        return self._failures

    def is_open(self) -> bool:
        return self._open

    def allow(self) -> bool:
        """True si se permite la llamada; False si el breaker está ABIERTO."""
        return not self._open

    def record_success(self) -> None:
        """Un éxito resetea el contador y cierra el breaker."""
        if self._open:
            logger.info("CircuitBreaker: éxito tras apertura — RESET (CLOSED)")
        self._failures = 0
        self._open = False

    def record_failure(self) -> None:
        """Un fallo incrementa el contador; al llegar al umbral ABRE el breaker."""
        self._failures += 1
        if self._failures >= self.threshold and not self._open:
            self._open = True
            logger.error(
                "CircuitBreaker ABIERTO tras %d fallos consecutivos del proveedor LLM",
                self._failures,
            )
            _notify_breaker_open(self._failures)


def _breaker_threshold() -> int:
    try:
        from config import LLM_BREAKER_THRESHOLD
        return LLM_BREAKER_THRESHOLD
    except Exception:
        return 5


# Instancia compartida por proceso.
breaker = CircuitBreaker(threshold=_breaker_threshold())


def _notify_breaker_open(failures: int) -> None:
    """Notifica por Telegram (best-effort) que el breaker LLM se abrió."""
    try:
        from tools.telegram import send_message
        send_message(
            f"🔌 *Circuit breaker LLM ABIERTO*\n"
            f"{failures} fallos consecutivos del proveedor. "
            f"Las llamadas fallarán rápido hasta el próximo éxito."
        )
    except Exception as exc:
        logger.warning("No se pudo notificar apertura del breaker: %s", exc)


# Mapeo agent_key (el que pasa call_agent) → perfil OpenClaw.
# DEBE coincidir con los agent_key reales del pipeline (= claves de
# SYSTEM_PROMPT_PATHS en config.py). El mapa anterior usaba una taxonomía vieja
# (a2_backend/a3_frontend/a4_qa/a6_db/a7_secops/a8_mcp) que NO existe hoy y hacía
# fallar el modo OpenClaw para casi todos los agentes.
AGENT_PROFILE_MAP = {
    "a0":          "a0-arquitecto",
    "a0_revisor":  "a0-revisor",
    "a1_pm":       "a1-pm",
    "a2_db":       "a2-db",
    "a3_mcp":      "a3-mcp",
    "a4_backend":  "a4-backend",
    "a5_frontend": "a5-frontend",
    "a6_refactor": "a6-refactor",
    "a7_qa":       "a7-qa",
    "a8_secops":   "a8-secops",
    "meta_agent":  "meta-agent",
}


def profile_for(agent_key: str) -> str:
    """Perfil OpenClaw para un agent_key. Fallback determinista (`_`→`-`) para
    claves no mapeadas, de modo que un agente nuevo nunca rompa el modo OpenClaw."""
    return AGENT_PROFILE_MAP.get(agent_key) or agent_key.replace("_", "-")


async def health_check() -> bool:
    """Verifica que el gateway OpenClaw esté accesible vía HTTP."""
    try:
        import httpx
        async with httpx.AsyncClient(timeout=5) as c:
            r = await c.get(f"{OPENCLAW_URL}/healthz")
            return r.status_code == 200
    except Exception:
        return False


async def run_agent(
    agent_key: str,
    task: str,
    timeout: int = 600,
    model: str | None = None,
) -> str:
    """
    Ejecuta un agente OpenClaw y devuelve su respuesta completa.

    Usa `openclaw agent --agent <profile> --message <task> --json --url <url>`
    con OPENCLAW_GATEWAY_TOKEN en el entorno del subprocess.

    Si se pasa `model` (p.ej. desde la cadena de fallback E2.2) se añade
    `--model <model>` para forzar un modelo alterno en el gateway.
    """
    profile_id = profile_for(agent_key)

    env = {**os.environ, "OPENCLAW_GATEWAY_TOKEN": OPENCLAW_TOKEN}

    logger.info(
        "OpenClaw → agente=%s modelo=%s tarea=%s…",
        profile_id, model or "(perfil)", task[:80],
    )

    args = [
        "openclaw", "agent",
        "--agent", profile_id,
        "--message", task,
        "--json",
        "--url", OPENCLAW_URL,
    ]
    if model:
        args += ["--model", model]

    proc = await asyncio.create_subprocess_exec(
        *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        env=env,
    )

    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except asyncio.TimeoutError:
        proc.kill()
        raise TimeoutError(f"Agente {profile_id} superó el límite de {timeout}s")

    if proc.returncode != 0:
        err = stderr.decode(errors="replace").strip()
        raise RuntimeError(f"openclaw agent falló (rc={proc.returncode}): {err}")

    raw = stdout.decode(errors="replace").strip()
    if not raw:
        raise RuntimeError(f"Agente {profile_id} no retornó salida")

    try:
        data = json.loads(raw)
        # OpenClaw --json puede devolver distintos campos según la versión
        return data.get("content") or data.get("text") or data.get("result") or raw
    except json.JSONDecodeError:
        return raw


# Excepciones transitorias que justifican reintento. Solo específicas (sin bare except).
_RETRYABLE = (OSError, RuntimeError, TimeoutError, asyncio.TimeoutError)


async def _run_with_backoff(
    agent_key: str,
    task: str,
    *,
    timeout: int,
    max_retries: int,
    base: float,
    model: str | None,
) -> str:
    """
    Ejecuta run_agent con backoff exponencial y manejo especial de 429.

    Devuelve el texto en éxito. Relanza la última excepción si agota los intentos.
    No toca el circuit breaker (lo gestiona el caller para distinguir éxito/fallo).
    """
    delays = backoff_delays(max_retries, base)
    last_exc: BaseException | None = None

    # max_retries reintentos ⇒ max_retries+1 intentos totales.
    for attempt in range(max_retries + 1):
        try:
            return await run_agent(agent_key, task, timeout=timeout, model=model)
        except Exception as exc:  # noqa: BLE001 — se filtra abajo, NO es bare except.
            # Solo reintentamos errores transitorios concretos o rate-limit (429). El
            # RateLimitError del SDK OpenAI-compatible NO hereda de RuntimeError, por eso
            # se contempla aparte vía _is_rate_limit_error en lugar de ampliar _RETRYABLE.
            if not isinstance(exc, _RETRYABLE) and not _is_rate_limit_error(exc):
                raise
            last_exc = exc
            if attempt >= max_retries:
                break
            wait = delays[attempt] if attempt < len(delays) else delays[-1]
            if _is_rate_limit_error(exc):
                # 429: respetar Retry-After si está; si no, esperar más (doble del backoff).
                retry_after = _retry_after_seconds(exc)
                wait = retry_after if retry_after is not None else wait * 2
                wait = min(wait, _BACKOFF_CAP_SECONDS)
                logger.warning(
                    "OpenClaw 429/rate-limit (%s) — backoff %.1fs (intento %d/%d)",
                    exc, wait, attempt + 1, max_retries,
                )
            else:
                logger.warning(
                    "OpenClaw error (%s) — backoff %.1fs (intento %d/%d)",
                    exc, wait, attempt + 1, max_retries,
                )
            # Jitter pequeño (±10%) para evitar thundering herd entre features paralelos.
            jitter = wait * 0.1 * (random.random() * 2 - 1)
            await asyncio.sleep(max(0.0, wait + jitter))

    assert last_exc is not None
    raise last_exc


async def run_agent_with_retry(
    agent_key: str,
    task: str,
    retries: int | None = None,
    timeout: int = 600,
) -> str:
    """
    run_agent con backoff exponencial (E2.1), circuit breaker (E2.2) y fallback
    de modelo (E2.2).

    - `retries`: máximo de reintentos. Si es None se toma LLM_MAX_RETRIES de config.
    - Si el breaker está ABIERTO la llamada falla rápido (no se invoca al proveedor).
    - Tras agotar los reintentos con el modelo primario, si MODEL_FALLBACKS define
      un alterno para el modelo configurado del agente, se intenta UNA vez con él.
    """
    try:
        from config import (
            LLM_MAX_RETRIES, LLM_BACKOFF_BASE_SECONDS, parse_model_fallbacks,
        )
        max_retries = LLM_MAX_RETRIES if retries is None else retries
        base = LLM_BACKOFF_BASE_SECONDS
        fallbacks = parse_model_fallbacks()
    except Exception:
        # Si config no carga por algún motivo, defaults seguros.
        max_retries = 4 if retries is None else retries
        base = 2.0
        fallbacks = {}

    # E2.2 — fallo rápido si el breaker está abierto.
    if not breaker.allow():
        raise RuntimeError(
            "CircuitBreaker ABIERTO — proveedor LLM con fallos en cascada; "
            "llamada abortada (fallo rápido)."
        )

    # Modelo primario configurado para este agente (para resolver el fallback).
    primary_model = _model_for_agent(agent_key)

    try:
        text = await _run_with_backoff(
            agent_key, task, timeout=timeout, max_retries=max_retries,
            base=base, model=None,
        )
        breaker.record_success()
        return text
    except Exception as primary_exc:  # noqa: BLE001 — se filtra abajo, NO es bare except.
        # Solo manejamos (breaker + fallback) errores transitorios o rate-limit; el resto
        # se relanza sin tocar el breaker (no son fallos del proveedor).
        if not isinstance(primary_exc, _RETRYABLE) and not _is_rate_limit_error(primary_exc):
            raise
        alt_model = fallbacks.get(primary_model) if primary_model else None
        if not alt_model:
            breaker.record_failure()
            raise
        logger.warning(
            "Modelo primario '%s' agotó reintentos — probando fallback '%s'",
            primary_model, alt_model,
        )
        try:
            text = await _run_with_backoff(
                agent_key, task, timeout=timeout, max_retries=max_retries,
                base=base, model=alt_model,
            )
            breaker.record_success()
            return text
        except Exception as alt_exc:  # noqa: BLE001 — se filtra abajo, NO es bare except.
            if not isinstance(alt_exc, _RETRYABLE) and not _is_rate_limit_error(alt_exc):
                raise
            breaker.record_failure()
            raise primary_exc


def _model_for_agent(agent_key: str) -> str | None:
    """
    Modelo configurado para un agent_key (para resolver MODEL_FALLBACKS).

    Mapea las claves del pipeline a las variables MODEL_* de config. Si no se puede
    resolver devuelve None (sin fallback).
    """
    try:
        import config
    except Exception:
        return None
    mapping = {
        "a0":          "MODEL_A0",
        "a0_revisor":  "MODEL_A0_REVISOR",
        "a1_pm":       "MODEL_A1",
        "a2_db":       "MODEL_A2",
        "a3_mcp":      "MODEL_A3",
        "a4_backend":  "MODEL_A4",
        "a5_frontend": "MODEL_A5",
        "a6_refactor": "MODEL_A6",
        "a7_qa":       "MODEL_A7",
        "a8_secops":   "MODEL_A8",
    }
    attr = mapping.get(agent_key)
    if not attr:
        return None
    return getattr(config, attr, None)
