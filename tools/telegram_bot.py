"""
Bot de Telegram interactivo — Fábrica de Software.

Permite al Founder operar el pipeline desde Telegram:
  • Ver aprobaciones pendientes  → /status
  • Aprobar un plan              → /aprobar [id]
  • Rechazar / cancelar          → /rechazar [id]
  • Solicitar cambios con texto  → /cambios [id] <feedback>
  • Crear un nuevo feature       → /feature <repo>: <nombre>
  • Ver repos disponibles        → /repos
  • Ayuda                        → /ayuda

El bot usa long-polling (no requiere webhook ni IP pública).
Se arranca desde server.py en el lifespan de FastAPI.
"""
from __future__ import annotations

import json
import logging
import os
import subprocess
import sys
import threading
from datetime import datetime
from pathlib import Path

import httpx

logger = logging.getLogger(__name__)

# ── Mapas de tipos de interrupción ───────────────────────────────────────────

INTERRUPT_LABELS = {
    "project_roadmap_approval": "📐 Aprobación de Roadmap",
    "project_suggestions":      "💡 Sugerencias del PM",
    "checkpoint":               "🔔 Checkpoint",
    "qa_escalation":            "⚠️ Escalación QA",
    "stop_protocol":            "⛔ Stop Protocol",
    "veto_window":              "⏳ Ventana de Veto",
}

# Respuestas según tipo e intención (approve / cancel)
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
        "approve": "Plan aprobado. Pasa a ejecución.",  # A-02: debe coincidir con FRASE_APROBACION
        "cancel":  "CANCELAR",
    },
    "veto_window": {
        "approve": "CONTINUAR",
        "cancel":  "VETAR",
    },
}


# ── Helpers de filesystem ─────────────────────────────────────────────────────

def _runs_dir() -> Path:
    from tools.file_tools import RUNS_DIR
    return RUNS_DIR


def _find_pending() -> list[dict]:
    """Escanea RUNS_DIR buscando procesos que esperan aprobación humana."""
    pending: list[dict] = []
    rd = _runs_dir()
    if not rd.exists():
        return pending
    for run_dir in sorted(rd.iterdir()):
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
        })
    return pending


def _write_approval(run_id: str, response: str) -> bool:
    """Escribe la respuesta en pending_approval.txt para desbloquear el proceso."""
    run_dir = _runs_dir() / run_id
    if not run_dir.exists():
        return False
    (run_dir / "pending_approval.txt").write_text(response)
    logger.info("Bot Telegram: respuesta escrita para %s → %.40s", run_id, response)
    return True


def _resolve_pending_item(run_id_hint: str | None, pending: list[dict]) -> dict | None:
    """
    Resuelve cuál item pendiente corresponde al hint dado.
    Si hint es None y hay exactamente uno, lo devuelve.
    Soporta coincidencia parcial de ID.
    """
    if not pending:
        return None
    if run_id_hint is None:
        return pending[0] if len(pending) == 1 else None
    # Coincidencia exacta primero
    for p in pending:
        if p["id"] == run_id_hint:
            return p
    # Coincidencia parcial
    matches = [p for p in pending if run_id_hint.lower() in p["id"].lower()]
    return matches[0] if len(matches) == 1 else None


# ── Telegram API helpers ──────────────────────────────────────────────────────

def _tg_send(token: str, chat_id: str, text: str) -> None:
    """Envía mensaje Markdown. Falla silenciosamente."""
    try:
        httpx.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": chat_id, "text": text[:4096], "parse_mode": "Markdown"},
            timeout=10,
        )
    except Exception as exc:
        logger.warning("Bot Telegram: error enviando mensaje: %s", exc)


def _tg_get_updates(token: str, offset: int) -> tuple[list, int]:
    """Long-polling getUpdates. Timeout 30 s en Telegram, 35 s en httpx."""
    try:
        r = httpx.get(
            f"https://api.telegram.org/bot{token}/getUpdates",
            params={"offset": offset, "timeout": 30, "allowed_updates": ["message"]},
            timeout=35,
        )
        updates = r.json().get("result", [])
        if updates:
            offset = updates[-1]["update_id"] + 1
        return updates, offset
    except Exception as exc:
        logger.warning("Bot Telegram: error en getUpdates: %s", exc)
        return [], offset


# ── Procesador de comandos ────────────────────────────────────────────────────

