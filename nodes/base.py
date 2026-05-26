"""
Router multi-proveedor para todos los agentes.

Modo OpenClaw (USE_OPENCLAW=true):
  Cada agente corre dentro de OpenClaw, con acceso real al sistema de archivos,
  terminal y herramientas. Los LLMs configurados en openclaw.json actúan como cerebro.

Modo directo (USE_OPENCLAW=false o no configurado):
  Llamada directa a la API del proveedor — sin acceso a herramientas reales.
  - Anthropic (claude-*): prompt caching nativo (90% descuento en cache hits)
  - Google / Z.ai / Kimi: OpenAI-compatible API
"""
from __future__ import annotations
import asyncio
import logging
import os

from config import (
    MODEL_STANDARD,
    ANTHROPIC_API_KEY, GOOGLE_API_KEY, ZHIPU_API_KEY, KIMI_API_KEY,
    PROVIDER_URLS,
)
from state import CostEntry
from tools.file_tools import read_static, read_system_prompt
from tools.cost_tracker import make_cost_entry

logger = logging.getLogger(__name__)

_STATIC_KEYS = ["project_context", "coding_standards", "decision_log"]

# ── Modo de operación ─────────────────────────────────────────────────────────
USE_OPENCLAW = os.getenv("USE_OPENCLAW", "false").lower() == "true"


# ══════════════════════════════════════════════════════════════════════════════
# MODO OPENCLAW — agentes con herramientas reales
# ══════════════════════════════════════════════════════════════════════════════

def _build_openclaw_task(
    agent_key: str,
    task_content: str,
    static_keys: list[str],
    extra_context: dict[str, str] | None,
) -> str:
    """Construye el mensaje completo que se envía al agente OpenClaw."""
    parts = []

    for key in static_keys:
        try:
            parts.append(f"## {key.upper().replace('_', ' ')}\n\n{read_static(key)}")
        except FileNotFoundError:
            pass

    if extra_context:
        for label, content in extra_context.items():
            parts.append(f"## {label}\n\n{content}")

    parts.append(f"## TU TAREA\n\n{task_content}")
    return "\n\n---\n\n".join(parts)


def _call_openclaw(
    *,
    agent_key: str,
    agent_label: str,
    model: str,
    static_keys: list[str],
    extra_context: dict[str, str] | None,
    task_content: str,
) -> tuple[str, CostEntry]:
    from openclaw.client import run_agent_with_retry

    task = _build_openclaw_task(agent_key, task_content, static_keys, extra_context)
    text = asyncio.run(run_agent_with_retry(agent_key, task))

    # OpenClaw no expone conteo de tokens directamente — estimamos basado en caracteres
    # (hasta que la API de OpenClaw lo soporte explícitamente)
    estimated_input  = len(task)  // 4   # ~4 chars por token
    estimated_output = len(text)  // 4
    cost_entry = make_cost_entry(
        agent_label, model,
        _FakeUsage(estimated_input, estimated_output),
    )

    logger.info(
        "%s [OpenClaw] OK — ~%d tok in / ~%d tok out → $%.4f (estimado)",
        agent_label, estimated_input, estimated_output, cost_entry["cost_usd"],
    )
    return text, cost_entry


class _FakeUsage:
    """Objeto Usage mínimo compatible con make_cost_entry()."""
    def __init__(self, input_tokens: int, output_tokens: int):
        self.input_tokens  = input_tokens
        self.output_tokens = output_tokens
        self.cache_read_input_tokens = 0


# ══════════════════════════════════════════════════════════════════════════════
# MODO DIRECTO — llamadas a la API sin herramientas
# ══════════════════════════════════════════════════════════════════════════════

def _provider(model: str) -> str:
    m = model.lower()
    if m.startswith("claude-"):                              return "anthropic"
    if m.startswith("gemini-3.5-"):                         return "google-native"  # SDK nativo
    if m.startswith("gemini-"):                             return "google"          # OpenAI-compat
    if m.startswith("glm-") or m.startswith("chatglm"):    return "zhipu"
    if m.startswith("kimi-") or m.startswith("moonshot-"): return "kimi"
    return "anthropic"


_PROVIDER_KEY_NAMES = {
    "google": "GOOGLE_API_KEY",
    "zhipu":  "ZHIPU_API_KEY",
    "kimi":   "KIMI_API_KEY",
}


def _anthropic_client():
    """A-07: lee la key en cada llamada para capturar cambios de config en runtime."""
    import os as _os
    from anthropic import Anthropic
    import httpx as _httpx
    return Anthropic(
        api_key=_os.getenv("ANTHROPIC_API_KEY", ANTHROPIC_API_KEY),
        timeout=_httpx.Timeout(300.0, connect=15.0),   # A-10: 5 min máximo por llamada
    )


