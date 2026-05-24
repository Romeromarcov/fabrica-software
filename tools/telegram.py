"""
Notificaciones vía Telegram Bot.

Configurar en .env:
  TELEGRAM_BOT_TOKEN=123456:ABC-...
  TELEGRAM_CHAT_ID=-100123456789

Si no están configurados, las llamadas son no-ops silenciosos.
"""
from __future__ import annotations
import os
import logging
import httpx

logger = logging.getLogger(__name__)


def send_message(text: str, parse_mode: str = "Markdown") -> bool:
    """
    Envía un mensaje al chat configurado.
    A-03: lee TOKEN y CHAT_ID en cada llamada para capturar cambios en runtime.
    Retorna True si fue exitoso, False si falla o no está configurado.
    Nunca lanza excepción — las notificaciones son best-effort.
    """
    token   = os.getenv("TELEGRAM_BOT_TOKEN", "")
    chat_id = os.getenv("TELEGRAM_CHAT_ID", "")
    if not token or not chat_id:
        logger.debug("Telegram no configurado — notificación omitida")
        return False
    try:
        url  = f"https://api.telegram.org/bot{token}/sendMessage"
        resp = httpx.post(
            url,
            json={"chat_id": chat_id, "text": text[:4096], "parse_mode": parse_mode},
            timeout=10,
        )
        resp.raise_for_status()
        logger.info("Telegram: mensaje enviado (%d chars)", len(text))
        return True
    except Exception as exc:
        logger.warning("Telegram: fallo al enviar notificación — %s", exc)
        return False


def notify_feature_done(feature_name: str, project_name: str | None,
                        cost_usd: float, pr_url: str) -> None:
    icon = "🏁" if not project_name else "✅"
    lines = [
        f"{icon} *Feature completado*",
        f"*Feature:* {feature_name}",
    ]
    if project_name:
        lines.append(f"*Proyecto:* {project_name}")
    lines += [
        f"*Costo:* ${cost_usd:.4f} USD",
        f"*PR:* {pr_url or 'creado localmente'}",
    ]
    send_message("\n".join(lines))


def notify_escalation(feature_name: str, reason: str,
                       project_name: str | None = None) -> None:
    lines = [
        "⚠️ *Escalación — se requiere intervención humana*",
        f"*Feature:* {feature_name}",
    ]
    if project_name:
        lines.append(f"*Proyecto:* {project_name}")
    lines.append(f"*Motivo:* {reason[:300]}")
    send_message("\n".join(lines))


def notify_project_done(project_name: str, completed: int, total: int,
                         cost_usd: float) -> None:
    send_message(
        f"🎉 *Proyecto completado*\n"
        f"*Proyecto:* {project_name}\n"
        f"*Features:* {completed}/{total}\n"
        f"*Costo total:* ${cost_usd:.4f} USD"
    )


def notify_approval_needed(project_name: str, project_id: str,
                            interrupt_type: str = "project_roadmap_approval") -> None:
    """
    Notifica que hay un plan/roadmap esperando aprobación.
    Incluye los comandos de Telegram para responder sin abrir la UI.
    """
    labels = {
        "project_roadmap_approval": "📐 Roadmap listo — aprobación requerida",
        "project_suggestions":      "💡 Sugerencias del PM — aprobación requerida",
        "checkpoint":               "🔔 Checkpoint — acción requerida",
        "qa_escalation":            "⚠️ Escalación QA — decisión requerida",
    }
    title = labels.get(interrupt_type, "🔔 Aprobación requerida")
    short_id = project_id[:40]
    send_message(
        f"{title}\n"
        f"*Proyecto:* {project_name}\n"
        f"*ID:* `{short_id}`\n\n"
        f"Responde desde este chat:\n"
        f"✅ `/aprobar {short_id}`\n"
        f"❌ `/rechazar {short_id}`\n"
        f"✏️ `/cambios {short_id} [tu feedback]`"
    )


def notify_veto_window(
    feature_name: str,
    feature_id: str,
    confidence: int,
    risk: str,
    plan_summary: str,
    deadline_minutes: int,
) -> None:
    """
    Notifica al Founder que un plan está en ventana de veto automático.
    Si no responde en deadline_minutes, el pipeline continúa solo.
    """
    short_id = feature_id[:40]
    risk_icon = {"LOW": "🟢", "MEDIUM": "🟡", "HIGH": "🔴"}.get(risk, "⚪")
    send_message(
        f"⏳ *Ventana de veto — {deadline_minutes} min*\n"
        f"*Feature:* {feature_name}\n"
        f"*Confianza:* {confidence}/100 · Riesgo: {risk_icon} {risk}\n\n"
        f"*Resumen del plan:*\n{plan_summary[:400]}\n\n"
        f"Si no respondes en {deadline_minutes} min el pipeline continúa automáticamente.\n"
        f"Para vetar: `/vetar {short_id}`"
    )


def notify_suggestions(project_name: str, suggestions: list[str],
                        project_id: str = "") -> None:
    sug_text = "\n".join(f"• {s}" for s in suggestions[:10]) or "Ninguna"
    base = (
        f"💡 *Sugerencias del PM — aprobación requerida*\n"
        f"*Proyecto:* {project_name}\n\n"
        f"*Sugerencias:*\n{sug_text}\n\n"
    )
    if project_id:
        short_id = project_id[:40]
        base += (
            f"Responde desde este chat:\n"
            f"✅ `/aprobar {short_id}`\n"
            f"❌ `/rechazar {short_id}`\n"
            f"✏️ `/cambios {short_id} [feedback]`"
        )
    else:
        base += "Abre la UI para aprobar o cerrar el proyecto."
    send_message(base)
