"""
tools/conversational_builder.py — Constructor CONVERSACIONAL de pipelines (meta-capa).

Función del meta-agente: el usuario explica en lenguaje natural lo que quiere y el agente va
construyendo el pipeline y cada nodo a lo largo del diálogo. Cuando tiene suficiente
información, emite un DRAFT estructurado (pipeline + agentes) que se valida y, con aprobación
explícita + flags activos, se registra reutilizando agent_builder/pipeline_builder.

Diseño:
  - converse(history, message, llm=None) → {reply, draft, errors, ready}. El LLM es inyectable
    (mockeable en tests), igual que en agent_builder/pipeline_builder.
  - El agente responde en prosa y, cuando está listo, incluye un bloque ```json con el draft.
    Cada agente del draft trae además su `system_prompt`: la LÓGICA del nodo (instrucciones
    detalladas), no solo su definición. Así el pipeline nuevo arranca con calidad dedicada en
    vez de depender del prompt genérico del runtime.
  - register_draft(draft, approved=...) persiste el `system_prompt` de cada agente como un
    `prompt_file` (pipelines/<name>/prompts/<ID>.md) que el runtime genérico ya sabe leer, y
    registra agentes + pipeline con los gates de cada tool (AGENT_BUILDER_ENABLED /
    PIPELINE_BUILDER_ENABLED + approved). Sin gate → lanza, sin escribir nada a disco.
"""
from __future__ import annotations

import json
import logging
import re
from pathlib import Path
from typing import Callable, Optional

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = (
    "Eres un Arquitecto de Pipelines conversacional. Tu trabajo es ayudar al usuario a diseñar "
    "un pipeline de agentes (un dominio nuevo de la fábrica) preguntando lo necesario y luego "
    "proponiendo cada nodo CON SU LÓGICA, no solo su nombre.\n\n"
    "Conversa en español, breve y concreto. Haz preguntas de aclaración hasta entender: objetivo "
    "del pipeline, etapas (agentes) y qué hace cada uno.\n\n"
    "Cuando tengas suficiente información, incluye al FINAL de tu mensaje un bloque ```json con "
    "EXACTAMENTE esta forma:\n"
    "```json\n"
    '{\n'
    '  "pipeline": {"name": "<slug_minusculas>", "description": "<desc>", "entry": "<ID_primer_agente>",\n'
    '               "agents": ["ID1","ID2",...], "default_model": null},\n'
    '  "agents": [{"id": "ID1", "role": "<rol>", "pipeline": "<mismo name>", "uses_llm": true,\n'
    '              "output_schema": null,\n'
    '              "system_prompt": "<instrucciones detalladas del nodo>"}, ...]\n'
    '}\n'
    "```\n"
    "Los IDs en MAYÚSCULAS y únicos. El name del pipeline en minúsculas sin espacios.\n\n"
    "El `system_prompt` de CADA agente es lo más importante: escribe el prompt de sistema real "
    "que regirá ese nodo (varias frases). Define su objetivo, qué recibe (el brief y las salidas "
    "de los agentes previos), cómo debe razonar, el formato de salida y los criterios de calidad. "
    "Redáctalo en segunda persona ('Eres el agente de…'). No incluyas el bloque json hasta que el "
    "diseño esté completo."
)


def _default_llm(messages: list[dict]) -> str:
    """LLM real por defecto (OpenAI-compat/Google). No se usa en tests (se inyecta mock)."""
    from nodes.base import _openai_client
    from config import GLOBAL_DEFAULT_MODEL
    client = _openai_client("google")
    resp = client.chat.completions.create(
        model=GLOBAL_DEFAULT_MODEL, messages=messages, max_tokens=1200,
    )
    return resp.choices[0].message.content or ""


_JSON_BLOCK = re.compile(r"```json\s*(\{.*?\})\s*```", re.DOTALL)