_HELP_TEXT = (
    "🏭 *Fábrica de Software — Comandos disponibles*\n\n"
    "`/status` — Ver aprobaciones pendientes\n"
    "`/aprobar [id]` — Aprobar el plan/roadmap\n"
    "`/rechazar [id]` — Cancelar el plan\n"
    "`/vetar [id]` — Vetar un plan en ventana de veto automático\n"
    "`/cambios [id] <feedback>` — Solicitar cambios con texto libre\n"
    "`/feature <repo>: <nombre>` — Crear nuevo feature\n"
    "`/repos` — Ver repositorios disponibles\n"
    "`/ayuda` — Esta ayuda\n\n"
    "_Si hay solo un proceso pendiente, el `[id]` es opcional._"
)


def _handle_command(token: str, chat_id: str, text: str) -> None:
    """Despacha un mensaje recibido al handler correcto."""
    parts = text.strip().split(None, 2)
    cmd   = parts[0].lower().split("@")[0]   # quita @botname si existe

    if cmd in ("/ayuda", "/help", "/start"):
        _tg_send(token, chat_id, _HELP_TEXT)
        return

    # ── /status ──────────────────────────────────────────────────────────────
    if cmd == "/status":
        pending = _find_pending()
        if not pending:
            _tg_send(token, chat_id, "✅ No hay aprobaciones pendientes en este momento.")
            return
        lines = [f"⏳ *{len(pending)} proceso(s) esperando aprobación:*\n"]
        for p in pending:
            lines.append(
                f"{p['label']}\n"
                f"*{p['name']}*\n"
                f"`{p['id']}`\n"
            )
        lines.append("Usa `/aprobar`, `/rechazar` o `/cambios` para responder.")
        _tg_send(token, chat_id, "\n".join(lines))
        return

    # ── /repos ───────────────────────────────────────────────────────────────
    if cmd == "/repos":
        try:
            from config import list_repos
            repos = list_repos()
            if not repos:
                _tg_send(token, chat_id, "⚠️ No hay repositorios configurados en WORKSPACES_ROOT.")
                return
            lines = ["📁 *Repositorios disponibles:*\n"]
            for r in repos:
                lines.append(f"• `{r['name']}`")
            _tg_send(token, chat_id, "\n".join(lines))
        except Exception as e:
            _tg_send(token, chat_id, f"❌ Error obteniendo repos: {e}")
        return

    # ── /aprobar [id] ─────────────────────────────────────────────────────────
    if cmd == "/aprobar":
        run_id_hint = parts[1] if len(parts) > 1 else None
        _do_respond(token, chat_id, run_id_hint, "approve")
        return

    # ── /rechazar [id] ────────────────────────────────────────────────────────
    if cmd == "/rechazar":
        run_id_hint = parts[1] if len(parts) > 1 else None
        _do_respond(token, chat_id, run_id_hint, "cancel")
        return

    # ── /cambios [id] <feedback> ──────────────────────────────────────────────
    if cmd == "/cambios":
        if len(parts) < 2:
            _tg_send(token, chat_id,
                "⚠️ Uso: `/cambios [id] <tu feedback>`\n"
                "Ejemplo: `/cambios Necesito que incluyas autenticación OAuth`")
            return
        pending = _find_pending()
        # Determinar si parts[1] es un ID o el inicio del feedback
        # Heurística: si hay más de un pendiente O si parts[1] parece un run_id (tiene '_')
        if len(parts) == 3:
            # /cambios <id> <feedback>
            run_id_hint, feedback = parts[1], parts[2]
        elif len(parts) == 2:
            if len(pending) == 1:
                # Solo un pendiente → parts[1] es todo el feedback
                run_id_hint = None
                feedback    = parts[1]
            else:
                # Varios pendientes → parts[1] debe ser el ID
                run_id_hint = parts[1]
                feedback    = ""
                if not feedback:
                    _tg_send(token, chat_id,
                        "⚠️ Hay varios procesos pendientes. Especifica ID y feedback:\n"
                        "`/cambios <id> <feedback>`\n\nUsa `/status` para ver los IDs.")
                    return
        else:
            _tg_send(token, chat_id, "⚠️ Uso: `/cambios [id] <tu feedback>`")
            return

        item = _resolve_pending_item(run_id_hint, pending)
        if item is None:
            if not pending:
                _tg_send(token, chat_id, "✅ No hay procesos pendientes.")
            elif run_id_hint:
                _tg_send(token, chat_id,
                    f"❌ No encontré proceso con ID `{run_id_hint}`.\n"
                    "Usa `/status` para ver los IDs disponibles.")
            else:
                lines = ["⚠️ Hay varios pendientes, especifica el ID:\n"]
                for p in pending:
                    lines.append(f"• `{p['id'][:40]}` — {p['name']}")
                _tg_send(token, chat_id, "\n".join(lines))
            return

        if _write_approval(item["id"], feedback):
            _tg_send(token, chat_id,
                f"✏️ *Cambios enviados* a *{item['name']}*\n"
                f"Feedback: _{feedback[:300]}_")
        else:
            _tg_send(token, chat_id, f"❌ Error al escribir respuesta para `{item['id']}`.")
        return

    # ── /vetar [id] ───────────────────────────────────────────────────────────
    if cmd == "/vetar":
        run_id_hint = parts[1] if len(parts) > 1 else None
        pending = _find_pending()
        # Filtrar solo los que son veto_window
        veto_pending = [p for p in pending if p["type"] == "veto_window"]
        if not veto_pending:
            # Intentar con todos los pendientes si no hay específicos de veto_window
            veto_pending = pending
        item = _resolve_pending_item(run_id_hint, veto_pending)
        if item is None:
            if not veto_pending:
                _tg_send(token, chat_id, "✅ No hay planes en ventana de veto en este momento.")
            else:
                lines = ["⚠️ Especifica el ID del plan a vetar:\n"]
                for p in veto_pending:
                    lines.append(f"• `{p['id'][:40]}` — {p['name']}")
                _tg_send(token, chat_id, "\n".join(lines))
            return
        if _write_approval(item["id"], "VETAR"):
            _tg_send(token, chat_id,
                f"🛑 *Plan vetado*: *{item['name']}*\n"
                f"El pipeline fue detenido.")
        else:
            _tg_send(token, chat_id, f"❌ Error al vetar `{item['id']}`.")
        return

    # ── /feature <repo>: <nombre> ─────────────────────────────────────────────
    if cmd == "/feature":
        if len(parts) < 2:
            _tg_send(token, chat_id,
                "⚠️ Uso: `/feature <repo>: <nombre del feature>`\n"
                "Ejemplo: `/feature omni-erp: Login con Google`\n\n"
                "Usa `/repos` para ver los repositorios disponibles.")
            return
        rest = " ".join(parts[1:])
        if ":" not in rest:
            _tg_send(token, chat_id,
                "⚠️ Debes especificar el repositorio separado con `:`\n"
                "Ejemplo: `/feature omni-erp: Login con Google`\n\n"
                "Usa `/repos` para ver los disponibles.")
            return
        repo_name, _, feature_name = rest.partition(":")
        repo_name    = repo_name.strip()
        feature_name = feature_name.strip()
        if not feature_name:
            _tg_send(token, chat_id, "⚠️ El nombre del feature no puede estar vacío.")
            return
        _launch_feature(token, chat_id, repo_name, feature_name)
        return

    # Comando desconocido
    _tg_send(token, chat_id,
        f"❓ Comando no reconocido: `{cmd}`\n"
        "Usa `/ayuda` para ver los comandos disponibles.")


