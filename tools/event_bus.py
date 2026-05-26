"""
VII-2 — Event Bus: canal de observabilidad en tiempo real.

El pipeline corre como subprocess separado del servidor FastAPI.
La comunicación usa archivos JSONL en RUNS_DIR/{feature_id}/events.jsonl:
  - emit()     escribe un evento (llamado desde nodes/base.py en el subprocess)
  - tail_sse() generador async que hace tail del archivo y yielda SSE chunks

Formato de evento:
{
  "ts":       "2026-05-25T14:32:01Z",
  "feature_id": "...",
  "agent":    "A4 Backend Developer",
  "status":   "start" | "end" | "error" | "info",
  "model":    "claude-sonnet-4-6",
  "tokens_in":  1240,
  "tokens_out":  890,
  "cost_usd":   0.018,
  "msg":      "Texto libre (último log, error, etc.)"
}
"""
from __future__ import annotations

import json
import time
import logging
from datetime import datetime, timezone
from pathlib import Path

from config import RUNS_DIR

logger = logging.getLogger(__name__)

_EVENTS_FILE = "events.jsonl"
_MAX_EVENTS  = 500   # máximo de eventos por feature (evita archivos infinitos)


def _events_path(feature_id: str) -> Path:
    p = RUNS_DIR / feature_id / _EVENTS_FILE
    p.parent.mkdir(parents=True, exist_ok=True)
    return p


# ── Escritura (subprocess del pipeline) ──────────────────────────────────────

def emit(
    feature_id: str,
    agent: str,
    status: str,                # "start" | "end" | "error" | "info"
    *,
    model: str = "",
    tokens_in: int = 0,
    tokens_out: int = 0,
    cost_usd: float = 0.0,
    msg: str = "",
) -> None:
    """
    Escribe un evento en el archivo de events del feature.
    Thread-safe: cada write() a un archivo en modo 'a' es atómico en la mayoría de OS.
    """
    event = {
        "ts":          datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "feature_id":  feature_id,
        "agent":       agent,
        "status":      status,
        "model":       model,
        "tokens_in":   tokens_in,
        "tokens_out":  tokens_out,
        "cost_usd":    round(cost_usd, 6),
        "msg":         msg[:300] if msg else "",
    }
    try:
        path = _events_path(feature_id)
        with path.open("a", encoding="utf-8") as f:
            f.write(json.dumps(event, ensure_ascii=False) + "\n")
    except Exception as exc:
        logger.debug("event_bus.emit error: %s", exc)


def emit_info(feature_id: str, agent: str, msg: str) -> None:
    """Shortcut para mensajes informativos sin costo."""
    emit(feature_id, agent, "info", msg=msg)


# ── Lectura (servidor FastAPI — SSE endpoint) ─────────────────────────────────

async def tail_sse(
    feature_id: str,
    poll_interval: float = 0.5,
    timeout_seconds: int = 3600,
) -> "AsyncIterator[str]":
    """
    Generador async que hace tail del events.jsonl del feature y yielda líneas SSE.
    Se detiene automáticamente si:
      - El feature termina (status == "end" con agent == "__pipeline__")
      - Pasaron timeout_seconds sin nuevos eventos y el feature ya no está "running"
    """
    import asyncio
    import aiofiles

    path       = _events_path(feature_id)
    deadline   = time.monotonic() + timeout_seconds
    byte_pos   = 0
    idle_ticks = 0

    # Heartbeat inicial
    yield "data: {\"type\":\"connected\",\"feature_id\":\"" + feature_id + "\"}\n\n"

    while time.monotonic() < deadline:
        await asyncio.sleep(poll_interval)

        if not path.exists():
            idle_ticks += 1
            if idle_ticks > 20:   # 10s sin archivo → cerrar
                yield "data: {\"type\":\"timeout\"}\n\n"
                return
            continue

        try:
            async with aiofiles.open(path, "r", encoding="utf-8") as f:
                await f.seek(byte_pos)
                while True:
                    line = await f.readline()
                    if not line:
                        break
                    byte_pos = await f.tell()
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        event = json.loads(line)
                    except json.JSONDecodeError:
                        continue

                    idle_ticks = 0
                    # Forwarding como SSE
                    yield f"data: {json.dumps(event)}\n\n"

                    # Pipeline completo → cerrar stream
                    if event.get("agent") == "__pipeline__" and event.get("status") == "end":
                        return
        except Exception as exc:
            logger.debug("tail_sse error: %s", exc)

        idle_ticks += 1
        if idle_ticks > 120:  # 60s sin nuevos eventos
            yield "data: {\"type\":\"idle_timeout\"}\n\n"
            return

    yield "data: {\"type\":\"timeout\"}\n\n"


def emit_pipeline_end(feature_id: str, status: str = "completed") -> None:
    """Señal de cierre — el servidor SSE se desconecta al verla."""
    emit(feature_id, "__pipeline__", "end", msg=status)


def get_recent_events(feature_id: str, limit: int = 100) -> list[dict]:
    """Lee los últimos N eventos del feature (para la vista de detalle inicial)."""
    path = _events_path(feature_id)
    if not path.exists():
        return []
    try:
        lines = path.read_text(encoding="utf-8").strip().splitlines()
        events = []
        for line in lines[-limit:]:
            try:
                events.append(json.loads(line))
            except json.JSONDecodeError:
                pass
        return events
    except Exception:
        return []
