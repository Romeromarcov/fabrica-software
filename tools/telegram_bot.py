"""
Bot de Telegram interactivo — Fábrica de Software v2.2

Operación completa del pipeline desde Telegram:

  /start  /ayuda     → Menú de ayuda con botones
  /status            → Aprobaciones pendientes con botones inline ✅ ❌
  /dashboard         → Estadísticas rápidas del sistema
  /historial         → Últimos 5 features con estado y costo
  /feature <repo>: <nombre> [--lite|--lightning]  → Lanzar feature
  /repos             → Repositorios disponibles
  /aprobar [id]      → Aprobar plan (o usar botón inline)
  /rechazar [id]     → Rechazar plan (o usar botón inline)
  /vetar [id]        → Vetar plan en ventana de veto
  /cambios [id] <texto>  → Feedback con texto libre
  /intervenir <id> <texto>  → VIII-1: Instrucción correctiva mid-flight
  /modo              → Cambiar modo por defecto del próximo feature
  /ayuda             → Esta ayuda

El bot usa long-polling. Se arranca desde server.py en el lifespan de FastAPI.
"""
from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import httpx

import config

logger = logging.getLogger(__name__)

# A1.1 — Bandera para advertir UNA sola vez si la whitelist de admins está vacía
# (evita spam en logs cuando TELEGRAM_ADMIN_IDS no está configurado).
_warned_no_whitelist = False


def _is_authorized_user(user_id: int | None) -> bool:
    """
    A1.1 — Valida que el user_id esté en la whitelist de administradores.

    Se lee `config.TELEGRAM_ADMIN_IDS` dinámicamente (no se enlaza al importar)
    para que los tests puedan monkeypatchearlo.

    - Whitelist NO vacía → solo se autoriza si user_id está en ella.
    - Whitelist vacía → compatibilidad hacia atrás (solo chat_id), pero se
      registra una advertencia UNA vez en logs.
    """
    global _warned_no_whitelist
    admin_ids = config.TELEGRAM_ADMIN_IDS
    if not admin_ids:
        if not _warned_no_whitelist:
            logger.warning(
                "Telegram: whitelist de admins (TELEGRAM_ADMIN_IDS) NO configurada "
                "— solo se valida chat_id. Recomendado definirla en producción."
            )
            _warned_no_whitelist = True
        return True
    return user_id in admin_ids

# ── Tipos de interrupción ─────────────────────────────────────────────────────

INTERRUPT_LABELS = {
    "project_roadmap_approval": "📐 Aprobación de Roadmap",
    "project_suggestions":      "💡 Sugerencias del PM",
    "checkpoint":               "🔔 Checkpoint",
    "qa_escalation":            "⚠️ Escalación QA",
    "stop_protocol":            "⛔ Stop Protocol — Plan listo",
    "veto_window":              "⏳ Ventana de Veto",
}

_RESP_MAP: dict[str, dict[str, str]] = {
    "project_roadmap_approval": {
        "approve": "Roadmap aprobado. Iniciar proyecto.",
        "cancel":  "CANCELAR",
    },
    "project_suggestions": {
        "approve": "CONTINUAR",
        "cancel":  "CERRAR",
    },
    "checkpoint": {
        "approve": "CONTINUAR",
        "cancel":  "PAUSA",
    },
    "qa_escalation": {
        "approve": "ACEPTAR",
        "cancel":  "CANCELAR",
    },
    "stop_protocol": {
        "approve": "Plan aprobado. Pasa a ejecución.",
        "cancel":  "CANCELAR",
    },
    "veto_window": {
        "approve": "CONTINUAR",
        "cancel":  "VETAR",
    },
}

# Modo por defecto para /feature (configurable con /modo)
_default_mode: str = "auto"

# ── Filesystem helpers ────────────────────────────────────────────────────────

def _runs_dir() -> Path:
    from tools.file_tools import RUNS_DIR
    return RUNS_DIR