def _do_respond(token: str, chat_id: str,
                run_id_hint: str | None, action: str) -> None:
    """Aprueba (approve) o cancela (cancel) un proceso pendiente."""
    pending = _find_pending()

    if not pending:
        _tg_send(token, chat_id, "✅ No hay aprobaciones pendientes.")
        return

    item = _resolve_pending_item(run_id_hint, pending)
    if item is None:
        if run_id_hint:
            matches = [p for p in pending if run_id_hint.lower() in p["id"].lower()]
            if len(matches) > 1:
                _tg_send(token, chat_id,
                    f"⚠️ ID ambiguo — {len(matches)} coincidencias.\n"
                    "Sé más específico o usa `/status` para ver los IDs.")
            else:
                _tg_send(token, chat_id,
                    f"❌ No encontré proceso con ID `{run_id_hint}`.\n"
                    "Usa `/status` para ver los IDs disponibles.")
        else:
            lines = ["⚠️ Hay varios procesos pendientes, especifica el ID:\n"]
            for p in pending:
                lines.append(f"• `{p['id'][:40]}` — {p['name']}")
            _tg_send(token, chat_id, "\n".join(lines))
        return

    resp_text = _RESP_MAP.get(item["type"], {}).get(action, action)
    if _write_approval(item["id"], resp_text):
        icon = "✅" if action == "approve" else "❌"
        verb = "aprobado" if action == "approve" else "rechazado/cancelado"
        _tg_send(token, chat_id,
            f"{icon} *{item['name']}* {verb}.\n"
            f"Proceso: `{item['id'][:50]}`")
    else:
        _tg_send(token, chat_id, f"❌ Error al escribir respuesta para `{item['id']}`.")


