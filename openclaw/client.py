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

logger = logging.getLogger(__name__)

OPENCLAW_TOKEN = os.getenv("OPENCLAW_GATEWAY_TOKEN", "")
OPENCLAW_URL   = os.getenv("OPENCLAW_URL", "http://openclaw:18789")

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
) -> str:
    """
    Ejecuta un agente OpenClaw y devuelve su respuesta completa.

    Usa `openclaw agent --agent <profile> --message <task> --json --url <url>`
    con OPENCLAW_GATEWAY_TOKEN en el entorno del subprocess.
    """
    profile_id = profile_for(agent_key)

    env = {**os.environ, "OPENCLAW_GATEWAY_TOKEN": OPENCLAW_TOKEN}

    logger.info("OpenClaw → agente=%s tarea=%s…", profile_id, task[:80])

    proc = await asyncio.create_subprocess_exec(
        "openclaw", "agent",
        "--agent", profile_id,
        "--message", task,
        "--json",
        "--url", OPENCLAW_URL,
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


async def run_agent_with_retry(
    agent_key: str,
    task: str,
    retries: int = 2,
    timeout: int = 600,
) -> str:
    """run_agent con reintentos ante errores transitorios."""
    for attempt in range(retries + 1):
        try:
            return await run_agent(agent_key, task, timeout=timeout)
        except (OSError, RuntimeError) as exc:
            if attempt == retries:
                raise
            wait = 5 * (attempt + 1)
            logger.warning("OpenClaw error (%s), reintentando en %ds…", exc, wait)
            await asyncio.sleep(wait)
    raise RuntimeError("Unreachable")
