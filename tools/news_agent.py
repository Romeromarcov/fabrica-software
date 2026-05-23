"""
Agente de Noticias Diario — independiente de la Fábrica de Software.

Soporta múltiples proveedores de IA:
  • anthropic — usa web_search tool nativo (búsqueda en tiempo real)
  • google    — usa Gemini via endpoint OpenAI-compatible (conocimiento del modelo)
  • openai    — usa OpenAI API directamente
  • custom    — usa cualquier endpoint OpenAI-compatible (NEWS_AGENT_API_URL)

Funciones:
  run_news_report()       → Reporte de noticias por Telegram
  run_ai_models_report()  → Reporte de modelos IA por Telegram
  run_daily_reports()     → Punto de entrada del scheduler (ambos reportes)
"""
from __future__ import annotations

import logging
import os
from datetime import datetime

logger = logging.getLogger(__name__)


# ── Helpers de configuración ──────────────────────────────────────────────────

def _get_cfg() -> dict:
    """Lee la configuración actual del news agent desde env vars."""
    return {
        "provider":  os.getenv("NEWS_AGENT_PROVIDER", "anthropic"),
        "model":     os.getenv("NEWS_AGENT_MODEL",    "claude-haiku-4-5-20251001"),
        "api_key":   os.getenv("NEWS_AGENT_API_KEY",  ""),
        "api_url":   os.getenv("NEWS_AGENT_API_URL",  ""),
        "topics":    [t.strip() for t in os.getenv(
            "NEWS_AGENT_TOPICS",
            "Inteligencia Artificial,Blockchain y Web3,Mercado Crypto,"
            "Marketing Digital,Negocios Globales,Petróleo e Hidrocarburos,"
            "Geopolítica,Finanzas Venezuela"
        ).split(",") if t.strip()],
        "tg_token":  os.getenv("NEWS_AGENT_TG_TOKEN", "") or os.getenv("TELEGRAM_BOT_TOKEN", ""),
        "tg_chat":   os.getenv("NEWS_AGENT_TG_CHAT",  "") or os.getenv("TELEGRAM_CHAT_ID",  ""),
    }


def _send(text: str, cfg: dict) -> bool:
    """Envía mensaje por Telegram usando la config del news agent (token/chat propios o compartidos)."""
    import httpx
    token = cfg["tg_token"]
    chat  = cfg["tg_chat"]
    if not token or not chat:
        logger.warning("news_agent: Telegram no configurado — omitiendo envío")
        return False
    try:
        r = httpx.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": chat, "text": text, "parse_mode": "Markdown"},
            timeout=15,
        )
        return r.status_code == 200
    except Exception as e:
        logger.warning("news_agent: error Telegram: %s", e)
        return False


# ── Motor de IA ───────────────────────────────────────────────────────────────

def _call_with_search(prompt: str, cfg: dict, max_searches: int = 10) -> str:
    """
    Llama al proveedor configurado para generar el reporte.
    Anthropic: usa web_search tool (búsqueda real en internet).
    Otros: generan con el conocimiento del modelo (sin búsqueda en tiempo real).
    """
    provider = cfg["provider"]
    model    = cfg["model"]

    # Resolver API key: usa la key específica del agente, o la del proveedor
    if provider == "anthropic":
        api_key = cfg["api_key"] or os.getenv("ANTHROPIC_API_KEY", "")
        return _call_anthropic(prompt, model, api_key, max_searches)

    elif provider == "google":
        api_key = cfg["api_key"] or os.getenv("GOOGLE_API_KEY", "")
        return _call_openai_compat(
            prompt, model, api_key,
            base_url="https://generativelanguage.googleapis.com/v1beta/openai/",
        )

    elif provider == "openai":
        api_key = cfg["api_key"] or os.getenv("OPENAI_API_KEY", "")
        return _call_openai_compat(prompt, model, api_key, base_url="https://api.openai.com/v1/")

    elif provider == "zhipu":
        api_key = cfg["api_key"] or os.getenv("ZHIPU_API_KEY", "")
        return _call_openai_compat(prompt, model, api_key, base_url="https://api.z.ai/api/paas/v4/")

    elif provider == "kimi":
        api_key = cfg["api_key"] or os.getenv("KIMI_API_KEY", "")
        return _call_openai_compat(prompt, model, api_key, base_url="https://api.moonshot.ai/v1/")

    else:  # custom
        api_key = cfg["api_key"]
        base_url = cfg["api_url"]
        if not base_url:
            raise ValueError("NEWS_AGENT_API_URL requerido para proveedor 'custom'")
        return _call_openai_compat(prompt, model, api_key, base_url=base_url)


def _call_anthropic(prompt: str, model: str, api_key: str, max_searches: int) -> str:
    """Usa la API de Anthropic con web_search tool para búsqueda en tiempo real."""
    import anthropic
    client = anthropic.Anthropic(api_key=api_key)
    response = client.messages.create(
        model=model,
        max_tokens=4096,
        tools=[{"type": "web_search_20250305", "name": "web_search", "max_uses": max_searches}],
        messages=[{"role": "user", "content": prompt}],
    )
    return "\n".join(b.text for b in response.content if hasattr(b, "text")).strip()


def _call_openai_compat(prompt: str, model: str, api_key: str, base_url: str) -> str:
    """Usa cualquier endpoint compatible con OpenAI (Google, Zhipu, Kimi, Custom, etc.)."""
    from openai import OpenAI
    client = OpenAI(api_key=api_key or "none", base_url=base_url)
    response = client.chat.completions.create(
        model=model,
        max_tokens=4096,
        messages=[{"role": "user", "content": prompt}],
    )
    return response.choices[0].message.content or ""