def _launch_feature(token: str, chat_id: str,
                    repo_name: str, feature_name: str) -> None:
    """Lanza un nuevo feature vía subprocess igual que la UI web."""
    try:
        from config import list_repos, RUNS_DIR

        available = [r["name"] for r in list_repos()]
        if repo_name not in available:
            repos_str = ", ".join(f"`{r}`" for r in available) or "ninguno"
            _tg_send(token, chat_id,
                f"❌ Repositorio `{repo_name}` no encontrado.\n"
                f"Disponibles: {repos_str}")
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
            "--mode", "auto",
        ]
        run_dir = Path(str(RUNS_DIR)) / feature_id
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

        _tg_send(token, chat_id,
            f"🚀 *Feature iniciado*\n"
            f"*Nombre:* {feature_name}\n"
            f"*Repo:* `{repo_name}`\n"
            f"*ID:* `{feature_id}`\n\n"
            f"Te notificaré cuando esté listo.")

    except Exception as e:
        logger.exception("Bot Telegram: error lanzando feature: %s", e)
        _tg_send(token, chat_id, f"❌ Error al lanzar feature: {e}")


# ── Worker ────────────────────────────────────────────────────────────────────

class TelegramBotWorker:
    """
    Worker de polling. Corre en un daemon thread.
    Solo procesa mensajes del chat_id configurado (seguridad básica).
    """

    def __init__(self, token: str, chat_id: str, stop_event: threading.Event):
        self.token      = token
        self.chat_id    = str(chat_id)
        self.stop_event = stop_event

    def _check_expired_veto_windows(self) -> None:
        """Auto-aprueba planes cuya ventana de veto ya expiró."""
        from datetime import datetime, timezone
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
            # Leer veto_expires de metadata
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
                    # Ventana expirada → auto-aprobar
                    approval_file = run_dir / "pending_approval.txt"
                    if not approval_file.exists():
                        approval_file.write_text("CONTINUAR")
                        name = meta.get("feature_name", run_dir.name)
                        _tg_send(self.token, self.chat_id,
                            f"⏰ *Ventana de veto expirada* — aprobado automáticamente\n"
                            f"*Feature:* {name}")
                        logger.info("Bot: veto expirado auto-aprobado → %s", run_dir.name)
            except Exception as exc:
                logger.warning("Bot: error revisando veto expirado %s: %s", run_dir.name, exc)

    def run(self) -> None:
        logger.info("Telegram bot: iniciando polling (chat_id=%s)", self.chat_id)
        _tg_send(self.token, self.chat_id,
            "🏭 *Fábrica de Software online*\n"
            "Bot activo. Usa `/ayuda` para ver los comandos disponibles.")
        offset = 0
        tick = 0
        while not self.stop_event.is_set():
            updates, offset = _tg_get_updates(self.token, offset)
            for update in updates:
                msg       = update.get("message", {})
                from_chat = str(msg.get("chat", {}).get("id", ""))
                if from_chat != self.chat_id:
                    continue
                text = msg.get("text", "").strip()
                if not text.startswith("/"):
                    continue
                try:
                    _handle_command(self.token, self.chat_id, text)
                except Exception as exc:
                    logger.exception("Bot Telegram: error procesando '%s': %s", text, exc)
                    _tg_send(self.token, self.chat_id, f"❌ Error interno: {exc}")
            # Revisar veto expirados cada ~2 ciclos de polling (≈60 s)
            tick += 1
            if tick % 2 == 0:
                try:
                    self._check_expired_veto_windows()
                except Exception as exc:
                    logger.warning("Bot: error en check_expired_veto_windows: %s", exc)
        logger.info("Telegram bot: polling detenido")