def _find_pending() -> list[dict]:
    """Escanea RUNS_DIR buscando procesos que esperan aprobación."""
    pending: list[dict] = []
    rd = _runs_dir()
    if not rd.exists():
        return pending
    for run_dir in sorted(rd.iterdir(), reverse=True):
        interrupt_file = run_dir / "pending_interrupt_type.txt"
        if not interrupt_file.exists():
            continue
        interrupt_type = interrupt_file.read_text().strip()
        meta_path = run_dir / "metadata.json"
        meta = json.loads(meta_path.read_text()) if meta_path.exists() else {}
        pending.append({
            "id":    run_dir.name,
            "name":  meta.get("project_name") or meta.get("feature_name", run_dir.name),
            "type":  interrupt_type,
            "label": INTERRUPT_LABELS.get(interrupt_type, interrupt_type),
            "meta":  meta,
        })
    return pending


def _write_approval(run_id: str, response: str) -> bool:
    run_dir = _runs_dir() / run_id
    if not run_dir.exists():
        return False
    (run_dir / "pending_approval.txt").write_text(response)
    logger.info("Bot Telegram: respuesta '%s' → %s", response[:40], run_id)
    return True


def _resolve_pending_item(run_id_hint: str | None, pending: list[dict]) -> dict | None:
    if not pending:
        return None
    if run_id_hint is None:
        return pending[0] if len(pending) == 1 else None
    for p in pending:
        if p["id"] == run_id_hint:
            return p
    matches = [p for p in pending if run_id_hint.lower() in p["id"].lower()]
    return matches[0] if len(matches) == 1 else None


def _get_all_runs() -> list[dict]:
    """Lee todos los runs del RUNS_DIR ordenados por fecha desc."""
    runs: list[dict] = []
    rd = _runs_dir()
    if not rd.exists():
        return runs
    for d in sorted(rd.iterdir(), reverse=True):
        meta_path = d / "metadata.json"
        if not meta_path.exists():
            continue
        try:
            meta = json.loads(meta_path.read_text())
            meta["feature_id"] = d.name
            runs.append(meta)
        except Exception:
            pass
    return runs


# ── Telegram API helpers ──────────────────────────────────────────────────────

def _tg(method: str, token: str, **payload) -> dict:
    """Llama a la Telegram Bot API. Falla silenciosamente."""
    try:
        r = httpx.post(
            f"https://api.telegram.org/bot{token}/{method}",
            json=payload,
            timeout=10,
        )
        return r.json()
    except Exception as exc:
        logger.warning("Bot Telegram: %s error: %s", method, exc)
        return {}


def _tg_send(token: str, chat_id: str, text: str,
             reply_markup: dict | None = None) -> dict:
    """Envía mensaje Markdown con teclado inline opcional."""
    payload: dict = {
        "chat_id":    chat_id,
        "text":       text[:4096],
        "parse_mode": "Markdown",
    }
    if reply_markup:
        payload["reply_markup"] = reply_markup
    result = _tg(method="sendMessage", token=token, **payload)
    return result.get("result", {})


def _tg_edit_text(token: str, chat_id: str, message_id: int, text: str) -> None:
    """Edita el texto de un mensaje existente (quita teclado inline)."""
    _tg(
        method="editMessageText",
        token=token,
        chat_id=chat_id,
        message_id=message_id,
        text=text[:4096],
        parse_mode="Markdown",
        reply_markup={"inline_keyboard": []},
    )


def _tg_answer_callback(token: str, callback_query_id: str, text: str = "") -> None:
    """Responde a un callback query (quita el spinner del botón)."""
    _tg(
        method="answerCallbackQuery",
        token=token,
        callback_query_id=callback_query_id,
        text=text[:200],
    )


def _tg_get_updates(token: str, offset: int) -> tuple[list, int]:
    """Long-polling getUpdates con timeout 30 s."""
    try:
        r = httpx.get(
            f"https://api.telegram.org/bot{token}/getUpdates",
            params={
                "offset": offset,
                "timeout": 30,
                "allowed_updates": ["message", "callback_query"],
            },
            timeout=35,
        )
        updates = r.json().get("result", [])
        if updates:
            offset = updates[-1]["update_id"] + 1
        return updates, offset
    except Exception as exc:
        logger.warning("Bot Telegram: getUpdates error: %s", exc)
        return [], offset


