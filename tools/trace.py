"""
Correlation IDs (trace_id) para observabilidad — Bloque E (PLAN_BLINDAJE_TOTAL) E1.1.

Permite que todos los logs emitidos durante el procesamiento de un feature compartan
un mismo identificador de traza, facilitando correlacionar la actividad de los agentes.

Uso típico:
    from tools.trace import new_trace_id, set_trace_id, install_trace_logging
    install_trace_logging()                      # una vez al arrancar el proceso
    set_trace_id(new_trace_id(feature_id))       # al entrar al procesamiento del feature

El trace_id se almacena en un contextvars.ContextVar, por lo que es seguro entre
corrutinas/hilos sin filtrarse entre features.
"""
from __future__ import annotations
import contextvars
import logging
from uuid import uuid4

# Almacén del trace id actual. "-" cuando no hay traza activa.
trace_id_var: contextvars.ContextVar[str] = contextvars.ContextVar("trace_id", default="-")

# Formato de log recomendado que incluye el trace_id entre corchetes.
TRACE_LOG_FORMAT = "%(asctime)s %(levelname)s [%(name)s] [%(trace_id)s] %(message)s"


def set_trace_id(tid: str) -> None:
    """Fija el trace_id de la traza actual (cadena vacía → '-')."""
    trace_id_var.set(tid or "-")


def get_trace_id() -> str:
    """Devuelve el trace_id actual o '-' si no hay traza activa."""
    return trace_id_var.get()


def new_trace_id(feature_id: str = "") -> str:
    """
    Deriva un trace_id corto y estable.

    Si hay feature_id se reutiliza tal cual (así todo el feature comparte traza);
    si no, se genera un hex de 12 caracteres a partir de un uuid4.
    """
    return feature_id or uuid4().hex[:12]


class TraceIdFilter(logging.Filter):
    """Inyecta el atributo `trace_id` en cada LogRecord ('-' si no hay traza)."""

    def filter(self, record: logging.LogRecord) -> bool:
        # getattr defensivo: si algún record ya trae trace_id, se respeta.
        if not hasattr(record, "trace_id"):
            record.trace_id = get_trace_id()
        return True


def install_trace_logging(fmt: str = TRACE_LOG_FORMAT, datefmt: str = "%H:%M:%S") -> None:
    """
    Instala el TraceIdFilter en el root logger y sus handlers, y aplica un formato
    que incluye `[%(trace_id)s]`. Barato e idempotente: no añade el filtro dos veces.
    """
    root = logging.getLogger()

    # Asegurar el filtro en el root logger (cubre LogRecords sin handler propio).
    if not any(isinstance(f, TraceIdFilter) for f in root.filters):
        root.addFilter(TraceIdFilter())

    formatter = logging.Formatter(fmt, datefmt=datefmt)
    for handler in root.handlers:
        if not any(isinstance(f, TraceIdFilter) for f in handler.filters):
            handler.addFilter(TraceIdFilter())
        handler.setFormatter(formatter)
