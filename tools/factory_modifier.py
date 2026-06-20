"""
tools/factory_modifier.py — Factory Modifier (PLAN_PLATAFORMA_V2 Fase 7, auto-modificación).

Cierra el lazo de auto-mejora de la fábrica: aplica cambios ACOTADOS y REVERSIBLES a la
PROPIA fábrica (prompts de agentes, campos no-estructurales del registry) a partir de una
propuesta — típicamente generada por `self_improvement` (M9) o por una petición en lenguaje
natural del fundador enrutada por `factory_router`.

Este es el ítem de MAYOR riesgo del plan (autofagia: la fábrica modificándose a sí misma),
por eso estaba escalado a sign-off humano. Se implementa con contención dura en 4 capas:

  1. DOBLE GATE — `config.FACTORY_MODIFIER_ENABLED` (flag, default false) Y `approved=True`
     (aprobación explícita del fundador). Sin ambos, `apply_factory_change` lanza.
  2. DENY-LIST DURA de objetivos protegidos — un cambio que apunte a CI/branch-protection
     (`.github/`), al wiring del grafo, a `config.py`, a los flags intocables
     (AUTO_MERGE_ENABLED / PARALLEL_FEATURES_ENABLED), a los revisores de seguridad
     (A8 / A8.5) o a sí mismo → la VALIDACIÓN falla y NO se aplica.
  3. NUNCA SOBRE `main` — `apply` exige una rama de trabajo (no main/master): el cambio
     entra por el PR pipeline normal (revisor independiente + CI). La fábrica se modifica
     vía PR, igual que modifica a OmniERP. No hay escritura autónoma a producción.
  4. SOLO CAMBIOS DETERMINISTAS Y ACOTADOS — `kind` ∈ {"prompt", "registry_field"}.

Contrato igual que `agent_builder` / `pipeline_builder`: la llamada LLM es INYECTABLE
(mockeable; sin JSON válido se lanza, no se finge éxito); `normalize_/validate_/plan_` son
puras y deterministas; `apply_factory_change` aplica los gates. Sin side effects al importar.
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Callable, Optional

logger = logging.getLogger(__name__)

# ── Objetivos protegidos (deny-list dura; un cambio que los toque NO se aplica) ──────
# Prefijos de ruta intocables (CI / branch-protection / contenedores).
PROTECTED_PATH_PREFIXES = (".github/", "scripts/", "ui/")
# Archivos concretos intocables: wiring del grafo, config, seguridad y este propio módulo.
PROTECTED_PATHS = frozenset({
    "config.py", "graph.py", "graph_project.py", "graph_builder.py", "state.py",
    "entrypoint.sh", "Dockerfile", "railway.json",
    "tools/factory_modifier.py", "tools/auth.py", "tools/code_sandbox.py",
    "tools/error_audit.py", "tools/merge_coordinator.py",
})
# Flags que NUNCA se cambian de forma autónoma (espejo del plan; defensa en profundidad).
PROTECTED_FLAGS = frozenset({"AUTO_MERGE_ENABLED", "PARALLEL_FEATURES_ENABLED"})
# Revisores de seguridad: no se permite auto-debilitarlos.
PROTECTED_AGENT_IDS = frozenset({"A8", "A8_5", "A85"})
# Ramas en las que NUNCA se escribe directamente (el cambio debe ir por PR).
PROTECTED_BRANCHES = frozenset({"main", "master"})

# Campos del registry estructurales (cablean el grafo) → inmutables por el modifier.
IMMUTABLE_REGISTRY_FIELDS = frozenset({"id", "pipeline", "node_name", "agent_key", "uses_llm"})
# Campos del registry seguros de ajustar (no cambian la topología del grafo).
MODIFIABLE_REGISTRY_FIELDS = frozenset({
    "model", "model_fallbacks", "depends_on", "hooks", "role",
    "prompt_file", "output_schema", "activation_flags", "judge",
})

VALID_KINDS = ("prompt", "registry_field")

_CHANGE_DEFAULTS: dict = {
    "kind": None,            # "prompt" | "registry_field"
    "rationale": "",         # por qué (trazabilidad; suele venir de self_improvement)
    # kind="prompt":
    "target": None,          # ruta relativa al prompt (bajo agents/, .md)
    "content": None,         # nuevo contenido
    "mode": "replace",       # "replace" | "append"
    # kind="registry_field":
    "agent_id": None,
    "field": None,
    "value": None,
}


def normalize_factory_change(raw: dict) -> dict:
    """Completa una propuesta parcial con los defaults del schema del cambio."""
    out = {k: (v.copy() if isinstance(v, (list, dict)) else v) for k, v in _CHANGE_DEFAULTS.items()}
    for k, v in raw.items():
        if k in out:
            out[k] = v
    return out


def _is_protected_path(target: str) -> bool:
    """True si la ruta cae en la deny-list (prefijo, archivo exacto, o escape de árbol)."""
    t = (target or "").replace("\\", "/").strip()
    if not t:
        return True
    if t.startswith("/") or ".." in t.split("/"):
        return True  # rutas absolutas o con escape → bloqueadas
    if t in PROTECTED_PATHS:
        return True
    return any(t.startswith(pref) for pref in PROTECTED_PATH_PREFIXES)


def is_protected_target(change: dict) -> bool:
    """True si el cambio apunta a un objetivo protegido (no aplicable)."""
    kind = change.get("kind")
    if kind == "prompt":
        return _is_protected_path(str(change.get("target") or ""))
    if kind == "registry_field":
        return str(change.get("agent_id") or "") in PROTECTED_AGENT_IDS
    return True  # kind desconocido → tratar como protegido (fail-safe)


def validate_factory_change(change: dict) -> list[str]:
    """
    Valida una propuesta de cambio. Devuelve lista de errores (vacía = válida).
    No lanza: pensada para feedback al fundador antes de aplicar.
    """
    errors: list[str] = []
    kind = change.get("kind")
    if kind not in VALID_KINDS:
        errors.append(f"'kind' debe ser uno de {VALID_KINDS} (recibido: {kind!r})")
        return errors

    if kind == "prompt":
        target = str(change.get("target") or "")
        if not target:
            errors.append("kind=prompt requiere 'target' (ruta del prompt)")
        else:
            if not target.replace("\\", "/").startswith("agents/"):
                errors.append("kind=prompt: 'target' debe estar bajo 'agents/'")
            if not target.endswith(".md"):
                errors.append("kind=prompt: 'target' debe ser un archivo .md")
            if _is_protected_path(target):
                errors.append(f"kind=prompt: 'target' '{target}' es un objetivo protegido")
        mode = change.get("mode")
        if mode not in ("replace", "append"):
            errors.append("kind=prompt: 'mode' debe ser 'replace' o 'append'")
        content = change.get("content")
        if not isinstance(content, str) or not content.strip():
            errors.append("kind=prompt: 'content' debe ser un string no vacío")

    elif kind == "registry_field":
        agent_id = str(change.get("agent_id") or "")
        field = change.get("field")
        if not agent_id:
            errors.append("kind=registry_field requiere 'agent_id'")
        elif agent_id in PROTECTED_AGENT_IDS:
            errors.append(f"agente '{agent_id}' es un revisor de seguridad protegido")
        if field in IMMUTABLE_REGISTRY_FIELDS:
            errors.append(f"campo '{field}' es estructural e inmutable (cablea el grafo)")
        elif field not in MODIFIABLE_REGISTRY_FIELDS:
            errors.append(f"campo '{field}' no es modificable por el factory_modifier")
        if isinstance(change.get("value"), str) and change["value"] in PROTECTED_FLAGS:
            errors.append("no se permite referenciar flags protegidos como valor")

    return errors


def _default_llm(request: str) -> str:
    """LLM real por defecto. No se usa en tests (se inyecta un mock)."""
    from nodes.base import _openai_client
    from config import GLOBAL_DEFAULT_MODEL
    client = _openai_client("google")
    sys = (
        "Eres un Factory Modifier. Dada una petición de modificar la PROPIA fábrica, devuelve "
        "SOLO un objeto JSON con un cambio ACOTADO: kind ('prompt' o 'registry_field'), "
        "rationale, y los campos del kind (prompt: target .md bajo agents/, content, mode "
        "'replace'|'append'; registry_field: agent_id, field, value). Nada fuera del JSON. "
        "NUNCA propongas tocar config.py, .github/, el grafo, ni los revisores A8/A8.5."
    )
    resp = client.chat.completions.create(
        model=GLOBAL_DEFAULT_MODEL,
        messages=[{"role": "system", "content": sys}, {"role": "user", "content": request}],
        max_tokens=900,
    )
    return resp.choices[0].message.content or ""


def build_factory_change(request: str, llm: Optional[Callable[[str], object]] = None) -> dict:
    """
    Genera (vía LLM inyectable) y normaliza una propuesta candidata. NO la aplica.
    `llm` recibe el texto de la petición y devuelve un dict o un str JSON.
    """
    raw = (llm or _default_llm)(request)
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ValueError(f"el LLM no devolvió JSON válido: {exc}") from exc
    if not isinstance(raw, dict):
        raise ValueError(f"propuesta de cambio inesperada (se esperaba dict): {type(raw)}")
    return normalize_factory_change(raw)


def plan_factory_change(change: dict, branch: str = "") -> str:
    """Reporte legible del cambio propuesto (qué, dónde, y la garantía de ruteo por PR)."""
    errors = validate_factory_change(change)
    lines = ["=== Factory Modifier — plan de cambio ==="]
    kind = change.get("kind")
    if kind == "prompt":
        lines.append(f"Tipo: prompt ({change.get('mode')}) → {change.get('target')}")
    elif kind == "registry_field":
        lines.append(f"Tipo: registry_field → agente {change.get('agent_id')} "
                     f"campo '{change.get('field')}' = {change.get('value')!r}")
    else:
        lines.append(f"Tipo: {kind!r} (no reconocido)")
    if change.get("rationale"):
        lines.append(f"Motivo: {change['rationale']}")
    lines.append(f"Rama destino: {branch or '(requerida — nunca main/master)'}")
    lines.append("Ruteo: se aplica en rama y entra por PR (revisor independiente + CI).")
    lines.append("Estado: " + ("VÁLIDO" if not errors else "BLOQUEADO — " + "; ".join(errors)))
    return "\n".join(lines)


def apply_factory_change(
    change: dict,
    *,
    approved: bool,
    branch: str,
    repo_root: Optional[Path] = None,
    registry_path: Optional[Path] = None,
) -> dict:
    """
    Aplica el cambio SOLO si: `config.FACTORY_MODIFIER_ENABLED` activo, `approved=True`,
    el cambio es válido, NO apunta a un objetivo protegido y `branch` NO es main/master.
    Escribe en disco (prompt o registry) y devuelve un registro del cambio. Si no, lanza.

    NO hace operaciones de git: el llamador es responsable de que `branch` sea una rama de
    trabajo real y de abrir el PR. El gate de `branch` aquí es la barrera determinista que
    impide escribir conceptualmente "sobre main".
    """
    import config
    if not getattr(config, "FACTORY_MODIFIER_ENABLED", False):
        raise PermissionError("FACTORY_MODIFIER_ENABLED está desactivado; modificación bloqueada.")
    if not approved:
        raise PermissionError("la modificación requiere aprobación explícita del fundador (approved=True).")
    if not branch or branch in PROTECTED_BRANCHES:
        raise PermissionError(
            f"factory_modifier nunca escribe sobre {sorted(PROTECTED_BRANCHES)}; "
            "se requiere una rama de trabajo (el cambio entra por PR)."
        )

    errors = validate_factory_change(change)
    if errors:
        raise ValueError("cambio inválido: " + "; ".join(errors))
    if is_protected_target(change):
        raise PermissionError("el cambio apunta a un objetivo protegido; bloqueado.")

    root = Path(repo_root) if repo_root else Path.cwd()
    kind = change["kind"]

    if kind == "prompt":
        target_path = (root / change["target"]).resolve()
        # Defensa adicional: el path resuelto debe quedar dentro de root/agents.
        agents_root = (root / "agents").resolve()
        if agents_root not in target_path.parents and target_path != agents_root:
            raise PermissionError("ruta de prompt fuera de 'agents/'; bloqueado.")
        target_path.parent.mkdir(parents=True, exist_ok=True)
        if change["mode"] == "append" and target_path.exists():
            prev = target_path.read_text(encoding="utf-8")
            new = prev + ("" if prev.endswith("\n") else "\n") + change["content"]
        else:
            new = change["content"]
        target_path.write_text(new, encoding="utf-8")
        logger.info("Factory Modifier (%s) escribió el prompt %s en la rama %s",
                    change["mode"], change["target"], branch)
        return {"applied": True, "kind": kind, "target": change["target"],
                "mode": change["mode"], "branch": branch}

    # kind == "registry_field"
    if registry_path is None:
        from tools import agent_registry as _ar
        registry_path = _ar._registry_path()
    registry_path = Path(registry_path)
    data = json.loads(registry_path.read_text(encoding="utf-8"))
    agent = next((a for a in data.get("agents", []) if a.get("id") == change["agent_id"]), None)
    if agent is None:
        raise ValueError(f"agente '{change['agent_id']}' no existe en el registry")
    old_value = agent.get(change["field"])
    agent[change["field"]] = change["value"]
    registry_path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    try:
        from tools import agent_registry as _ar
        _ar.clear_cache()
    except (ImportError, AttributeError) as exc:
        logger.debug("no se pudo limpiar el cache del registry tras el cambio: %s", exc)
    logger.info("Factory Modifier cambió %s.%s de %r a %r en la rama %s",
                change["agent_id"], change["field"], old_value, change["value"], branch)
    return {"applied": True, "kind": kind, "agent_id": change["agent_id"],
            "field": change["field"], "old_value": old_value, "value": change["value"],
            "branch": branch}
