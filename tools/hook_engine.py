"""
tools/hook_engine.py — Motor de hooks del ciclo de vida (PLAN_PLATAFORMA_V2 R2).

Puntos de extensión registrables en el ciclo de vida de un agente/feature:
    pre_agent, post_agent, pre_write, post_qa, on_approval, on_error, pre_pr

Los hooks son funciones puras `(context: dict) -> dict | None`. Si devuelven un dict,
sus claves se fusionan en el contexto que se pasa al siguiente hook (encadenado).
Diseño best-effort: un hook que lanza se loguea y NO rompe el pipeline (salvo el
punto `on_error`, que igualmente protege para no enmascarar el error original).

Sin side effects al importar: el registro arranca vacío; se puebla desde
`config.py`/pipeline.yaml o en tests.
"""
from __future__ import annotations

import logging
from typing import Callable, Optional

logger = logging.getLogger(__name__)

HookFn = Callable[[dict], Optional[dict]]

# Puntos válidos del ciclo de vida.
HOOK_POINTS = (
    "pre_agent",
    "post_agent",
    "pre_write",
    "post_qa",
    "on_approval",
    "on_error",
    "pre_pr",
)

# Registro: punto → lista de hooks (orden de registro = orden de ejecución).
_REGISTRY: dict[str, list[HookFn]] = {point: [] for point in HOOK_POINTS}


def register(point: str, fn: HookFn) -> None:
    """Registra un hook en un punto del ciclo de vida. Lanza si el punto es inválido."""
    if point not in _REGISTRY:
        raise ValueError(f"Punto de hook desconocido: {point}. Válidos: {HOOK_POINTS}")
    _REGISTRY[point].append(fn)
    logger.debug("hook registrado en %s: %s", point, getattr(fn, "__name__", repr(fn)))


def unregister_all(point: Optional[str] = None) -> None:
    """Limpia hooks de un punto (o de todos si point es None). Útil en tests."""
    if point is None:
        for p in _REGISTRY:
            _REGISTRY[p].clear()
    elif point in _REGISTRY:
        _REGISTRY[point].clear()


def registered(point: str) -> list[HookFn]:
    """Devuelve los hooks registrados en un punto (copia)."""
    return list(_REGISTRY.get(point, []))


def run_hooks(point: str, context: Optional[dict] = None) -> dict:
    """
    Ejecuta en orden los hooks de `point`, encadenando el contexto.

    Cada hook recibe el contexto acumulado; si devuelve un dict, se fusiona.
    Un hook que lanza se loguea (best-effort) y se omite — el resto siguen.
    Devuelve el contexto final.
    """
    ctx = dict(context or {})
    if point not in _REGISTRY:
        raise ValueError(f"Punto de hook desconocido: {point}")

    for fn in _REGISTRY[point]:
        try:
            result = fn(ctx)
            if isinstance(result, dict):
                ctx.update(result)
        except Exception as exc:  # noqa: BLE001 — best-effort por diseño
            logger.warning(
                "hook %s en %s lanzó %s — omitido",
                getattr(fn, "__name__", repr(fn)), point, exc,
            )
    return ctx