def _tg_set_my_commands(token: str) -> None:
    """Registra los comandos del bot en Telegram (aparecen como sugerencias)."""
    commands = [
        {"command": "status",     "description": "Aprobaciones pendientes"},
        {"command": "dashboard",  "description": "Estadísticas del sistema"},
        {"command": "historial",  "description": "Últimos 5 features"},
        {"command": "feature",    "description": "Lanzar nuevo feature"},
        {"command": "repos",      "description": "Repositorios disponibles"},
        {"command": "intervenir", "description": "Instrucción correctiva mid-flight"},
        {"command": "aprobar",    "description": "Aprobar plan pendiente"},
        {"command": "rechazar",   "description": "Rechazar plan pendiente"},
        {"command": "vetar",      "description": "Vetar plan en ventana de veto"},
        {"command": "cambios",    "description": "Enviar feedback con texto"},
        {"command": "modo",       "description": "Cambiar modo de ejecución"},
        {"command": "ayuda",      "description": "Ayuda y comandos disponibles"},
    ]
    _tg(method="setMyCommands", token=token, commands=commands)


def _inline_keyboard(*rows: list[dict]) -> dict:
    """Genera un reply_markup con teclado inline."""
    return {"inline_keyboard": list(rows)}


def _approval_keyboard(run_id: str, interrupt_type: str) -> dict:
    """Teclado inline para aprobar/rechazar con el run_id embebido."""
    short = run_id[:40]
    buttons = [
        {"text": "✅ Aprobar",  "callback_data": f"approve:{short}"},
        {"text": "❌ Rechazar", "callback_data": f"reject:{short}"},
    ]
    if interrupt_type == "veto_window":
        buttons = [
            {"text": "✅ Continuar", "callback_data": f"approve:{short}"},
            {"text": "🛑 Vetar",     "callback_data": f"veto:{short}"},
        ]
    return _inline_keyboard(buttons)


# ── Comandos ──────────────────────────────────────────────────────────────────

_HELP_TEXT = (
    "🏭 *Fábrica de Software* — Comandos\n\n"
    "📋 *Aprobaciones*\n"
    "`/status` — Ver pendientes con botones\n"
    "`/aprobar [id]` · `/rechazar [id]` · `/vetar [id]`\n"
    "`/cambios [id] <feedback>` — Feedback libre\n\n"
    "🚀 *Features*\n"
    "`/feature <repo>: <nombre>` — Lanzar (modo auto)\n"
    "`/feature <repo>: <nombre> --lite` — Modo lite\n"
    "`/feature <repo>: <nombre> --lightning` — ⚡ Lightning\n"
    "`/repos` — Ver repositorios disponibles\n"
    "`/modo [auto|lite|lightning]` — Cambiar modo por defecto\n\n"
    "⚡ *Control en tiempo real*\n"
    "`/intervenir <id> <texto>` — Instrucción correctiva al agente activo\n\n"
    "📊 *Información*\n"
    "`/dashboard` — Estadísticas rápidas\n"
    "`/historial` — Últimos 5 features\n\n"
    "_Si hay un solo proceso pendiente, `[id]` es opcional._"
)


