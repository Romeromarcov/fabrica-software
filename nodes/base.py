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
    ANTHROPIC_API_KEY, GOOGLE_API_KEY, ZHIPU_API_KEY, KIMI_API_KEY, OPENAI_API_KEY,
    PROVIDER_URLS, CUSTOM_PROVIDERS,
)
from state import CostEntry
from tools.file_tools import read_static, read_system_prompt
from tools.cost_tracker import make_cost_entry
from tools.llm_retry import retry_sync

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
    if m.startswith("gpt-") or m.startswith("o1") or m.startswith("o3"): return "openai"
    if m.startswith("nvidia/") or "nemotron" in m:        return "nvidia"   # build.nvidia.com
    # Custom providers: check if model is listed in any custom provider
    for cp in CUSTOM_PROVIDERS:
        if model in (cp.get("models") or []):
            return "cp_" + (cp.get("api_key_var") or "CUSTOM_API_KEY")
    return "anthropic"


_PROVIDER_KEY_NAMES = {
    "openai": "OPENAI_API_KEY",
    "google": "GOOGLE_API_KEY",
    "zhipu":  "ZHIPU_API_KEY",
    "kimi":   "KIMI_API_KEY",
    "nvidia": "NVIDIA_API_KEY",
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
    if provider.startswith("cp_"):
        # Custom provider: api_key_var = provider[3:]
        key = _os.getenv(provider[3:], "")
    else:
        key = _os.getenv(_PROVIDER_KEY_NAMES.get(provider, ""), "")
    return OpenAI(
        base_url=PROVIDER_URLS.get(provider, "https://api.openai.com/v1"),
        api_key=key or "no-key",
        timeout=300.0,
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

    # ── Inyectar skills (globales de la fábrica + del proyecto) ────────────────
    try:
        from tools.skill_tools import all_skills_for, select_skills_for_task, build_skills_context
        skills = all_skills_for(repo_path)
        if skills:
            relevant = select_skills_for_task(skills, task_content)
            if relevant:
                skills_block = build_skills_context(relevant)
                resolved_extra["SKILLS DEL PROYECTO"] = skills_block
                logger.debug(
                    "%s: inyectando %d skills (global+repo): %s",
                    agent_label, len(relevant), [s["name"] for s in relevant],
                )
    except Exception as _skill_exc:
        logger.warning("Error al cargar skills: %s", _skill_exc)

    # VII-2: señal de inicio al event bus (best-effort, nunca bloquea el pipeline)
    # feature_id puede venir como parámetro o del env var que el CLI inyecta
    _fid = feature_id or os.getenv("FEATURE_ID_OVERRIDE", "")

    # E1.1: fijar el trace_id de la traza para que todos los logs de este feature
    # compartan el mismo identificador de correlación (barato, sin cambio de comportamiento).
    if _fid:
        try:
            from tools.trace import set_trace_id, new_trace_id
            set_trace_id(new_trace_id(_fid))
        except ImportError:
            pass

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

    # M6 (PLAN_PLATAFORMA_V2): A/B testing de modelos. En AB_TESTING_PCT de los features,
    # el agente usa su modelo alternativo (model_fallbacks del registry). Opt-in; no-op si
    # el flag está off o el agente no tiene alternativas declaradas.
    try:
        from config import AB_TESTING_ENABLED, AB_TESTING_PCT
        if AB_TESTING_ENABLED and _fid:
            from tools.agent_registry import all_agents
            from tools.ab_testing import choose_model
            _match = next((a for a in all_agents() if a.get("agent_key") == agent_key), None)
            if _match and _match.get("model_fallbacks"):
                model, _ab_variant = choose_model(
                    _fid, _match["id"], model, _match["model_fallbacks"], AB_TESTING_PCT,
                )
                if _ab_variant:
                    logger.info("%s: A/B testing → modelo variante %s", agent_label, model)
    except Exception as _ab_exc:
        logger.warning("A/B testing de modelos falló (ignorado): %s", _ab_exc)

    # R2 (PLAN_PLATAFORMA_V2): hook pre_agent. Sin hooks registrados es no-op
    # (comportamiento idéntico). Un hook puede devolver `model`/`task_content`
    # para influir en la llamada (opt-in, gobernado por quien lo registra).
    try:
        from tools.hook_engine import run_hooks
        _pre = run_hooks("pre_agent", {
            "agent_key": agent_key, "agent_label": agent_label,
            "model": model, "task_content": task_content,
            "feature_id": _fid, "repo_path": repo_path,
        })
        model = _pre.get("model", model)
        task_content = _pre.get("task_content", task_content)
    except Exception as _hook_exc:
        logger.warning("hook pre_agent falló (ignorado): %s", _hook_exc)

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

        # E2.1 (path directo): reintento de errores transitorios (429 + 5xx +
        # conexión/timeout). Antes la ruta directa NO reintentaba, así que un único
        # 503 UNAVAILABLE transitorio del proveedor mataba al agente.
        def _dispatch():
            if provider == "anthropic":
                return _call_anthropic(**kwargs)
            elif provider == "google-native":
                return _call_google_native(**kwargs)
            return _call_openai_compat(provider=provider, **kwargs)

        # M5 (PLAN_PLATAFORMA_V2): caché local para proveedores SIN caché nativa.
        # Anthropic ya cachea → se salta. Opt-in; default off → comportamiento idéntico.
        _cache_key = None
        try:
            from config import SEMANTIC_CACHE_ENABLED, SEMANTIC_CACHE_TTL_SECONDS
            if SEMANTIC_CACHE_ENABLED and provider != "anthropic":
                from tools import prompt_cache
                _ctx_blob = "".join(f"{k}={v}" for k, v in sorted(resolved_extra.items()))
                _cache_key = prompt_cache.make_key(
                    model, read_system_prompt(agent_key), task_content, _ctx_blob,
                )
                _hit = prompt_cache.get(_cache_key, ttl_seconds=SEMANTIC_CACHE_TTL_SECONDS)
            else:
                _hit = None
        except Exception as _cache_exc:
            logger.warning("prompt_cache lookup falló (ignorado): %s", _cache_exc)
            _cache_key, _hit = None, None

        if _hit is not None:
            logger.info("→ %s [caché] | modelo: %s (sin llamada al LLM)", agent_label, model)
            text = _hit
            cost_entry = make_cost_entry(agent_label, model, _FakeUsage(0, 0))
        else:
            text, cost_entry = retry_sync(_dispatch, label=agent_label)
            if _cache_key is not None:
                try:
                    from tools import prompt_cache
                    prompt_cache.set(_cache_key, text)
                except Exception as _cache_exc:
                    logger.warning("prompt_cache store falló (ignorado): %s", _cache_exc)

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

    # R2: hook post_agent (observacional por defecto; no-op sin hooks registrados).
    try:
        from tools.hook_engine import run_hooks
        run_hooks("post_agent", {
            "agent_key": agent_key, "agent_label": agent_label,
            "model": model, "feature_id": _fid, "output_text": text,
            "cost_usd": cost_entry.get("cost_usd", 0.0),
        })
    except Exception as _hook_exc:
        logger.warning("hook post_agent falló (ignorado): %s", _hook_exc)

    return text, cost_entry
