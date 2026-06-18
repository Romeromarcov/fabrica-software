"""
tools/agent_registry.py — Agent Registry (PLAN_PLATAFORMA_V2 Fase 0, C2-base).

Fuente única de verdad de cada agente: `agents/registry.json`. Permite que el
comportamiento de los agentes (modelo, prompt, schema de salida, dependencias,
hooks) sea **data-driven** en vez de estar hardcodeado en `graph.py`/`config.py`.

Invariante del plan — **modelo por agente siempre opcional**. Resolución en cascada:

    agent.model  →  pipeline.default_model  →  config.GLOBAL_DEFAULT_MODEL

Sin side effects al importar: el registry se lee perezosamente y se cachea.
"""
from __future__ import annotations

import json
import logging
from functools import lru_cache
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

# Ruta al registry, relativa a la raíz de la fábrica.
_REGISTRY_REL = Path("agents") / "registry.json"


def _registry_path() -> Path:
    try:
        from config import FABRICA_DIR
        return Path(FABRICA_DIR) / _REGISTRY_REL
    except ImportError:
        return _REGISTRY_REL


@lru_cache(maxsize=1)
def load_registry() -> dict:
    """Carga `agents/registry.json` (cacheado). Lanza si no existe o es inválido."""
    path = _registry_path()
    if not path.exists():
        raise FileNotFoundError(f"Agent registry no encontrado: {path}")
    data = json.loads(path.read_text(encoding="utf-8"))
    if "agents" not in data or not isinstance(data["agents"], list):
        raise ValueError("registry.json inválido: falta la lista 'agents'")
    return data


def clear_cache() -> None:
    """Limpia el cache del registry (para tests que apuntan a un registry temporal)."""
    load_registry.cache_clear()


def all_agents(pipeline: Optional[str] = None) -> list[dict]:
    """Devuelve los agentes del registry, opcionalmente filtrados por pipeline."""
    agents = load_registry()["agents"]
    if pipeline is None:
        return list(agents)
    return [a for a in agents if a.get("pipeline") == pipeline]


def get_agent(agent_id: str) -> dict:
    """Devuelve la definición de un agente por su id. Lanza KeyError si no existe."""
    for a in load_registry()["agents"]:
        if a.get("id") == agent_id:
            return a
    raise KeyError(f"Agente '{agent_id}' no está en el registry")


def pipeline_default_model(pipeline: str) -> Optional[str]:
    """Lee el default_model declarado por el pipeline (pipeline.yaml), o None."""
    try:
        from tools.pipeline_loader import load_pipeline
        return load_pipeline(pipeline).get("default_model")
    except Exception:
        return None


def resolve_model(agent_id: str, pipeline_default: Optional[str] = None) -> str:
    """
    Resuelve el modelo efectivo de un agente con la cascada del plan:
        agent.model → pipeline_default → config.GLOBAL_DEFAULT_MODEL

    `pipeline_default` puede pasarse explícitamente; si no, se intenta leer del
    pipeline.yaml del agente. Agentes sin LLM (`uses_llm=false`) devuelven "no-llm".
    """
    agent = get_agent(agent_id)

    if agent.get("uses_llm") is False:
        return "no-llm"

    model = agent.get("model")
    if model:
        return model

    if pipeline_default is None:
        pipeline_default = pipeline_default_model(agent.get("pipeline", ""))
    if pipeline_default:
        return pipeline_default

    from config import GLOBAL_DEFAULT_MODEL
    return GLOBAL_DEFAULT_MODEL


def model_fallbacks(agent_id: str) -> list[str]:
    """Lista de modelos de fallback declarados para el agente (puede ser vacía)."""
    return list(get_agent(agent_id).get("model_fallbacks") or [])
