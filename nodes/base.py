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
    if m.startswith("claude-"):                           return "anthropic"
    if m.startswith("gemini-"):                           return "google"
    if m.startswith("glm-") or m.startswith("chatglm"):  return "zhipu"
    if m.startswith("kimi-") or m.startswith("moonshot-"): return "kimi"
    return "anthropic"


from functools import lru_cache

_PROVIDER_KEYS = {
    "google": lambda: GOOGLE_API_KEY,
    "zhipu":  lambda: ZHIPU_API_KEY,
    "kimi":   lambda: KIMI_API_KEY,
}


@lru_cache(maxsize=1)
def _anthropic_client():
    from anthropic import Anthropic
    return Anthropic(api_key=ANTHROPIC_API_KEY)


@lru_cache(maxsize=4)
def _openai_client(provider: str):
    from openai import OpenAI
    return OpenAI(base_url=PROVIDER_URLS[provider], api_key=_PROVIDER_KEYS[provider]())


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
    text = response.content[0].text
    cost_entry = make_cost_entry(agent_label, model, response.usage)
    logger.info(
        "%s OK — %d in / %d out / %d cache → $%.4f",
        agent_label, response.usage.input_tokens, response.usage.output_tokens,
        getattr(response.usage, "cache_read_input_tokens", 0), cost_entry["cost_usd"],
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

    if USE_OPENCLAW:
        logger.info("→ %s [OpenClaw] | repo: %s", agent_label, repo_path or "—")
        return _call_openclaw(
            agent_key=agent_key, agent_label=agent_label, model=model,
            static_keys=[], extra_context=resolved_extra, task_content=task_content,
        )

    provider = _provider(model)
    logger.info("→ %s [directo] | modelo: %s | repo: %s", agent_label, model, repo_path or "—")

    kwargs = dict(
        agent_key=agent_key, agent_label=agent_label, model=model,
        static_keys=[], extra_context=resolved_extra, task_content=task_content,
    )
    if provider == "anthropic":
        return _call_anthropic(**kwargs)
    return _call_openai_compat(provider=provider, **kwargs)
