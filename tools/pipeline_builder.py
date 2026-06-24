"""
tools/pipeline_builder.py — Pipeline Builder (PLAN_PLATAFORMA_V2 Fase 6).

Extiende el Agent Builder: dada "crea un pipeline legal que…", genera un `pipeline.yaml`
(name, agents, entry, gates, state, output), lo **valida** y lo **registra** escribiéndolo
en `pipelines/<name>/pipeline.yaml` SOLO con doble gate (flag + aprobación del fundador).

Mismo contrato que agent_builder: la llamada LLM es INYECTABLE (mockeable); sin YAML/JSON
válido se lanza (no se finge éxito); validación/normalización puras; registro con gates.
Sin side effects al importar.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Callable, Optional

import yaml

logger = logging.getLogger(__name__)

_PIPELINE_DEFAULTS: dict = {
    "name": None,
    "description": "",
    "default_model": None,           # opcional → cascada por agente
    "state_schema": "PipelineState",
    "entry": None,
    "agents": [],
    "human_checkpoints": [],
    "gates": [],
    "output": {"type": "noop"},
}

_REQUIRED = ("name", "entry", "agents")


def normalize_pipeline_definition(raw: dict) -> dict:
    out = {k: (v.copy() if isinstance(v, (list, dict)) else v) for k, v in _PIPELINE_DEFAULTS.items()}
    for k, v in raw.items():
        out[k] = v
    return out


def validate_pipeline_definition(d: dict, existing_names: Optional[set[str]] = None) -> list[str]:
    """Valida una definición de pipeline. Devuelve lista de errores (vacía = válida)."""
    errors: list[str] = []
    for field in _REQUIRED:
        if d.get(field) in (None, "", []):
            errors.append(f"falta campo requerido '{field}'")

    name = d.get("name")
    if name is not None:
        if not isinstance(name, str) or not name.strip():
            errors.append("'name' debe ser un string no vacío")
        elif not all(c.isalnum() or c in "_-" for c in name):
            errors.append(f"'name' '{name}' tiene caracteres inválidos (usa alfanumérico/_/-)")
        elif existing_names and name in existing_names:
            errors.append(f"'name' '{name}' ya existe como pipeline")

    agents = d.get("agents")
    if agents is not None:
        if not isinstance(agents, list):
            errors.append("'agents' debe ser una lista")
        elif not all(isinstance(a, str) and a for a in agents):
            errors.append("'agents' debe ser una lista de ids no vacíos")
        elif d.get("entry") and d["entry"] not in agents:
            errors.append(f"'entry' '{d['entry']}' no está en la lista de agents")

    for list_field in ("human_checkpoints", "gates"):
        if list_field in d and not isinstance(d[list_field], list):
            errors.append(f"'{list_field}' debe ser una lista")
    return errors


def _default_llm(request: str) -> str:
    from nodes.base import _openai_client
    from config import GLOBAL_DEFAULT_MODEL
    client = _openai_client("google")
    sys = (
        "Eres un Pipeline Builder. Dada una petición, devuelve SOLO un objeto JSON con la "
        "definición de un pipeline: name (minúsculas, único), description, agents (lista de "
        "ids), entry (uno de agents), default_model (null), gates (lista), output ({type}). "
        "Nada de texto fuera del JSON."
    )
    resp = client.chat.completions.create(
        model=GLOBAL_DEFAULT_MODEL,
        messages=[{"role": "system", "content": sys}, {"role": "user", "content": request}],
        max_tokens=800,
    )
    return resp.choices[0].message.content or ""


def build_pipeline_definition(request: str, llm: Optional[Callable[[str], object]] = None) -> dict:
    """Genera (vía LLM inyectable) y normaliza una definición candidata. NO la registra."""
    raw = (llm or _default_llm)(request)
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ValueError(f"el LLM no devolvió JSON válido: {exc}") from exc
    if not isinstance(raw, dict):
        raise ValueError(f"definición de pipeline inesperada (se esperaba dict): {type(raw)}")
    return normalize_pipeline_definition(raw)


def register_pipeline(definition: dict, *, approved: bool, base_dir: Optional[Path] = None) -> Path:
    """
    Escribe `pipelines/<name>/pipeline.yaml` SOLO si: PIPELINE_BUILDER_ENABLED activo,
    `approved=True` y la definición es válida. Devuelve la ruta escrita. Si no, lanza.
    """
    import config
    if not getattr(config, "PIPELINE_BUILDER_ENABLED", False):
        raise PermissionError("PIPELINE_BUILDER_ENABLED está desactivado; registro bloqueado.")
    if not approved:
        raise PermissionError("registro requiere aprobación explícita del fundador (approved=True).")

    if base_dir is None:
        from tools.pipeline_loader import _pipelines_dir
        base_dir = _pipelines_dir()
    base_dir = Path(base_dir)

    existing = {p.parent.name for p in base_dir.glob("*/pipeline.yaml")} if base_dir.exists() else set()
    errors = validate_pipeline_definition(definition, existing)
    if errors:
        raise ValueError("definición de pipeline inválida: " + "; ".join(errors))

    target_dir = base_dir / definition["name"]
    target_dir.mkdir(parents=True, exist_ok=True)
    path = target_dir / "pipeline.yaml"
    path.write_text(yaml.safe_dump(normalize_pipeline_definition(definition), allow_unicode=True,
                                   sort_keys=False), encoding="utf-8")
    try:
        from tools.pipeline_loader import load_pipeline
        load_pipeline.cache_clear()
    except (ImportError, AttributeError) as exc:
        logger.debug("no se pudo limpiar el cache de pipelines tras el registro: %s", exc)
    logger.info("Pipeline Builder registró el pipeline '%s' en %s", definition["name"], path)
    return path