def _handle_command(token: str, chat_id: str, text: str) -> None:
    global _default_mode
    parts = text.strip().split(None, 2)
    cmd   = parts[0].lower().split("@")[0]

    # ── /start /ayuda /help ───────────────────────────────────────────────────
    if cmd in ("/ayuda", "/help", "/start"):
        _tg_send(token, chat_id, _HELP_TEXT)
        return

    # ── /dashboard ────────────────────────────────────────────────────────────
    if cmd == "/dashboard":
        runs = _get_all_runs()
        total = len(runs)
        done  = sum(1 for r in runs if r.get("status") in ("completado", "completed", "completado_lightning"))
        active = sum(1 for r in runs if r.get("status") in ("iniciando", "building", "approved", "auto_approved", "planning", "running"))
        cost  = sum(r.get("total_cost_usd", 0) for r in runs)
        pending = _find_pending()

        lines = [
            "📊 *Dashboard — Fábrica de Software*\n",
            f"🔢 *Runs totales:* {total}",
            f"✅ *Completados:* {done}",
            f"⏳ *En progreso:* {active}",
            f"💰 *Costo total:* ${cost:.4f} USD",
        ]
        if pending:
            lines.append(f"\n⚡ *{len(pending)} aprobación(es) pendiente(s)* — usa /status")
        else:
            lines.append("\n✅ Sin aprobaciones pendientes")
        _tg_send(token, chat_id, "\n".join(lines))
        return

    # ── /historial ────────────────────────────────────────────────────────────
    if cmd == "/historial":
        runs = _get_all_runs()[:5]
        if not runs:
            _tg_send(token, chat_id, "📭 No hay features registrados todavía.")
            return
        status_icons = {
            "completado": "✅", "completed": "✅", "completado_lightning": "⚡",
            "detenido": "🛑", "failed": "❌", "cancelled": "❌",
            "iniciando": "🔄", "building": "⚙️", "planning": "📋",
            "approved": "👍", "running": "⏳",
        }
        lines = ["📋 *Últimos features:*\n"]
        for r in runs:
            status = r.get("status", "?")
            icon = status_icons.get(status, "❓")
            cost = r.get("total_cost_usd", 0)
            name = r.get("feature_name") or r.get("feature_id", "?")[:30]
            mode = r.get("mode", "")
            mode_tag = f" `[{mode}]`" if mode else ""
            date = (r.get("started_at") or "")[:10]
            lines.append(
                f"{icon} *{name}*{mode_tag}\n"
                f"   `{r.get('feature_id', '')[:30]}` · ${cost:.4f} · {date}"
            )
        _tg_send(token, chat_id, "\n".join(lines))
        return

    # ── /status ───────────────────────────────────────────────────────────────
    if cmd == "/status":
        pending = _find_pending()
        if not pending:
            _tg_send(token, chat_id, "✅ *Sin aprobaciones pendientes.*\nEl pipeline está corriendo solo.")
            return
        for p in pending:
            meta = p.get("meta", {})
            conf  = meta.get("confidence_score", "")
            risk  = meta.get("risk_level", "")
            mode  = meta.get("mode", "")
            conf_str = f"\n🎯 Confianza: {conf}/100 · Riesgo: {risk}" if conf else ""
            mode_str = f"\n🔧 Modo: `{mode}`" if mode else ""
            msg = (
                f"{p['label']}\n"
                f"*{p['name']}*{mode_str}{conf_str}\n"
                f"`{p['id'][:40]}`"
            )
            keyboard = _approval_keyboard(p["id"], p["type"])
            result = _tg_send(token, chat_id, msg, reply_markup=keyboard)
            # Guardar message_id para poder editar el mensaje cuando se pulse el botón
            if result.get("message_id"):
                _save_tg_msg_id(p["id"], result["message_id"])
        return

    # ── /repos ────────────────────────────────────────────────────────────────
    if cmd == "/repos":
        try:
            from config import list_repos
            repos = list_repos()
            if not repos:
                _tg_send(token, chat_id, "⚠️ No hay repositorios en WORKSPACES_ROOT.")
                return
            lines = ["📁 *Repositorios disponibles:*\n"]
            for r in repos:
                lines.append(f"• `{r['name']}`")
            lines.append(
                f"\n*Uso:* `/feature {repos[0]['name']}: Nombre del feature`\n"
                f"_Opciones: --lite · --lightning_"
            )
            _tg_send(token, chat_id, "\n".join(lines))
        except Exception as e:
            _tg_send(token, chat_id, f"❌ Error: {e}")
        return

    # ── /modo [auto|lite|lightning] ───────────────────────────────────────────
    if cmd == "/modo":
        if len(parts) < 2:
            _tg_send(token, chat_id,
                f"🔧 *Modo actual:* `{_default_mode}`\n\n"
                "Usa `/modo auto`, `/modo lite` o `/modo lightning` para cambiar.\n"
                "Solo afecta los features lanzados con `/feature` desde Telegram.")
            return
        new_mode = parts[1].lower().strip("-")
        if new_mode not in ("auto", "lite", "completo", "lightning"):
            _tg_send(token, chat_id, "⚠️ Modos válidos: `auto`, `lite`, `completo`, `lightning`")
            return
        _default_mode = new_mode
        icons = {"auto": "🤖", "lite": "💡", "completo": "🔬", "lightning": "⚡"}
        _tg_send(token, chat_id,
            f"{icons.get(new_mode,'✅')} *Modo cambiado a `{new_mode}`*\n"
            f"El próximo `/feature` usará este modo.")
        return

    # ── /aprobar [id] ────────────────────────────────────────────────────────
    if cmd == "/aprobar":
        run_id_hint = parts[1] if len(parts) > 1 else None
        _do_respond(token, chat_id, run_id_hint, "approve")
        return

    # ── /rechazar [id] ───────────────────────────────────────────────────────
    if cmd == "/rechazar":
        run_id_hint = parts[1] if len(parts) > 1 else None
        _do_respond(token, chat_id, run_id_hint, "cancel")
        return

    # ── /vetar [id] ──────────────────────────────────────────────────────────
    if cmd == "/vetar":
        run_id_hint = parts[1] if len(parts) > 1 else None
        pending = _find_pending()
        veto_pending = [p for p in pending if p["type"] == "veto_window"] or pending
        item = _resolve_pending_item(run_id_hint, veto_pending)
        if item is None:
            if not veto_pending:
                _tg_send(token, chat_id, "✅ No hay planes en ventana de veto.")
            else:
                lines = ["⚠️ Especifica el ID del plan a vetar:\n"]
                for p in veto_pending:
                    lines.append(f"• `{p['id'][:40]}` — {p['name']}")
                _tg_send(token, chat_id, "\n".join(lines))
            return
        if _write_approval(item["id"], "VETAR"):
            _edit_or_send(token, chat_id, item["id"],
                f"🛑 *Plan vetado*\n*Feature:* {item['name']}\nEl pipeline fue detenido.")
        else:
            _tg_send(token, chat_id, f"❌ Error al vetar `{item['id']}`.")
        return

    # ── /cambios [id] <feedback> ──────────────────────────────────────────────
    if cmd == "/cambios":
        if len(parts) < 2:
            _tg_send(token, chat_id,
                "⚠️ Uso: `/cambios [id] <feedback>`\n"
                "Ejemplo: `/cambios Añade autenticación OAuth al módulo de usuarios`")
            return
        pending = _find_pending()
        if len(parts) == 3:
            run_id_hint, feedback = parts[1], parts[2]
        elif len(parts) == 2:
            if len(pending) == 1:
                run_id_hint, feedback = None, parts[1]
            else:
                _tg_send(token, chat_id,
                    "⚠️ Hay varios pendientes. Formato: `/cambios <id> <feedback>`\n"
                    "Usa `/status` para ver los IDs.")
                return
        else:
            _tg_send(token, chat_id, "⚠️ Uso: `/cambios [id] <feedback>`")
            return

        item = _resolve_pending_item(run_id_hint, pending)
        if item is None:
            _handle_not_found(token, chat_id, run_id_hint, pending)
            return
        if _write_approval(item["id"], feedback):
            _edit_or_send(token, chat_id, item["id"],
                f"✏️ *Feedback enviado*\n"
                f"*Feature:* {item['name']}\n"
                f"_{feedback[:300]}_")
        else:
            _tg_send(token, chat_id, f"❌ Error al enviar feedback.")
        return

    # ── /intervenir <id> <texto> ──────────────────────────────────────────────
    if cmd == "/intervenir":
        if len(parts) < 3:
            _tg_send(token, chat_id,
                "⚡ *Intervención mid-flight*\n\n"
                "Uso: `/intervenir <id> <instrucción>`\n"
                "Ejemplo: `/intervenir 20260526_120000_login Usa bcrypt para las contraseñas`\n\n"
                "_La instrucción se inyecta en el próximo agente antes de llamar al LLM._\n"
                "Usa `/historial` para ver los IDs de runs activos.")
            return
        run_id  = parts[1].strip()
        instruc = parts[2].strip()
        if not instruc:
            _tg_send(token, chat_id, "⚠️ La instrucción no puede estar vacía.")
            return
        try:
            from tools.event_bus import post_intervention
            post_intervention(run_id, instruc)
            _tg_send(token, chat_id,
                f"⚡ *Intervención enviada*\n"
                f"*Run:* `{run_id[:40]}`\n"
                f"*Instrucción:* _{instruc[:300]}_\n\n"
                f"_El próximo agente la leerá antes de llamar al LLM._")
        except Exception as e:
            _tg_send(token, chat_id, f"❌ Error al enviar intervención: {e}")
        return

    # ── /feature <repo>: <nombre> [--lite|--lightning] ────────────────────────
    if cmd == "/feature":
        if len(parts) < 2:
            _tg_send(token, chat_id,
                "⚠️ *Uso:*\n"
                "`/feature <repo>: <nombre>`\n"
                "`/feature omni-erp: Login con Google --lite`\n"
                "`/feature omni-erp: Hotfix urgente --lightning`\n\n"
                "Usa `/repos` para ver los repositorios disponibles.")
            return
        rest = " ".join(parts[1:])
        if ":" not in rest:
            _tg_send(token, chat_id,
                "⚠️ Separa el repo y el nombre con `:`\n"
                "Ejemplo: `/feature omni-erp: Login con Google`")
            return

        repo_part, _, name_and_flags = rest.partition(":")
        repo_name = repo_part.strip()
        name_and_flags = name_and_flags.strip()

        # Detectar modo desde flags --lite / --lightning
        mode = _default_mode
        for flag in ("--lightning", "--lite", "--completo", "--auto"):
            if flag in name_and_flags:
                mode = flag.lstrip("-")
                name_and_flags = name_and_flags.replace(flag, "").strip()
                break

        feature_name = name_and_flags.strip()
        if not feature_name:
            _tg_send(token, chat_id, "⚠️ El nombre del feature no puede estar vacío.")
            return
        _launch_feature(token, chat_id, repo_name, feature_name, mode)
        return

    # Comando desconocido
    _tg_send(token, chat_id,
        f"❓ Comando no reconocido: `{cmd}`\n"
        "Usa /ayuda para ver los comandos disponibles.")


