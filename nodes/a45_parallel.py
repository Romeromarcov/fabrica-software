"""
nodes/a45_parallel.py — Ejecución concurrente A4 Backend + A5 Frontend (PLAN_PLATAFORMA_V2 R3).

Cuando ambos agentes están activos, corren en paralelo (ThreadPoolExecutor) y A6 unifica.
Cada agente corre en un CONTEXTO copiado (`contextvars.copy_context()`) para que el
`trace_id` (E1.1) quede aislado por hilo y no se pisen entre sí. Cada uno recibe una COPIA
del state para evitar mutaciones compartidas.

Solo se entra a este nodo cuando `PARALLEL_AGENTS_ENABLED` y ambos agentes aplican (el
routing lo decide); por eso aquí no se re-chequean flags. NO es el paralelismo a nivel
feature (PARALLEL_FEATURES_ENABLED / CTF-FABRICA-001) — esto es intra-feature.
"""
from __future__ import annotations

import contextvars
import logging
from concurrent.futures import ThreadPoolExecutor

from state import FabricaState

logger = logging.getLogger(__name__)


def a45_parallel(state: FabricaState) -> dict:
    from nodes.a4_backend import a4_backend
    from nodes.a5_frontend import a5_frontend

    logger.info("A4+A5 en paralelo (intra-feature)")

    with ThreadPoolExecutor(max_workers=2) as ex:
        ctx_b = contextvars.copy_context()
        ctx_f = contextvars.copy_context()
        fut_b = ex.submit(ctx_b.run, a4_backend, dict(state))
        fut_f = ex.submit(ctx_f.run, a5_frontend, dict(state))
        res_b = fut_b.result()
        res_f = fut_f.result()

    # Fusión: claves disjuntas (backend_code / frontend_code) + reducidas (cost_entries,
    # errors) concatenadas UNA vez (el reducer operator.add de LangGraph las añade al canal).
    merged: dict = {}
    for k, v in res_b.items():
        if k not in ("cost_entries", "errors", "current_agent"):
            merged[k] = v
    for k, v in res_f.items():
        if k not in ("cost_entries", "errors", "current_agent"):
            merged[k] = v
    merged["cost_entries"] = list(res_b.get("cost_entries", [])) + list(res_f.get("cost_entries", []))
    merged["errors"] = list(res_b.get("errors", [])) + list(res_f.get("errors", []))
    merged["current_agent"] = "a45_parallel"
    return merged