# ── Reportes ──────────────────────────────────────────────────────────────────

def run_news_report() -> bool:
    """Genera y envía el reporte diario de noticias por Telegram."""
    cfg   = _get_cfg()
    today = datetime.now().strftime("%d/%m/%Y")
    topics_list = "\n".join(f"- {t}" for t in cfg["topics"])

    has_search = cfg["provider"] == "anthropic"
    search_note = (
        "Busca noticias ACTUALES de HOY en internet para cada tema."
        if has_search else
        "Usa tu conocimiento más reciente. Indica la fecha aproximada de cada noticia."
    )

    prompt = f"""Eres un analista de noticias para un empresario venezolano. Hoy es {today}.

{search_note}

Temas a cubrir:
{topics_list}

Selecciona las 5 noticias MÁS IMPORTANTES considerando:
- Impacto directo en Venezuela y su economía
- Oportunidades de negocio globales
- Precio del petróleo y dólar
- Tecnología aplicable a empresas venezolanas

Para cada noticia usa EXACTAMENTE este formato Telegram Markdown:

📰 *REPORTE DE NOTICIAS — {today}*

1️⃣ *[TÍTULO CORTO]*
📍 _{cfg['topics'][0] if cfg['topics'] else 'Tema'}_ | _[Fuente] — [fecha]_
[Resumen en 2-3 líneas]
🇻🇪 *Impacto Venezuela:* [por qué importa]

[Repite para noticias 2-5]

---
_Generado por Fábrica de Software · IA al servicio del negocio_"""

    try:
        logger.info("news_agent: generando reporte de noticias (proveedor=%s)...", cfg["provider"])
        report = _call_with_search(prompt, cfg)
        if not report:
            logger.warning("news_agent: reporte vacío")
            return False
        sent = _send(report, cfg)
        logger.info("news_agent: noticias enviadas=%s", sent)
        return sent
    except Exception as e:
        logger.exception("news_agent: error en reporte de noticias: %s", e)
        return False


def run_ai_models_report() -> bool:
    """Genera y envía el reporte de modelos IA por Telegram."""
    cfg   = _get_cfg()
    today = datetime.now().strftime("%d/%m/%Y")

    has_search = cfg["provider"] == "anthropic"
    search_note = (
        "Busca información ACTUAL sobre modelos IA, precios y lanzamientos recientes."
        if has_search else
        "Usa tu conocimiento más reciente sobre modelos IA y precios de API."
    )

    prompt = f"""Eres un analista especialista en modelos de inteligencia artificial. Hoy es {today}.

{search_note}

Entrega:
1. Top 5-8 modelos IA más relevantes hoy (OpenAI, Anthropic, Google, Meta, DeepSeek, etc.)
2. Para cada uno: proveedor, precio input/output por 1M tokens, capacidades clave
3. Modelos NUEVOS o cambios de PRECIO recientes (últimas 2 semanas si tienes info)
4. Recomendación clara por caso de uso

Formato Telegram Markdown:

🤖 *REPORTE MODELOS IA — {today}*

📊 *TOP MODELOS POR COSTO/BENEFICIO:*

▸ *[Nombre]* ([Proveedor])
  💰 In: $[X]/1M tok | Out: $[Y]/1M tok
  ⚡ [Capacidades en 1 línea]
  🎯 Ideal para: [caso de uso]

[Repite para cada modelo]

🆕 *NOVEDADES (últimas 2 semanas):*
[Lista o "Sin novedades confirmadas"]

⚠️ *CAMBIOS DE PRECIO:*
[Lista o "Sin cambios detectados"]

💡 *RECOMENDACIÓN:*
- Mejor costo/beneficio general: [modelo]
- Mejor para razonamiento: [modelo]
- Más económico para tareas simples: [modelo]

---
_Análisis automático · Fábrica de Software_"""

    try:
        logger.info("news_agent: generando reporte de modelos IA...")
        report = _call_with_search(prompt, cfg, max_searches=8)
        if not report:
            logger.warning("news_agent: reporte IA vacío")
            return False
        sent = _send(report, cfg)

        # Alertar al PM si hay cambios de precio
        if sent and _detect_price_changes(report):
            _notify_pm_changes(report, cfg)

        logger.info("news_agent: reporte IA enviado=%s", sent)
        return sent
    except Exception as e:
        logger.exception("news_agent: error en reporte de modelos: %s", e)
        return False


def _detect_price_changes(text: str) -> bool:
    keywords = [
        "reducción de precio", "baja de precio", "aumento de precio",
        "precio reducido", "nuevo modelo", "lanzamiento", "price cut",
        "price reduction", "new model", "released", "cambio de precio",
    ]
    low = text.lower()
    return any(k in low for k in keywords)


def _notify_pm_changes(report_text: str, cfg: dict) -> None:
    alert = (
        "⚠️ *ALERTA — Cambios en Modelos IA Detectados*\n\n"
        "El reporte diario detectó nuevos modelos o cambios de precio.\n\n"
        "📋 *Acción sugerida:*\n"
        "1. Revisar el reporte de modelos enviado hoy\n"
        "2. Evaluar si conviene actualizar los modelos en Configuración\n"
        "3. Comparar costo actual vs nuevas alternativas"
    )
    _send(alert, cfg)
    logger.info("news_agent: alerta de cambios de modelos enviada")


def run_daily_reports() -> None:
    """Punto de entrada del scheduler diario."""
    logger.info("=== Iniciando reportes diarios (news_agent) ===")
    run_news_report()
    run_ai_models_report()
    logger.info("=== Reportes diarios completados ===")