# ── Helpers ───────────────────────────────────────────────────────────────────

def _save_tg_msg_id(run_id: str, message_id: int) -> None:
    """Guarda el message_id de Telegram para poder editar el mensaje luego."""
    try:
        path = _runs_dir() / run_id / "tg_message_id.txt"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(str(message_id))
    except Exception:
        pass


def _load_tg_msg_id(run_id: str) -> int | None:
    try:
        path = _runs_dir() / run_id / "tg_message_id.txt"
        return int(path.read_text().strip()) if path.exists() else None
    except Exception:
        return None


def _edit_or_send(token: str, chat_id: str, run_id: str, text: str) -> None:
    """Edita el mensaje original de aprobación o envía uno nuevo si no existe."""
    msg_id = _load_tg_msg_id(run_id)
    if msg_id:
        _tg_edit_text(token, chat_id, msg_id, text)
    else:
        _tg_send(token, chat_id, text)


def _handle_not_found(token: str, chat_id: str,
                      run_id_hint: str | None, pending: list[dict]) -> None:
    if not pending:
        _tg_send(token, chat_id, "✅ No hay procesos pendientes.")
    elif run_id_hint:
        _tg_send(token, chat_id,
            f"❌ No encontré proceso con ID `{run_id_hint}`.\n"
            "Usa /status para ver los IDs disponibles.")
    else:
        lines = ["⚠️ Hay varios pendientes. Especifica el ID:\n"]
        for p in pending:
            lines.append(f"• `{p['id'][:40]}` — {p['name']}")
        _tg_send(token, chat_id, "\n".join(lines))


