"""
tools/langsmith_tracing.py — Observabilidad LangSmith (PLAN_MAESTRO F0.1).

Provee un callback `LangChainTracer` para inyectar en la invocación del grafo LangGraph
(`app.stream(state, config={"callbacks": [...]})`). Cuando LangSmith está habilitado, cada
run del grafo aparece como una traza navegable (nodos como pasos) en el proyecto LangSmith.

Diseño sin dependencias duras / sin side effects al importar:
  - Si `langsmith`/`langchain-core` no están instalados o el tracing está deshabilitado,
    `tracing_callbacks()` devuelve `[]` → la invocación del grafo es idéntica a hoy.
  - Se habilita con `LANGCHAIN_TRACING_V2=true` (o `LANGSMITH_TRACING=true`) y una
    `LANGCHAIN_API_KEY`/`LANGSMITH_API_KEY`. El proyecto se toma de `LANGCHAIN_PROJECT`.

Es complementario a `otel_tracing` (OTLP/Jaeger): OTel da spans por agente con tokens/coste;
LangSmith da el árbol de ejecución del grafo. Ambos reusan el mismo run real.
"""
from __future__ import annotations

import importlib.util
import logging
import os

logger = logging.getLogger(__name__)


def langsmith_available() -> bool:
    """True si el cliente de LangSmith y el tracer de langchain están instalados.

    Usa `find_spec` (sin try/except de import) para no introducir un manejador
    silencioso: devuelve un bool consultando el sistema de importación.
    """
    return (
        importlib.util.find_spec("langsmith") is not None
        and importlib.util.find_spec("langchain_core.tracers") is not None
    )


def _tracing_flag() -> bool:
    """Lee el flag de tracing de las env vars estándar de LangSmith/LangChain."""
    val = os.getenv("LANGCHAIN_TRACING_V2") or os.getenv("LANGSMITH_TRACING") or ""
    return val.strip().lower() == "true"


def _has_api_key() -> bool:
    return bool(os.getenv("LANGCHAIN_API_KEY") or os.getenv("LANGSMITH_API_KEY"))


def enabled() -> bool:
    """True si LangSmith está habilitado por env, con API key y disponible (instalado)."""
    return _tracing_flag() and _has_api_key() and langsmith_available()


def project_name() -> str:
    return os.getenv("LANGCHAIN_PROJECT") or os.getenv("LANGSMITH_PROJECT") or "fabrica-software"


def tracing_callbacks() -> list:
    """
    Devuelve los callbacks de tracing para `config["callbacks"]` de la invocación del grafo.
    Lista vacía si LangSmith no está habilitado/instalado (no-op, sin cambiar el comportamiento).
    """
    if not enabled():
        return []
    try:
        from langchain_core.tracers import LangChainTracer
        return [LangChainTracer(project_name=project_name())]
    except Exception as exc:  # noqa: BLE001 — la observabilidad nunca rompe el pipeline
        logger.warning("langsmith_tracing: no se pudo crear el tracer (%s); sin traza LangSmith", exc)
        return []