def _extract_draft(text: str) -> tuple[Optional[dict], list[str]]:
    """Busca el bloque ```json del draft, lo parsea y valida. Devuelve (draft|None, errores)."""
    m = _JSON_BLOCK.search(text or "")
    if not m:
        return None, []
    try:
        raw = json.loads(m.group(1))
    except json.JSONDecodeError as exc:
        logger.debug("draft conversacional con json inválido: %s", exc)
        return None, [f"el bloque json no es válido: {exc}"]
    if not isinstance(raw, dict) or "pipeline" not in raw or "agents" not in raw:
        return None, ["el draft debe tener 'pipeline' y 'agents'"]

    from tools.agent_builder import normalize_agent_definition, validate_agent_definition
    from tools.pipeline_builder import normalize_pipeline_definition, validate_pipeline_definition

    agents = [normalize_agent_definition(a) for a in raw.get("agents", [])]
    pipeline = normalize_pipeline_definition(raw.get("pipeline", {}))
    draft = {"pipeline": pipeline, "agents": agents}

    errors: list[str] = []
    seen_ids: set[str] = set()
    for a in agents:
        errors += [f"agente {a.get('id')}: {e}" for e in validate_agent_definition(a, seen_ids)]
        if a.get("id"):
            seen_ids.add(a["id"])
    errors += [f"pipeline: {e}" for e in validate_pipeline_definition(pipeline)]
    return draft, errors


def converse(history: list[dict], message: str,
             llm: Optional[Callable[[list], object]] = None) -> dict:
    """
    Avanza el diálogo. `history` es una lista [{role, content}] (sin el system). Devuelve:
      {reply, draft, errors, ready}. `ready` es True cuando hay un draft parseado.
    """
    messages = [{"role": "system", "content": SYSTEM_PROMPT}]
    for h in history or []:
        if h.get("role") in ("user", "assistant") and h.get("content"):
            messages.append({"role": h["role"], "content": h["content"]})
    messages.append({"role": "user", "content": message})

    text = (llm or _default_llm)(messages)
    if not isinstance(text, str):
        text = str(text)
    draft, errors = _extract_draft(text)
    return {"reply": text, "draft": draft, "errors": errors, "ready": draft is not None and not errors}


def _persist_prompt(pipelines_dir: Path, pipeline_name: str, agent_id: str,
                    system_prompt: str) -> str:
    """
    Escribe la lógica (system prompt) de un nodo en `pipelines/<name>/prompts/<ID>.md` y
    devuelve la ruta RELATIVA a FABRICA_DIR que el runtime genérico (`_read_prompt`) lee.
    """
    target = Path(pipelines_dir) / pipeline_name / "prompts" / f"{agent_id}.md"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(system_prompt.strip() + "\n", encoding="utf-8")
    return str(Path("pipelines") / pipeline_name / "prompts" / f"{agent_id}.md")


def register_draft(draft: dict, *, approved: bool,
                   registry_path: Optional[Path] = None,
                   pipelines_dir: Optional[Path] = None) -> dict:
    """
    Persiste la lógica de cada nodo (system_prompt → prompt_file) y registra los agentes y el
    pipeline del draft, reutilizando los gates de cada tool (flags + approved). Registra agentes
    primero para que la validación del pipeline los encuentre. Lanza PermissionError/ValueError
    si algún gate falla o algo es inválido — comprobando los gates ANTES de escribir prompts a
    disco para no dejar artefactos huérfanos.
    """
    import config
    if not getattr(config, "AGENT_BUILDER_ENABLED", False):
        raise PermissionError("AGENT_BUILDER_ENABLED está desactivado; registro bloqueado.")
    if not getattr(config, "PIPELINE_BUILDER_ENABLED", False):
        raise PermissionError("PIPELINE_BUILDER_ENABLED está desactivado; registro bloqueado.")
    if not approved:
        raise PermissionError("registro requiere aprobación explícita del fundador (approved=True).")

    from tools.agent_builder import register_agent
    from tools.pipeline_builder import register_pipeline

    if pipelines_dir is None:
        from tools.pipeline_loader import _pipelines_dir
        pipelines_dir = _pipelines_dir()

    pipeline_name = draft["pipeline"].get("name")
    results: dict = {"agents": [], "pipeline": None, "prompts": []}
    for raw_agent in draft.get("agents", []):
        agent = dict(raw_agent)
        system_prompt = agent.pop("system_prompt", None)
        if system_prompt and str(system_prompt).strip():
            agent["prompt_file"] = _persist_prompt(
                pipelines_dir, pipeline_name, agent["id"], str(system_prompt))
            results["prompts"].append(agent["prompt_file"])
        register_agent(agent, approved=approved, registry_path=registry_path)
        results["agents"].append(agent.get("id"))
    path = register_pipeline(draft["pipeline"], approved=approved, base_dir=pipelines_dir)
    results["pipeline"] = str(path)
    logger.info("Constructor conversacional registró pipeline '%s' con %d agentes y %d prompts",
                pipeline_name, len(results["agents"]), len(results["prompts"]))
    return results