def _do_respond(token: str, chat_id: str,
                run_id_hint: str | None, action: str) -> None:
    pending = _find_pending()
    if not pending:
        _tg_send(token, chat_id, "✅ No hay aprobaciones pendientes.")
        return
    item = _resolve_pending_item(run_id_hint, pending)
    if item is None:
        _handle_not_found(token, chat_id, run_id_hint, pending)
        return
    resp_text = _RESP_MAP.get(item["type"], {}).get(action, action)
    if _write_approval(item["id"], resp_text):
        icon = "✅" if action == "approve" else "🛑"
        verb = "aprobado" if action == "approve" else "rechazado"
        _edit_or_send(token, chat_id, item["id"],
            f"{icon} *{item['name']}* — {verb}\n`{item['id'][:50]}`")
    else:
        _tg_send(token, chat_id, f"❌ Error al escribir respuesta.")


def _handle_callback(token: str, chat_id: str,
                     callback_query_id: str, data: str) -> None:
    """
    Maneja un callback de botón inline.
    Formatos: "approve:<run_id>", "reject:<run_id>", "veto:<run_id>"
    """
    try:
        action, run_id = data.split(":", 1)
    except ValueError:
        _tg_answer_callback(token, callback_query_id, "⚠️ Callback inválido")
        return

    pending = _find_pending()
    item = _resolve_pending_item(run_id, pending)

    if item is None:
        _tg_answer_callback(token, callback_query_id, "⚠️ Proceso no encontrado o ya respondido")
        return

    if action == "approve":
        resp_text = _RESP_MAP.get(item["type"], {}).get("approve", "CONTINUAR")
        if _write_approval(item["id"], resp_text):
            _tg_answer_callback(token, callback_query_id, "✅ Aprobado")
            _edit_or_send(token, chat_id, item["id"],
                f"✅ *{item['name']}* — aprobado\n`{item['id'][:50]}`")
        else:
            _tg_answer_callback(token, callback_query_id, "❌ Error al escribir aprobación")

    elif action in ("reject", "cancel"):
        resp_text = _RESP_MAP.get(item["type"], {}).get("cancel", "CANCELAR")
        if _write_approval(item["id"], resp_text):
            _tg_answer_callback(token, callback_query_id, "❌ Rechazado")
            _edit_or_send(token, chat_id, item["id"],
                f"❌ *{item['name']}* — rechazado\n`{item['id'][:50]}`")
        else:
            _tg_answer_callback(token, callback_query_id, "❌ Error")

    elif action == "veto":
        if _write_approval(item["id"], "VETAR"):
            _tg_answer_callback(token, callback_query_id, "🛑 Plan vetado")
            _edit_or_send(token, chat_id, item["id"],
                f"🛑 *{item['name']}* — vetado\nEl pipeline fue detenido.")
        else:
            _tg_answer_callback(token, callback_query_id, "❌ Error")
    else:
        _tg_answer_callback(token, callback_query_id, "❓ Acción desconocida")


