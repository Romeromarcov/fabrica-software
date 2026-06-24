"""
tools/agent_builder.py — Agent Builder (PLAN_PLATAFORMA_V2 Fase 5).

Genera una definición de agente a partir de una petición en lenguaje natural
("quiero un agente de SEO que…"), la **valida** contra el schema del registry, y la
**registra** en `agents/registry.json` SOLO con aprobación explícita del fundador.

Separación de responsabilidades (cada pieza es testeable de forma aislada):
  - `build_agent_definition()` : parte conversacional. La llamada al LLM es INYECTABLE
    (`llm=`) → en tests se mockea, igual que `call_agent` en el resto del repo. Sin LLM
    no se inventa éxito: si el LLM no devuelve JSON válido, se lanza (no silencioso).
  - `validate_agent_definition()` / `normalize_agent_definition()` : puras, deterministas.
  - `register_agent()` : gate de seguridad. Requiere `approved=True` (aprobación del
    fundador, Fase 5) Y `config.AGENT_BUILDER_ENABLED` Y validación OK. Si no, lanza.

Sin side effects al importar.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Callable, Optional

from tools import agent_registry as _ar

logger = logging.getLogger(__name__)

# Campos del schema del registry y sus defaults (espejo de agents/registry.json).
_AGENT_DEFAULTS: dict = {
    "id": None,
    "role": "",
    "pipeline": "software",
    "uses_llm": True,
    "model": None,                 # opcional → cascada (invariante del plan)
    "model_fallbacks": [],
    "agent_key": None,
    "node_name": None,
    "prompt_file": None,
    "output_schema": None,
    "depends_on": [],
    "hooks": [],
    "activation_flags": [],
    "judge": {"enabled": False, "model": None},
}

_REQUIRED = ("id", "role", "pipeline", "uses_llm")


def normalize_agent_definition(raw: dict) -> dict:
    """Completa una definición parcial con los defaults del schema del registry."""
    out = {k: (v.copy() if isinstance(v, (list, dict)) else v) for k, v in _AGENT_DEFAULTS.items()}
    for k, v in raw.items():
        out[k] = v
    if out.get("agent_key") is None and out.get("id"):
        out["agent_key"] = str(out["id"]).lower()
    return out


def validate_agent_definition(d: dict, existing_ids: Optional[set[str]] = None) -> list[str]:
    """
    Valida una definición de agente. Devuelve lista de errores (vacía = válida).
    No lanza: pensada para feedback al fundador antes de registrar.
    """
    errors: list[str] = []
    for field in _REQUIRED:
        if d.get(field) in (None, ""):
            errors.append(f"falta campo requerido '{field}'")

    agent_id = d.get("id")
    if agent_id is not None:
        if not isinstance(agent_id, str) or not agent_id.strip():
            errors.append("'id' debe ser un string no vacío")
        elif not all(c.isalnum() or c in "_-" for c in agent_id):
            errors.append(f"'id' '{agent_id}' tiene caracteres inválidos (usa alfanumérico/_/-)")
        elif existing_ids and agent_id in existing_ids:
            errors.append(f"'id' '{agent_id}' ya existe en el registry")

    if "uses_llm" in d and not isinstance(d["uses_llm"], bool):
        errors.append("'uses_llm' debe ser booleano")
    for list_field in ("model_fallbacks", "depends_on", "hooks", "activation_flags"):
        if list_field in d and not isinstance(d[list_field], list):
            errors.append(f"'{list_field}' debe ser una lista")
    # uses_llm=False ⇒ no debería declarar modelo (coherencia con resolve_model → "no-llm").
    if d.get("uses_llm") is False and d.get("model") not in (None, "", "no-llm"):
        errors.append("agente sin LLM (uses_llm=false) no debe declarar 'model'")
    return errors


def _default_llm(request: str) -> str:
    """LLM real por defecto (Google/OpenAI-compat). No se usa en tests (se inyecta mock)."""
    from nodes.base import _openai_client
    from config import GLOBAL_DEFAULT_MODEL
    client = _openai_client("google")
    sys = (
        "Eres un Agent Builder. Dada una petición, devuelve SOLO un objeto JSON con la "
        "definición de un agente para el registry: campos id (MAYÚSCULAS, único), role, "
        "pipeline, uses_llm (bool), model (null para cascada), depends_on (lista de ids), "
        "output_schema (o null). Nada de texto fuera del JSON."
    )
    resp = client.chat.completions.create(
        model=GLOBAL_DEFAULT_MODEL,
        messages=[{"role": "system", "content": sys}, {"role": "user", "content": request}],
        max_tokens=600,
    )
    return resp.choices[0].message.content or ""


def build_agent_definition(request: str, llm: Optional[Callable[[str], object]] = None) -> dict:
    """
    Genera (vía LLM) y normaliza una definición candidata. NO la registra.
    `llm` recibe el texto de la petición y devuelve un dict o un str JSON.
    """
    raw = (llm or _default_llm)(request)
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ValueError(f"el LLM no devolvió JSON válido: {exc}") from exc
    if not isinstance(raw, dict):
        raise ValueError(f"definición de agente inesperada (se esperaba dict): {type(raw)}")
    return normalize_agent_definition(raw)


def register_agent(definition: dict, *, approved: bool, registry_path: Optional[Path] = None) -> dict:
    """
    Registra el agente en el registry SOLO si: el flag AGENT_BUILDER_ENABLED está activo,
    `approved=True` (aprobación explícita del fundador) y la definición es válida.
    Persiste el JSON, limpia el cache y devuelve el registry actualizado. Si no, lanza.
    """
    import config
    if not getattr(config, "AGENT_BUILDER_ENABLED", False):
        raise PermissionError("AGENT_BUILDER_ENABLED está desactivado; registro bloqueado.")
    if not approved:
        raise PermissionError("registro requiere aprobación explícita del fundador (approved=True).")

    path = registry_path or _ar._registry_path()
    data = json.loads(path.read_text(encoding="utf-8"))
    existing_ids = {a.get("id") for a in data.get("agents", [])}

    errors = validate_agent_definition(definition, existing_ids)
    if errors:
        raise ValueError("definición de agente inválida: " + "; ".join(errors))

    data["agents"].append(normalize_agent_definition(definition))
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    _ar.clear_cache()
    logger.info("Agent Builder registró el agente '%s' en el pipeline '%s'",
                definition.get("id"), definition.get("pipeline"))
    return data
