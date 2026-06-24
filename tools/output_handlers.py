"""
tools/output_handlers.py — Handlers de salida pluggables (PLAN_PLATAFORMA_V2 Fase 4).

Cada pipeline declara en su `pipeline.yaml` un `output: { type: ..., destination: ... }`.
El runtime multi-pipeline despacha el resultado al handler correspondiente.

Tipos:
  - `files`     → escribe artefactos a disco (implementado, real, testeable offline).
  - `noop`/`log`→ no persiste (útil para dry runs / pipelines de solo-análisis).
  - `github_pr`, `notion`, `email`, `api_call` → integraciones externas: registran un
    resultado HONESTO `not_configured` mientras no haya credenciales/cableado real
    (NO se finge éxito — alineado con "sin passed=True cuando falta la herramienta").

Sin side effects al importar; registro poblado con los built-ins.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Callable

logger = logging.getLogger(__name__)

# handler(payload: dict, spec: dict) -> dict (resultado con al menos {"status": ...})
Handler = Callable[[dict, dict], dict]

_REGISTRY: dict[str, Handler] = {}


def register_handler(name: str, fn: Handler) -> None:
    """Registra un handler de salida bajo `name`."""
    _REGISTRY[name] = fn


def available_handlers() -> list[str]:
    return sorted(_REGISTRY)


def get_handler(name: str) -> Handler | None:
    return _REGISTRY.get(name)


def dispatch(spec: dict, payload: dict) -> dict:
    """
    Despacha `payload` al handler indicado por `spec["type"]`.
    Lanza ValueError si el tipo es desconocido (no se finge un no-op silencioso).
    """
    handler_name = (spec or {}).get("type")
    if not handler_name:
        raise ValueError("output spec sin 'type'")
    handler = get_handler(handler_name)
    if handler is None:
        raise ValueError(f"handler de salida desconocido: {handler_name} "
                         f"(disponibles: {available_handlers()})")
    return handler(payload or {}, spec or {})


# ── Built-in: files ───────────────────────────────────────────────────────────

def _files_handler(payload: dict, spec: dict) -> dict:
    """
    Escribe `payload["files"]` ({ruta_relativa: contenido}) bajo `spec["destination"]`.
    Devuelve las rutas escritas. Real y verificable.
    """
    dest = Path(spec.get("destination", "."))
    files = payload.get("files", {})
    if not isinstance(files, dict):
        return {"status": "error", "handler": "files", "error": "payload['files'] debe ser dict"}
    written: list[str] = []
    errors: list[str] = []
    for rel, content in files.items():
        try:
            target = dest / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(content if isinstance(content, str) else str(content),
                              encoding="utf-8")
            written.append(str(rel))
        except OSError as exc:
            errors.append(f"{rel}: {exc}")
    return {"status": "ok" if not errors else "partial", "handler": "files",
            "written": written, "errors": errors}


def _noop_handler(payload: dict, spec: dict) -> dict:
    return {"status": "ok", "handler": "noop", "note": "salida no persistida (noop)"}


def _not_configured(name: str) -> Handler:
    """Crea un handler que reporta honestamente que la integración no está cableada."""
    def _h(payload: dict, spec: dict) -> dict:
        logger.info("output_handlers: '%s' aún no configurado (no se finge éxito)", name)
        return {"status": "not_configured", "handler": name,
                "note": f"Integración '{name}' pendiente de credenciales/cableado real."}
    return _h


# Registro de built-ins.
register_handler("files", _files_handler)
register_handler("noop", _noop_handler)
register_handler("log", _noop_handler)
for _ext in ("github_pr", "notion", "email", "api_call"):
    register_handler(_ext, _not_configured(_ext))