def _launch_feature(
    token: str, chat_id: str,
    repo_name: str, feature_name: str, mode: str = "auto",
) -> None:
    try:
        from config import list_repos, RUNS_DIR as _RUNS_DIR

        available = [r["name"] for r in list_repos()]
        if repo_name not in available:
            repos_str = ", ".join(f"`{r}`" for r in available) or "ninguno"
            _tg_send(token, chat_id,
                f"❌ Repositorio `{repo_name}` no encontrado.\n"
                f"Disponibles: {repos_str}\n\nUsa /repos para ver la lista.")
            return

        feature_id = (
            f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_"
            f"{feature_name[:20].replace(' ', '_').lower()}"
        )
        fabrica_dir = Path(__file__).parent.parent
        cmd = [
            sys.executable, "cli.py", "new-feature",
            feature_name,
            "--repo", repo_name,
            "--mode", mode,
        ]
        run_dir = Path(str(_RUNS_DIR)) / feature_id
        run_dir.mkdir(parents=True, exist_ok=True)

        proc = subprocess.Popen(
            cmd,
            cwd=str(fabrica_dir),
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            env={**os.environ, "FEATURE_ID_OVERRIDE": feature_id},
        )
        (run_dir / "process.pid").write_text(str(proc.pid))

        mode_icons = {"auto": "🤖", "lite": "💡", "completo": "🔬", "lightning": "⚡"}
        _tg_send(token, chat_id,
            f"🚀 *Feature lanzado*\n"
            f"*Nombre:* {feature_name}\n"
            f"*Repo:* `{repo_name}`\n"
            f"*Modo:* {mode_icons.get(mode,'🔧')} `{mode}`\n"
            f"*ID:* `{feature_id}`\n\n"
            f"Te notificaré cuando esté listo o necesite aprobación.")

    except Exception as e:
        logger.exception("Bot Telegram: error lanzando feature: %s", e)
        _tg_send(token, chat_id, f"❌ Error al lanzar feature: {e}")


# ── Worker ────────────────────────────────────────────────────────────────────