def _openai_client(provider: str):
    """A-07: sin lru_cache — lee la key fresca en cada llamada."""
    import os as _os
    from openai import OpenAI
    key = _os.getenv(_PROVIDER_KEY_NAMES.get(provider, ""), "")
    return OpenAI(
        base_url=PROVIDER_URLS[provider],
        api_key=key,
        timeout=300.0,   # A-10: 5 min máximo
    )


def _call_anthropic(*, agent_key, agent_label, model, static_keys, extra_context, task_content):
    from anthropic.types import TextBlockParam
    client = _anthropic_client()
    system_prompt = read_system_prompt(agent_key)

    user_content: list[TextBlockParam] = []
    for key in static_keys:
        try:
            user_content.append({
                "type": "text",
                "text": f"## {key.upper().replace('_', ' ')}\n\n{read_static(key)}",
                "cache_control": {"type": "ephemeral"},
            })
        except FileNotFoundError as exc:
            logger.warning("Doc estático no encontrado: %s", exc)

    if extra_context:
        for label, content in extra_context.items():
            user_content.append({"type": "text", "text": f"## {label}\n\n{content}"})
    user_content.append({"type": "text", "text": f"## TU TAREA\n\n{task_content}"})

    response = client.messages.create(
        model=model, max_tokens=8192, system=system_prompt,
        messages=[{"role": "user", "content": user_content}],
        extra_headers={"anthropic-beta": "prompt-caching-2024-07-31"},
    )
    # M-03: acceso seguro en caso de respuesta sin bloques de texto
    text = next((b.text for b in response.content if hasattr(b, "text") and b.text), "")
    cost_entry = make_cost_entry(agent_label, model, response.usage)
    logger.info(
        "%s OK — %d in / %d out / %d cache → $%.4f",
        agent_label, response.usage.input_tokens, response.usage.output_tokens,
        getattr(response.usage, "cache_read_input_tokens", 0), cost_entry["cost_usd"],
    )
    return text, cost_entry


def _call_google_native(*, agent_key, agent_label, model, static_keys, extra_context, task_content):
    """
    Llama a Gemini 3.5+ via SDK nativo google-genai.
    Habilita Thinking (MEDIUM) para razonamiento más profundo en A0/A1.
    Fallback a OpenAI-compat si el SDK no está disponible.
    """
    try:
        from google import genai as gai
        from google.genai import types as gtypes
    except ImportError:
        logger.warning("google-genai no instalado — usando fallback OpenAI-compat para %s", model)
        return _call_openai_compat(
            provider="google", agent_key=agent_key, agent_label=agent_label,
            model=model, static_keys=static_keys, extra_context=extra_context,
            task_content=task_content,
        )

    client = gai.Client(api_key=GOOGLE_API_KEY)
    system_prompt = read_system_prompt(agent_key)

    # Armar bloque de usuario: contexto estático + extra + tarea
    parts: list[str] = []
    for key in static_keys:
        try:
            parts.append(f"## {key.upper().replace('_', ' ')}\n\n{read_static(key)}")
        except FileNotFoundError:
            pass
    if extra_context:
        for label, content in extra_context.items():
            parts.append(f"## {label}\n\n{content}")
    parts.append(f"## TU TAREA\n\n{task_content}")

    contents = [
        gtypes.Content(
            role="user",
            parts=[gtypes.Part.from_text(text="\n\n---\n\n".join(parts))],
        )
    ]

    gen_cfg = gtypes.GenerateContentConfig(
        system_instruction=system_prompt or None,
        thinking_config=gtypes.ThinkingConfig(thinking_level="MEDIUM"),
        max_output_tokens=8192,
    )

    response = client.models.generate_content(
        model=model,
        contents=contents,
        config=gen_cfg,
    )

    text = response.text or ""
    usage = response.usage_metadata
    input_tokens  = getattr(usage, "prompt_token_count",     0) or 0
    output_tokens = getattr(usage, "candidates_token_count", 0) or 0
    thoughts_tok  = getattr(usage, "thoughts_token_count",   0) or 0

    cost_entry = make_cost_entry(agent_label, model, _FakeUsage(input_tokens, output_tokens))
    logger.info(
        "%s [Gemini Native] OK — %d in / %d out / %d thoughts → $%.4f",
        agent_label, input_tokens, output_tokens, thoughts_tok, cost_entry["cost_usd"],
    )
    return text, cost_entry


