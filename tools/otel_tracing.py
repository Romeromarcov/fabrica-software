"""
tools/otel_tracing.py — Observabilidad OpenTelemetry (PLAN_PLATAFORMA_V2 M7, Fase 3).

Emite spans por agente (timeline, latencia, tokens) reutilizando el trace_id de E1.1.
Exporta vía OTLP a Jaeger/Grafana Tempo cuando hay un collector configurado.

Diseño sin dependencias duras: si `opentelemetry` no está instalado o `OTEL_ENABLED=false`,
TODO es no-op (un context manager nulo) → comportamiento idéntico. La fábrica NO añade
opentelemetry a requirements (opcional: `pip install opentelemetry-sdk opentelemetry-exporter-otlp`).

Sin side effects al importar; el proveedor se inicializa de forma perezosa e idempotente.
"""
from __future__ import annotations

import contextlib
import logging
from typing import Iterator

logger = logging.getLogger(__name__)

_PROVIDER_READY = False


def otel_available() -> bool:
    """True si el SDK de OpenTelemetry está instalado."""
    try:
        import opentelemetry.trace  # noqa: F401
        return True
    except ImportError:
        return False


def enabled() -> bool:
    """True si la observabilidad OTel está habilitada Y disponible."""
    try:
        from config import OTEL_ENABLED
    except ImportError:
        OTEL_ENABLED = False
    return bool(OTEL_ENABLED) and otel_available()


def init_tracing(service_name: str = "fabrica-software") -> bool:
    """
    Inicializa el TracerProvider (idempotente). Devuelve True si quedó activo.
    Best-effort: cualquier fallo deja la observabilidad en no-op sin romper nada.
    """
    global _PROVIDER_READY
    if not enabled():
        return False
    if _PROVIDER_READY:
        return True
    try:
        import os

        from opentelemetry import trace
        from opentelemetry.sdk.resources import Resource
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor

        provider = TracerProvider(resource=Resource.create({"service.name": service_name}))
        endpoint = os.getenv("OTEL_EXPORTER_OTLP_ENDPOINT", "")
        if endpoint:
            from opentelemetry.exporter.otlp.proto.http.trace_exporter import OTLPSpanExporter
            provider.add_span_processor(BatchSpanProcessor(OTLPSpanExporter()))
        trace.set_tracer_provider(provider)
        _PROVIDER_READY = True
        logger.info("otel_tracing: TracerProvider activo (endpoint=%s)", endpoint or "(none)")
        return True
    except Exception as exc:  # noqa: BLE001 — la observabilidad nunca rompe el pipeline
        logger.warning("otel_tracing: init falló (%s); observabilidad en no-op", exc)
        return False


@contextlib.contextmanager
def span(name: str, **attributes) -> Iterator[None]:
    """
    Context manager de span. Si OTel no está activo, es un no-op (nullcontext).
    Adjunta el trace_id de E1.1 como atributo del span.
    """
    if not enabled() or not init_tracing():
        yield
        return
    # Setup del span (import/tracer). Si falla → no-op observable. IMPORTANTE: el `yield` del
    # cuerpo NO va dentro de este try — una excepción del cuerpo (p. ej. un agente que agota
    # reintentos) debe PROPAGARSE, no tragarse. Antes, el except hacía `yield` de nuevo tras el
    # del cuerpo → "generator didn't stop after throw()" y enmascaraba el error real (F6).
    try:
        from opentelemetry import trace
        from tools.trace import get_trace_id

        tracer = trace.get_tracer("fabrica")
        _trace_id = get_trace_id()
    except Exception as exc:  # noqa: BLE001 — setup falló → degradar a no-op
        logger.warning("otel_tracing: span '%s' no se pudo iniciar (%s); continúa sin traza", name, exc)
        yield
        return

    with tracer.start_as_current_span(name) as sp:
        try:
            sp.set_attribute("fabrica.trace_id", _trace_id)
            for k, v in attributes.items():
                if v is not None:
                    sp.set_attribute(k, v)
        except Exception:  # noqa: BLE001 — atributos best-effort
            logger.debug("otel_tracing: no se pudieron fijar atributos", exc_info=True)
        # El cuerpo corre aquí; si lanza, el span lo registra y la excepción se propaga.
        yield


def reset_for_tests() -> None:
    """Resetea el estado del proveedor (solo para tests)."""
    global _PROVIDER_READY
    _PROVIDER_READY = False