class TelegramBotWorker:
    """Daemon thread de long-polling. Solo procesa mensajes del chat_id configurado."""

    def __init__(self, token: str, chat_id: str, stop_event: threading.Event):
        self.token      = token
        self.chat_id    = str(chat_id)
        self.stop_event = stop_event

    def _check_expired_veto_windows(self) -> None:
        """Auto-aprueba planes cuya ventana de veto ya expiró."""
        rd = _runs_dir()
        if not rd.exists():
            return
        now = datetime.now(timezone.utc)
        for run_dir in rd.iterdir():
            interrupt_file = run_dir / "pending_interrupt_type.txt"
            if not interrupt_file.exists():
                continue
            if interrupt_file.read_text().strip() != "veto_window":
                continue
            meta_path = run_dir / "metadata.json"
            if not meta_path.exists():
                continue
            try:
                meta = json.loads(meta_path.read_text())
                expires_str = meta.get("veto_expires", "")
                if not expires_str:
                    continue
                expires = datetime.fromisoformat(expires_str)
                if expires.tzinfo is None:
                    expires = expires.replace(tzinfo=timezone.utc)
                if now >= expires:
                    approval_file = run_dir / "pending_approval.txt"
                    if not approval_file.exists():
                        approval_file.write_text("CONTINUAR")
                        name = meta.get("feature_name", run_dir.name)
                        _tg_send(self.token, self.chat_id,
                            f"⏰ *Ventana de veto expirada — aprobado automáticamente*\n"
                            f"*Feature:* {name}\n"
                            f"El pipeline continúa sin intervención.")
                        logger.info("Bot: veto expirado auto-aprobado → %s", run_dir.name)
            except Exception as exc:
                logger.warning("Bot: error revisando veto %s: %s", run_dir.name, exc)

    def _process_update(self, update: dict) -> None:
        # Mensaje de texto (comandos)
        if "message" in update:
            msg       = update["message"]
            from_chat = str(msg.get("chat", {}).get("id", ""))
            if from_chat != self.chat_id:
                return
            # A1.1 — Whitelist de usuarios: aunque el chat_id sea correcto, solo
            # los user IDs autorizados pueden controlar la fábrica.
            user_id = msg.get("from", {}).get("id")
            if not _is_authorized_user(user_id):
                logger.warning(
                    "Telegram: usuario %s NO autorizado (chat_id correcto) — update ignorado",
                    user_id,
                )
                return
            text = msg.get("text", "").strip()
            if text.startswith("/"):
                _handle_command(self.token, self.chat_id, text)

        # Callback de botón inline
        elif "callback_query" in update:
            cb = update["callback_query"]
            from_chat = str(cb.get("message", {}).get("chat", {}).get("id", ""))
            if from_chat != self.chat_id:
                # Responder para quitar el spinner aunque no sea nuestro chat
                _tg_answer_callback(self.token, cb["id"], "⚠️ Chat no autorizado")
                return
            # A1.1 — Whitelist de usuarios también para callbacks de botones inline.
            user_id = cb.get("from", {}).get("id")
            if not _is_authorized_user(user_id):
                logger.warning(
                    "Telegram: usuario %s NO autorizado (chat_id correcto) — update ignorado",
                    user_id,
                )
                # Responder para quitar el spinner del botón
                _tg_answer_callback(self.token, cb["id"], "⚠️ Usuario no autorizado")
                return
            _handle_callback(
                self.token,
                self.chat_id,
                cb["id"],
                cb.get("data", ""),
            )

    def run(self) -> None:
        logger.info("Telegram bot: iniciando polling (chat_id=%s)", self.chat_id)
        # Registrar comandos en Telegram
        try:
            _tg_set_my_commands(self.token)
        except Exception:
            pass

        _tg_send(self.token, self.chat_id,
            "🏭 *Fábrica de Software online*\n"
            "Sistema listo. Usa /ayuda para ver los comandos.\n"
            "/status para ver aprobaciones pendientes.")

        offset = 0
        tick   = 0
        while not self.stop_event.is_set():
            updates, offset = _tg_get_updates(self.token, offset)
            for update in updates:
                try:
                    self._process_update(update)
                except Exception as exc:
                    logger.exception("Bot Telegram: error procesando update: %s", exc)
                    try:
                        _tg_send(self.token, self.chat_id, f"❌ Error interno: {exc}")
                    except Exception:
                        pass

            # Revisar veto expirados cada ~2 ciclos (≈60 s)
            tick += 1
            if tick % 2 == 0:
                try:
                    self._check_expired_veto_windows()
                except Exception as exc:
                    logger.warning("Bot: error check_expired_veto_windows: %s", exc)

        logger.info("Telegram bot: polling detenido")
