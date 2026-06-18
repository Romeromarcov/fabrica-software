"""
tools/pipeline_loader.py — descubrimiento y carga de pipelines (PLAN_PLATAFORMA_V2 Fase 0/4).

Cada dominio vive en `pipelines/<nombre>/pipeline.yaml`. Este módulo los descubre y
parsea. Sin side effects al importar. Es la pieta que `graph_builder.py` consume.
"""
from __future__ import annotations

import logging
from functools import lru_cache
from pathlib import Path

import yaml

logger = logging.getLogger(__name__)


def _pipelines_dir() -> Path:
    try:
        from config import FABRICA_DIR
        return Path(FABRICA_DIR) / "pipelines"
    except ImportError:
        return Path("pipelines")


def discover_pipelines() -> list[str]:
    """Devuelve los nombres de pipelines con un `pipeline.yaml` válido en disco."""
    base = _pipelines_dir()
    if not base.exists():
        return []
    names = []
    for child in sorted(base.iterdir()):
        if child.is_dir() and (child / "pipeline.yaml").exists():
            names.append(child.name)
    return names


@lru_cache(maxsize=16)
def load_pipeline(name: str) -> dict:
    """Carga y valida `pipelines/<name>/pipeline.yaml`."""
    path = _pipelines_dir() / name / "pipeline.yaml"
    if not path.exists():
        raise FileNotFoundError(f"pipeline.yaml no encontrado para '{name}': {path}")
    data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    if not isinstance(data, dict):
        raise ValueError(f"pipeline.yaml de '{name}' no es un mapeo YAML válido")
    data.setdefault("name", name)
    if not data.get("agents"):
        raise ValueError(f"pipeline '{name}' no declara 'agents'")
    return data


def pipeline_summaries() -> list[dict]:
    """
    Resumen de cada pipeline descubierto para `fabrica-cli pipelines` (Fase 4, slice CLI).
    Pure: no lanza — un pipeline.yaml inválido se reporta con ok=False + error, para que
    el listado nunca rompa por un dominio mal formado.
    """
    out: list[dict] = []
    for name in discover_pipelines():
        try:
            d = load_pipeline(name)
        except (FileNotFoundError, ValueError) as exc:
            logger.warning("pipeline '%s' inválido, se omite del listado: %s", name, exc)
            out.append({"name": name, "ok": False, "error": str(exc),
                        "description": "", "agents": [], "entry": "", "default_model": ""})
            continue
        out.append({
            "name": d.get("name", name),
            "ok": True,
            "error": "",
            "description": d.get("description", ""),
            "agents": list(d.get("agents", [])),
            "entry": d.get("entry", ""),
            "default_model": d.get("default_model", ""),
        })
    return out


def clear_cache() -> None:
    """Limpia el cache de pipelines (para tests)."""
    load_pipeline.cache_clear()