def _call_openai_compat(*, provider, agent_key, agent_label, model, static_keys, extra_context, task_content):
    client = _openai_client(provider)
    system_prompt = read_system_prompt(agent_key)

    parts = []
    for key in static_keys:
        try:
            parts.append(f"## {key.upper().replace('_', ' ')}\n\n{read_static(key)}")
        except FileNotFoundError:
            pass
    if extra_context:
        for label, content in extra_context.items():
            parts.append(f"## {label}\n\n{content}")
    parts.append(f"## TU TAREA\n\n{task_content}")

    response = client.chat.completions.create(
        model=model, max_tokens=8192,
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user",   "content": "\n\n---\n\n".join(parts)},
        ],
    )
    text = response.choices[0].message.content or ""
    cost_entry = make_cost_entry(agent_label, model, response.usage)
    logger.info(
        "%s OK — %d in / %d out → $%.4f",
        agent_label, response.usage.prompt_tokens,
        response.usage.completion_tokens, cost_entry["cost_usd"],
    )
    return text, cost_entry


# ══════════════════════════════════════════════════════════════════════════════
# ROUTER PRINCIPAL
# ══════════════════════════════════════════════════════════════════════════════

def call_agent(
    *,
    agent_key: str,
    agent_label: str,
    task_content: str,
    model: str = MODEL_STANDARD,
    include_static: list[str] | None = None,
    extra_context: dict[str, str] | None = None,
    repo_path: str | None = None,
    feature_id: str | None = None,   # VII-2: para emitir eventos de observabilidad
) -> tuple[str, CostEntry]:
    static_keys = include_static if include_static is not None else _STATIC_KEYS

    # Inyectar docs del repo destino en el contexto estático
    from tools.file_tools import read_static
    resolved_extra: dict[str, str] = {}
    for key in static_keys:
        text = read_static(key, repo_path=repo_path)
        if text:
            resolved_extra[key.upper().replace("_", " ")] = text
    if extra_context:
        resolved_extra.update(extra_context)

    # ── Inyectar skills del proyecto ──────────────────────────────────────────
    if repo_path:
        try:
            from tools.skill_tools import list_skills, select_skills_for_task, build_skills_context
            skills = list_skills(repo_path)
            if skills:
                relevant = select_skills_for_task(skills, task_content)
                if relevant:
                    skills_block = build_skills_context(relevant)
                    resolved_extra["SKILLS DEL PROYECTO"] = skills_block
                    logger.debug(
                        "%s: inyectando %d skills: %s",
                        agent_label, len(relevant), [s["name"] for s in relevant],
                    )
        except Exception as _skill_exc:
            logger.warning("Error al cargar skills del proyecto: %s", _skill_exc)

    # VII-2: señal de inicio al event bus (best-effort, nunca bloquea el pipeline)
    # feature_id puede venir como parámetro o del env var que el CLI inyecta
    _fid = feature_id or os.getenv("FEATURE_ID_OVERRIDE", "")

    # VIII-1: Verificar intervención del Founder antes de llamar al LLM
    if _fid:
        try:
            from tools.event_bus import pop_intervention
            _intervention = pop_intervention(_fid)
            if _intervention:
                task_content = (
                    "⚡ INSTRUCCIÓN CORRECTIVA DEL FOUNDER (máxima prioridad):\n"
                    "---\n"
                    f"{_intervention}\n"
                    "---\n\n"
                    + task_content
                )
                logger.info(
                    "%s: intervención del Founder inyectada (%d chars)",
                    agent_label, len(_intervention),
                )
        except Exception:
            pass

    if _fid:
        try:
            from tools.event_bus import emit
            emit(_fid, agent_label, "start", model=model)
        except Exception:
            pass

    if USE_OPENCLAW:
        logger.info("→ %s [OpenClaw] | repo: %s", agent_label, repo_path or "—")
        text, cost_entry = _call_openclaw(
            agent_key=agent_key, agent_label=agent_label, model=model,
            static_keys=[], extra_context=resolved_extra, task_content=task_content,
        )
    else:
        provider = _provider(model)
        logger.info("→ %s [directo] | modelo: %s | repo: %s", agent_label, model, repo_path or "—")

        kwargs = dict(
            agent_key=agent_key, agent_label=agent_label, model=model,
            static_keys=[], extra_context=resolved_extra, task_content=task_content,
        )
        if provider == "anthropic":
            text, cost_entry = _call_anthropic(**kwargs)
        elif provider == "google-native":
            text, cost_entry = _call_google_native(**kwargs)
        else:
            text, cost_entry = _call_openai_compat(provider=provider, **kwargs)

    # VII-2: señal de fin con métricas reales
    if _fid:
        try:
            from tools.event_bus import emit
            emit(
                _fid, agent_label, "end",
                model=model,
                tokens_in=cost_entry.get("input_tokens", 0),
                tokens_out=cost_entry.get("output_tokens", 0),
                cost_usd=cost_entry.get("cost_usd", 0.0),
            )
        except Exception:
            pass

    return text, cost_entry
