"""
tools/prompt_cache.py — Caché local de prompts (PLAN_PLATAFORMA_V2 M5, Fase 2).

Para proveedores SIN caché nativa (Google/OpenAI/Z.ai/Kimi). Anthropic ya cachea
nativamente, así que el router lo salta para esos modelos. La clave es el hash de
(modelo + system prompt + tarea + fingerprint del repo): entradas idénticas →
respuesta reutilizable, ahorrando una llamada al LLM.

Determinista y content-addressed (no "semántico difuso"): solo acierta ante entradas
idénticas, lo que lo hace seguro. Lógica pura + IO de disco; sin side effects al importar.
Opt-in vía `SEMANTIC_CACHE_ENABLED` (default off → comportamiento idéntico).
"""
from __future__ import annotations

import hashlib
import logging
import time
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


def _cache_dir() -> Path:
    try:
        from config import FABRICA_DIR
        base = Path(FABRICA_DIR) / "data" / "cache" / "prompts"
    except ImportError:
        base = Path("data/cache/prompts")
    return base


def make_key(model: str, system_prompt: str, task_content: str, fingerprint: str = "") -> str:
    """Clave content-addressed (sha256) de la llamada."""
    h = hashlib.sha256()
    for part in (model, system_prompt, task_content, fingerprint):
        h.update((part or "").encode("utf-8"))
        h.update(b"\x00")
    return h.hexdigest()


def _path_for(key: str) -> Path:
    # Sharding por prefijo para no saturar un solo directorio.
    return _cache_dir() / key[:2] / f"{key}.txt"


def get(key: str, ttl_seconds: int = 0) -> Optional[str]:
    """
    Devuelve la respuesta cacheada o None. Si `ttl_seconds` > 0, ignora (y limpia)
    entradas más antiguas que el TTL.
    """
    path = _path_for(key)
    if not path.exists():
        return None
    if ttl_seconds > 0 and (time.time() - path.stat().st_mtime) > ttl_seconds:
        try:
            path.unlink()
        except OSError as exc:
            from tools.degradation import best_effort_log
            best_effort_log("Limpieza de entrada de caché expirada", exc, logger)
        return None
    try:
        return path.read_text(encoding="utf-8")
    except OSError as exc:
        logger.warning("prompt_cache: lectura falló (%s)", exc)
        return None


def set(key: str, text: str) -> None:
    """Guarda la respuesta en caché (best-effort)."""
    path = _path_for(key)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text or "", encoding="utf-8")
    except OSError as exc:
        logger.warning("prompt_cache: escritura falló (%s)", exc)


def clear() -> int:
    """Borra toda la caché. Devuelve el número de entradas eliminadas (para tests/mant.)."""
    base = _cache_dir()
    if not base.exists():
        return 0
    count = 0
    for p in base.rglob("*.txt"):
        try:
            p.unlink()
            count += 1
        except OSError as exc:
            from tools.degradation import best_effort_log
            best_effort_log("Borrado de entrada de caché", exc, logger)
    return count
