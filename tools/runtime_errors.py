"""
tools/runtime_errors.py — Errores de runtime → audit_backlog (PLAN_BLINDAJE_TOTAL D2.2).

Núcleo PURO y OFFLINE-VERIFICABLE de la captura de errores de runtime de la app VIVA
en dev: toma eventos de error ya recolectados (Sentry o logging estructurado),
los **agrupa/deduplica** por firma, asigna **tier por severidad y frecuencia**, y los
emite como items de backlog con el MISMO schema que `tools.audit_backlog` para que el
auditor y la maduración por riesgo (D2.3) los traten igual que un hallazgo de auditoría.

La CAPTURA en sí (consultar Sentry, leer los logs del servicio en Railway dev) es la
arista de infra que requiere red/credenciales — fuera de este módulo. Aquí solo se
TRANSFORMA la lista de eventos ya obtenida en backlog priorizado.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger(__name__)


def _high_threshold() -> int:
    """Recurrencias de un error de nivel `error` que lo escalan a tier HIGH."""
    try:
        from config import RUNTIME_ERROR_HIGH_THRESHOLD
        return RUNTIME_ERROR_HIGH_THRESHOLD
    except ImportError:
        logger.warning("config no importable; umbral de error HIGH por defecto 10")
        return 10


@dataclass
class RuntimeErrorEvent:
    """Un evento de error de runtime ya capturado de la app viva."""

    error_type: str               # p.ej. "ValueError", "HTTP500", "IntegrityError"
    message: str = ""
    path: Optional[str] = None    # endpoint donde ocurrió, si aplica
    count: int = 1                # ocurrencias agregadas de esta firma
    level: str = "error"          # "critical" | "error" | "warning"


# Normaliza un mensaje para deduplicar: baja a minúsculas, colapsa números/UUIDs/espacios.
_NUM_RE = re.compile(r"\b[0-9a-f]{8,}\b|\b\d+\b")
_WS_RE = re.compile(r"\s+")


def _normalize_message(message: str) -> str:
    msg = (message or "").lower()
    msg = _NUM_RE.sub("#", msg)
    return _WS_RE.sub(" ", msg).strip()


def _signature(event: RuntimeErrorEvent) -> tuple[str, str, str]:
    """Firma de deduplicación: (tipo, mensaje normalizado, path)."""
    return (
        (event.error_type or "").strip(),
        _normalize_message(event.message),
        (event.path or "").strip(),
    )


def group_events(events: list[RuntimeErrorEvent]) -> list[RuntimeErrorEvent]:
    """Agrupa eventos por firma sumando `count`; conserva el nivel más severo del grupo.

    Determinista: el orden de salida sigue la primera aparición de cada firma.
    """
    severity_order = {"critical": 0, "error": 1, "warning": 2}
    grouped: dict[tuple, RuntimeErrorEvent] = {}
    for ev in events or []:
        sig = _signature(ev)
        if sig in grouped:
            g = grouped[sig]
            g.count += max(1, ev.count)
            if severity_order.get(ev.level, 1) < severity_order.get(g.level, 1):
                g.level = ev.level
        else:
            grouped[sig] = RuntimeErrorEvent(
                error_type=ev.error_type,
                message=ev.message,
                path=ev.path,
                count=max(1, ev.count),
                level=ev.level,
            )
    return list(grouped.values())


def severity_tier(event: RuntimeErrorEvent) -> str:
    """Mapea un evento agrupado a tier de riesgo (mismo vocabulario que audit_backlog).

    - `critical` → HIGH siempre.
    - `error` → HIGH si recurre ≥ umbral (un error que se repite en dev es crítico),
      MEDIUM en caso contrario.
    - `warning` → LOW.
    """
    level = (event.level or "error").lower()
    if level == "critical":
        return "HIGH"
    if level == "warning":
        return "LOW"
    # nivel "error" (o desconocido): escala por frecuencia.
    return "HIGH" if event.count >= _high_threshold() else "MEDIUM"


_TIER_PRIORITY = {"HIGH": 1, "MEDIUM": 2, "LOW": 3}


def runtime_errors_to_backlog(events: list[RuntimeErrorEvent]) -> list[dict]:
    """Convierte eventos de error de runtime en backlog priorizado (críticos primero).

    Item shape compatible con `tools.audit_backlog.build_backlog`:
    {name, description, tier, priority, source, count, order}.
    """
    grouped = group_events(events)
    enriched = []
    for ev in grouped:
        tier = severity_tier(ev)
        enriched.append((ev, tier))
    # Orden: tier (HIGH→LOW) y, dentro del tier, mayor frecuencia primero.
    enriched.sort(key=lambda et: (_TIER_PRIORITY[et[1]], -et[0].count, et[0].error_type))
    backlog = []
    for i, (ev, tier) in enumerate(enriched):
        where = f" @ {ev.path}" if ev.path else ""
        title = f"{ev.error_type}{where} (×{ev.count})"
        backlog.append({
            "name": title[:80],
            "description": (
                f"Error de runtime en dev: {ev.error_type}{where} — "
                f"{ev.message or 'sin mensaje'} (×{ev.count})"
            ),
            "tier": tier,
            "priority": _TIER_PRIORITY[tier],
            "source": "runtime",
            "count": ev.count,
            "order": i,
        })
    return backlog


def has_blocking_errors(events: list[RuntimeErrorEvent]) -> bool:
    """True si hay algún error de runtime de tier HIGH — alimenta D2.3 (runtime_errors_clean).

    La maduración por riesgo (promotion_policy) exige `runtime_errors_clean`; un HIGH
    aquí significa que el feature NO está limpio de errores de runtime en dev.
    """
    return any(severity_tier(ev) == "HIGH" for ev in group_events(events))
