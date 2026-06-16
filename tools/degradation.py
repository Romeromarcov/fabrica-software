"""
tools/degradation.py — Helpers de degradación observable (Plan Blindaje Total E3.1).

Objetivo de E3.1: convertir la degradación SILENCIOSA de dependencias de contexto
del agente (fingerprint, lecciones, memoria, métricas...) en degradación OBSERVABLE.

Dos piezas, ambas puras y sin efectos secundarios al importar:

- `degraded_note(label)`  → marcador para inyectar en el prompt del LLM, de modo
  que el agente "sepa" que está trabajando sin ese contexto (a ciegas).
- `best_effort_log(...)`  → reemplaza los `pass` silenciosos: cuando una dependencia
  best-effort falla, al menos queda logueada con contexto (no se cambia el flujo:
  se sigue devolviendo el valor vacío/por defecto, solo se registra).

NO se re-lanza ninguna excepción aquí: el contrato es "swallow → swallow + log".
"""
from __future__ import annotations

import logging


def degraded_note(label: str) -> str:
    """
    Devuelve un marcador legible para inyectar en el prompt cuando un bloque de
    contexto no pudo cargarse, para que el LLM sepa que trabaja sin ese contexto.
    """
    return f"⚠️ {label} no disponible — el agente trabaja sin este contexto."


def best_effort_log(
    label: str,
    exc: BaseException,
    logger: logging.Logger,
    level: int = logging.WARNING,
) -> None:
    """
    Loguea una dependencia best-effort que falló, conservando el comportamiento
    no fatal (el llamador sigue devolviendo su valor vacío/por defecto).

    Args:
        label:  Nombre humano de la dependencia degradada (p. ej. "Lecciones aprendidas").
        exc:    La excepción capturada.
        logger: Logger del módulo llamante.
        level:  Nivel de log (por defecto WARNING).
    """
    logger.log(level, "%s no disponible (best-effort): %s", label, exc)
