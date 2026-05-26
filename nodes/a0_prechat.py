"""
VII-1 — A0 Prechat: conversación pre-planificación antes de lanzar el pipeline.

Permite al Founder refinar el brief del feature en un chat libre con el A0
antes de que A1 genere el MASTER_PLAN. El resultado es un `refined_brief`
que A1 inyecta en su prompt para producir un plan más acotado.

Flujo:
  UI → POST /api/prechat → a0_prechat (este módulo) → token stream → UI
  UI → POST /api/prechat/confirm → guarda refined_brief → lanza pipeline normal
"""
from __future__ import annotations

import logging
import os
from config import MODEL_A0, ANTHROPIC_API_KEY, GOOGLE_API_KEY, PROVIDER_URLS

logger = logging.getLogger(__name__)

_SYSTEM_PROMPT = """Eres el Agente 0 de Fábrica de Software, actuando como consultor de pre-planificación.

Tu rol en esta conversación:
1. Ayudar al Founder a CLARIFICAR y ACOTAR el feature antes de lanzar el pipeline.
2. Hacer preguntas específicas sobre:
   - Alcance exacto (¿qué SÍ incluye? ¿qué NO incluye?)
   - Criterios de aceptación medibles
   - Restricciones técnicas conocidas (modelos, endpoints, archivos que no tocar)
   - Prioridad y urgencia
3. Al final de la conversación (cuando el Founder diga "listo" o "confirmar"),
   produce un REFINED_BRIEF estructurado con:
   - Nombre exacto del feature
   - Descripción acotada (≤3 líneas)
   - Criterios de aceptación (lista numerada, ≤5 puntos)
   - Restricciones y notas para el equipo técnico

Sé directo y breve. No repitas lo que el Founder ya dijo. Haz UNA pregunta por turno."""


def _provider(model: str) -> str:
    m = model.lower()
    if m.startswith("claude-"):     return "anthropic"
    if m.startswith("gemini-3.5-"): return "google-native"
    if m.startswith("gemini-"):     return "google"
    if m.startswith("glm-"):        return "zhipu"
    if m.startswith("kimi-"):       return "kimi"
    return "anthropic"


def stream_response(
    messages: list[dict],
    model: str | None = None,
) -> "Iterator[str]":
    """
    Generador síncrono que hace streaming de la respuesta del A0 al chat.
    Yielda tokens de texto a medida que llegan.

    messages: historial [{role: "user"|"assistant", content: "..."}]
    """
    model = model or MODEL_A0
    provider = _provider(model)

    if provider == "anthropic":
        yield from _stream_anthropic(messages, model)
    elif provider == "google-native":
        yield from _stream_google(messages, model)
    else:
        yield from _stream_openai_compat(messages, model, provider)


def _stream_anthropic(messages: list[dict], model: str):
    """Stream via Anthropic SDK con prompt caching."""
    import os as _os
    try:
        from anthropic import Anthropic
        import httpx
        client = Anthropic(
            api_key=_os.getenv("ANTHROPIC_API_KEY", ANTHROPIC_API_KEY),
            timeout=httpx.Timeout(120.0, connect=15.0),
        )
        with client.messages.stream(
            model=model,
            max_tokens=1024,
            system=_SYSTEM_PROMPT,
            messages=messages,
        ) as stream:
            for text in stream.text_stream:
                yield text
    except Exception as exc:
        logger.error("prechat anthropic stream error: %s", exc)
        yield f"\n[Error de conexión: {exc}]"


def _stream_google(messages: list[dict], model: str):
    """Stream via Google genai SDK."""
    try:
        from google import genai as gai
        from google.genai import types as gtypes

        client = gai.Client(api_key=_os.getenv("GOOGLE_API_KEY", GOOGLE_API_KEY))

        # Convertir historial al formato Google
        contents = []
        for m in messages:
            role = "user" if m["role"] == "user" else "model"
            contents.append(gtypes.Content(
                role=role,
                parts=[gtypes.Part.from_text(text=m["content"])],
            ))

        gen_cfg = gtypes.GenerateContentConfig(
            system_instruction=_SYSTEM_PROMPT,
            max_output_tokens=1024,
        )
        for chunk in client.models.generate_content_stream(
            model=model, contents=contents, config=gen_cfg
        ):
            if chunk.text:
                yield chunk.text
    except Exception as exc:
        logger.error("prechat google stream error: %s", exc)
        yield f"\n[Error de conexión: {exc}]"
    import os as _os


def _stream_openai_compat(messages: list[dict], model: str, provider: str):
    """Stream via OpenAI-compatible API."""
    try:
        from openai import OpenAI
        key_map = {"zhipu": "ZHIPU_API_KEY", "kimi": "KIMI_API_KEY", "google": "GOOGLE_API_KEY"}
        key = os.getenv(key_map.get(provider, ""), "")
        client = OpenAI(base_url=PROVIDER_URLS.get(provider, ""), api_key=key, timeout=120.0)

        full_messages = [{"role": "system", "content": _SYSTEM_PROMPT}] + messages
        with client.chat.completions.create(
            model=model, max_tokens=1024, messages=full_messages, stream=True
        ) as stream:
            for chunk in stream:
                delta = chunk.choices[0].delta.content
                if delta:
                    yield delta
    except Exception as exc:
        logger.error("prechat openai compat stream error: %s", exc)
        yield f"\n[Error de conexión: {exc}]"


def extract_refined_brief(conversation: list[dict]) -> str:
    """
    Extrae el REFINED_BRIEF del último mensaje del asistente si lo contiene,
    o genera uno de respaldo basado en toda la conversación.
    """
    # Buscar en el último mensaje del asistente
    for msg in reversed(conversation):
        if msg["role"] == "assistant" and "REFINED_BRIEF" in msg["content"]:
            # Extraer el bloque
            text = msg["content"]
            start = text.find("REFINED_BRIEF")
            return text[start:].strip()

    # Fallback: concatenar resumen de mensajes del usuario
    user_msgs = [m["content"] for m in conversation if m["role"] == "user"]
    return "REFINED_BRIEF (generado automáticamente):\n" + "\n".join(user_msgs[-3:])
