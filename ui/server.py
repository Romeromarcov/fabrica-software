"""
Servidor web de la Fábrica de Software — Omni ERP.
Arrancar: uvicorn ui.server:app --reload --port 7860
"""
from __future__ import annotations
import sys
import json
import asyncio
import subprocess
import logging
from contextlib import asynccontextmanager
from pathlib import Path
from datetime import datetime
from typing import AsyncIterator

import os
import base64
import threading
import aiofiles
from fastapi import FastAPI, Request, Form, HTTPException, UploadFile, File
from typing import List
from fastapi.responses import HTMLResponse, JSONResponse, StreamingResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.middleware.sessions import SessionMiddleware

# Asegurar imports del orquestador
sys.path.insert(0, str(Path(__file__).parent.parent))

from config import RUNS_DIR, PRICES, MODEL_PM, MODEL_STANDARD, MODEL_FAST, DB_PATH, list_repos, FABRICA_DIR, RBAC_ENABLED
from ui.config_store import ConfigStore

# ── Proveedores IA personalizados ─────────────────────────────────────────────
_CUSTOM_PROVIDERS_PATH = FABRICA_DIR / "data" / "custom_providers.json"


def _load_custom_providers() -> list[dict]:
    try:
        if _CUSTOM_PROVIDERS_PATH.exists():
            return json.loads(_CUSTOM_PROVIDERS_PATH.read_text(encoding="utf-8")) or []
    except Exception:
        pass
    return []


def _save_custom_providers(providers: list[dict]) -> None:
    _CUSTOM_PROVIDERS_PATH.parent.mkdir(exist_ok=True)
    _CUSTOM_PROVIDERS_PATH.write_text(
        json.dumps(providers, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)


# ── C-03: Basic Auth opcional ─────────────────────────────────────────────────

class _BasicAuthMiddleware(BaseHTTPMiddleware):
    """Protege toda la UI con usuario/contraseña si UI_USERNAME y UI_PASSWORD están definidos."""
    def __init__(self, app, username: str, password: str):
        super().__init__(app)
        self._creds = base64.b64encode(f"{username}:{password}".encode()).decode()

    async def dispatch(self, request, call_next):
        # Permitir el health-check sin auth para Docker
        if request.url.path in ("/health", "/favicon.ico"):
            return await call_next(request)
        auth = request.headers.get("Authorization", "")
        if auth.startswith("Basic ") and auth[6:] == self._creds:
            return await call_next(request)
        return Response(
            "Acceso no autorizado — configura UI_USERNAME y UI_PASSWORD en .env",
            status_code=401,
            headers={"WWW-Authenticate": 'Basic realm="Fábrica de Software"'},
        )


class _RBACMiddleware(BaseHTTPMiddleware):
    """
    IX-1: Si RBAC_ENABLED, todas las rutas protegidas requieren sesión activa.
    Las rutas públicas (login, static, auth) están excluidas.
    """
    _PUBLIC = {
        "/login", "/login/setup", "/register", "/logout",
        "/auth/github", "/auth/callback", "/health", "/favicon.ico",
    }
    _PUBLIC_PREFIXES = ("/static/",)

    async def dispatch(self, request, call_next):
        if not RBAC_ENABLED:
            return await call_next(request)
        path = request.url.path
        if path in self._PUBLIC or any(path.startswith(p) for p in self._PUBLIC_PREFIXES):
            return await call_next(request)
        if not request.session.get("user_id"):
            return RedirectResponse(f"/login?next={path}")
        return await call_next(request)


# ── Scheduler de noticias ─────────────────────────────────────────────────────

_news_scheduler    = None   # instancia global para poder reconfigurar sin reiniciar
_audit_scheduler   = None   # scheduler periódico de auditoría de codebase
_tg_bot_stop_event = None   # threading.Event para detener el polling del bot
_tg_bot_thread     = None   # daemon thread del bot de Telegram


def _start_news_scheduler():
    """Arranca APScheduler con el reporte diario de noticias según NEWS_AGENT_HOUR."""
    global _news_scheduler
    try:
        from apscheduler.schedulers.background import BackgroundScheduler
        from apscheduler.triggers.cron import CronTrigger
        from tools.news_agent import run_daily_reports
        from config import NEWS_AGENT_ENABLED, NEWS_AGENT_HOUR

        _news_scheduler = BackgroundScheduler(timezone="America/Caracas")

        if NEWS_AGENT_ENABLED:
            _news_scheduler.add_job(
                run_daily_reports,
                trigger=CronTrigger(hour=NEWS_AGENT_HOUR, minute=0),
                id="daily_news_report",
                name="Reporte Diario de Noticias",
                replace_existing=True,
                misfire_grace_time=3600,
            )
            logger.info(
                "Scheduler de noticias iniciado — reporte diario a las %02d:00 (America/Caracas)",
                NEWS_AGENT_HOUR,
            )
        else:
            logger.info("Scheduler de noticias desactivado (NEWS_AGENT_ENABLED=false)")

        _news_scheduler.start()
        return _news_scheduler

    except ImportError:
        logger.warning("APScheduler no instalado — scheduler de noticias desactivado")
        return None
    except Exception as e:
        logger.exception("Error al iniciar scheduler de noticias: %s", e)
        return None


def _reschedule_news(enabled: bool, hour: int) -> None:
    """Reconfigura el job de noticias sin reiniciar el proceso."""
    global _news_scheduler
    if _news_scheduler is None:
        return
    try:
        from apscheduler.triggers.cron import CronTrigger
        from tools.news_agent import run_daily_reports

        try:
            _news_scheduler.remove_job("daily_news_report")
        except Exception:
            pass  # El job puede no existir si el agente arrancó desactivado
        if enabled:
            _news_scheduler.add_job(
                run_daily_reports,
                trigger=CronTrigger(hour=hour, minute=0),
                id="daily_news_report",
                name="Reporte Diario de Noticias",
                replace_existing=True,
                misfire_grace_time=3600,
            )
            logger.info("Scheduler reconfigurado — próximo disparo a las %02d:00", hour)
    except Exception as e:
        logger.exception("Error al reconfigurar scheduler: %s", e)


def _start_auditor_scheduler():
    """Arranca APScheduler con la auditoría semanal de codebase según AUDITOR_WEEKDAY/HOUR."""
    global _audit_scheduler
    try:
        from apscheduler.schedulers.background import BackgroundScheduler
        from apscheduler.triggers.cron import CronTrigger
        from tools.codebase_auditor import run_audit

        cfg_raw = store.load(masked=False)
        enabled  = cfg_raw.get("AUDITOR_ENABLED", "true") == "true"
        weekday  = int(cfg_raw.get("AUDITOR_WEEKDAY", "0"))
        hour     = int(cfg_raw.get("AUDITOR_HOUR", "7"))

        _audit_scheduler = BackgroundScheduler(timezone="America/Caracas")

        if enabled:
            _audit_scheduler.add_job(
                run_audit,
                trigger=CronTrigger(day_of_week=weekday, hour=hour, minute=0),
                id="codebase_audit",
                name="Auditoría Periódica de Codebase",
                replace_existing=True,
                misfire_grace_time=3600,
            )
            _WEEKDAYS = ["lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo"]
            logger.info(
                "Scheduler de auditoría iniciado — cada %s a las %02d:00 (America/Caracas)",
                _WEEKDAYS[weekday], hour,
            )
        else:
            logger.info("Scheduler de auditoría desactivado (AUDITOR_ENABLED=false)")

        _audit_scheduler.start()
        return _audit_scheduler

    except ImportError:
        logger.warning("APScheduler no instalado — scheduler de auditoría desactivado")
        return None
    except Exception as e:
        logger.exception("Error al iniciar scheduler de auditoría: %s", e)
        return None


def _reschedule_auditor(enabled: bool, weekday: int, hour: int) -> None:
    """Reconfigura el job de auditoría sin reiniciar el proceso."""
    global _audit_scheduler
    if _audit_scheduler is None:
        return
    try:
        from apscheduler.triggers.cron import CronTrigger
        from tools.codebase_auditor import run_audit

        try:
            _audit_scheduler.remove_job("codebase_audit")
        except Exception:
            pass
        if enabled:
            _audit_scheduler.add_job(
                run_audit,
                trigger=CronTrigger(day_of_week=weekday, hour=hour, minute=0),
                id="codebase_audit",
                name="Auditoría Periódica de Codebase",
                replace_existing=True,
                misfire_grace_time=3600,
            )
            logger.info(
                "Auditor reconfigurado — próximo disparo día %d a las %02d:00", weekday, hour
            )
    except Exception as e:
        logger.exception("Error al reconfigurar scheduler de auditoría: %s", e)


def _start_telegram_bot() -> None:
    """Arranca el bot de Telegram interactivo en un daemon thread."""
    global _tg_bot_stop_event, _tg_bot_thread
    cfg = store.load(masked=False)
    token   = cfg.get("TELEGRAM_BOT_TOKEN", "")
    chat_id = cfg.get("TELEGRAM_CHAT_ID", "")
    if not token or not chat_id:
        logger.info("Telegram bot: no configurado (falta BOT_TOKEN o CHAT_ID) — omitiendo")
        return
    try:
        from tools.telegram_bot import TelegramBotWorker
        _tg_bot_stop_event = threading.Event()
        worker = TelegramBotWorker(token, chat_id, _tg_bot_stop_event)
        _tg_bot_thread = threading.Thread(
            target=worker.run, daemon=True, name="telegram-bot-polling"
        )
        _tg_bot_thread.start()
        logger.info("Telegram bot: polling iniciado (chat_id=%s)", chat_id)
    except Exception as e:
        logger.exception("Error al iniciar Telegram bot: %s", e)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # ── Startup ──────────────────────────────────────────────────────────────
    scheduler = _start_news_scheduler()
    _start_auditor_scheduler()
    _start_telegram_bot()
    yield
    # ── Shutdown ─────────────────────────────────────────────────────────────
    if scheduler and scheduler.running:
        scheduler.shutdown(wait=False)
        logger.info("Scheduler de noticias detenido")
    if _audit_scheduler and _audit_scheduler.running:
        _audit_scheduler.shutdown(wait=False)
        logger.info("Scheduler de auditoría detenido")
    if _tg_bot_stop_event:
        _tg_bot_stop_event.set()
        logger.info("Telegram bot: señal de parada enviada")


# ── App ───────────────────────────────────────────────────────────────────────
app = FastAPI(title="Fábrica de Software", docs_url=None, redoc_url=None, lifespan=lifespan)

# P0-B: SessionMiddleware (obligatorio antes de BasicAuth y rutas OAuth)
from config import GITHUB_OAUTH_SECRET
app.add_middleware(SessionMiddleware, secret_key=GITHUB_OAUTH_SECRET, session_cookie="fabrica_session")

# IX-1: RBAC middleware (activo solo si RBAC_ENABLED=true)
app.add_middleware(_RBACMiddleware)

_ui_user = os.getenv("UI_USERNAME", "")
_ui_pass = os.getenv("UI_PASSWORD", "")
if _ui_user and _ui_pass and not RBAC_ENABLED:
    # BasicAuth solo si RBAC está desactivado (son mutuamente excluyentes)
    app.add_middleware(_BasicAuthMiddleware, username=_ui_user, password=_ui_pass)
    logger.info("UI: Basic Auth habilitado para usuario '%s'", _ui_user)

_UI_DIR = Path(__file__).parent
_STATIC_DIR = _UI_DIR / "static"
_STATIC_DIR.mkdir(exist_ok=True)   # BUG-019: crea el dir si no existe
app.mount("/static", StaticFiles(directory=_STATIC_DIR), name="static")
templates = Jinja2Templates(directory=_UI_DIR / "templates")
store = ConfigStore()

# ── IX-1: RBAC helpers ───────────────────────────────────────────────────────

def _get_current_user(request: Request) -> dict | None:
    """Devuelve el usuario de sesión activo o None."""
    if not RBAC_ENABLED:
        return None
    user_id = request.session.get("user_id")
    if not user_id:
        return None
    try:
        from tools.auth_manager import get_user_by_id
        return get_user_by_id(user_id)
    except Exception:
        return None


def _base_ctx(request: Request, **extra) -> dict:
    """Contexto base para todos los templates (incluye current_user para la sidebar)."""
    return {"current_user": _get_current_user(request), "rbac_enabled": RBAC_ENABLED, **extra}


def _require_perm(request: Request, action: str) -> dict:
    """
    Verifica que el usuario tenga permiso para la acción.
    Si RBAC está desactivado, devuelve un usuario virtual con rol owner.
    Lanza HTTPException 403 si no tiene permiso.
    """
    if not RBAC_ENABLED:
        return {"role": "owner", "id": 0, "display_name": "Admin"}
    user = _get_current_user(request)
    if not user:
        raise HTTPException(status_code=302, headers={"Location": "/login"})
    from tools.auth_manager import can
    if not can(user, action):
        raise HTTPException(status_code=403, detail="Permiso insuficiente para esta acción")
    return user


# ── IX-1: Rutas de autenticación ─────────────────────────────────────────────

@app.get("/login", response_class=HTMLResponse)
async def login_page(request: Request, next: str = "/", error: str = "", success: str = ""):
    if RBAC_ENABLED and request.session.get("user_id"):
        return RedirectResponse("/")  # ya autenticado
    try:
        from tools.auth_manager import ensure_owner_exists
        no_users = not ensure_owner_exists()
    except Exception:
        no_users = False
    from config import GITHUB_OAUTH_ENABLED
    return templates.TemplateResponse(request, "login.html", {
        "mode": "login",
        "error": error,
        "success": success,
        "no_users": no_users,
        "github_oauth_enabled": GITHUB_OAUTH_ENABLED,
        "current_user": None,
    })


@app.post("/login")
async def login_submit(
    request: Request,
    email: str = Form(...),
    password: str = Form(...),
):
    from tools.auth_manager import authenticate
    user = authenticate(email.strip(), password)
    if not user:
        return templates.TemplateResponse(request, "login.html", {
            "mode": "login", "current_user": None,
            "error": "Email o contraseña incorrectos.",
            "no_users": False,
            "github_oauth_enabled": False,
        })
    request.session["user_id"]      = user["id"]
    request.session["user_role"]    = user["role"]
    request.session["display_name"] = user["display_name"]
    next_url = request.query_params.get("next", "/")
    return RedirectResponse(next_url, status_code=303)


@app.post("/login/setup")
async def login_setup(
    request: Request,
    email: str = Form(...),
    display_name: str = Form(...),
    password: str = Form(...),
):
    """Crea el primer usuario owner (solo si no hay ninguno)."""
    from tools.auth_manager import list_users, create_user
    if list_users():
        raise HTTPException(400, "Ya hay usuarios registrados")
    if len(password) < 8:
        raise HTTPException(400, "La contraseña debe tener mínimo 8 caracteres")
    user = create_user(email.strip(), display_name.strip(), role="owner", password=password)
    request.session["user_id"]      = user["id"]
    request.session["user_role"]    = "owner"
    request.session["display_name"] = user["display_name"]
    return RedirectResponse("/", status_code=303)


@app.get("/logout")
async def logout(request: Request):
    request.session.clear()
    if RBAC_ENABLED:
        return RedirectResponse("/login?success=Sesión+cerrada+correctamente")
    return RedirectResponse("/")


@app.get("/register", response_class=HTMLResponse)
async def register_page(request: Request, token: str = ""):
    """Registro via token de invitación."""
    from tools.auth_manager import consume_invite_token
    invite = consume_invite_token(token) if token else None
    if not invite:
        return templates.TemplateResponse(request, "login.html", {
            "mode": "login", "current_user": None,
            "error": "Enlace de invitación inválido o expirado.",
            "no_users": False, "github_oauth_enabled": False,
        })
    return templates.TemplateResponse(request, "login.html", {
        "mode":          "register",
        "invite_token":  token,
        "prefill_email": invite["email"],
        "current_user":  None,
    })


@app.post("/register")
async def register_submit(
    request: Request,
    token: str = Form(...),
    email: str = Form(...),
    display_name: str = Form(...),
    password: str = Form(...),
):
    from tools.auth_manager import consume_invite_token, create_user, get_user_by_email
    invite = consume_invite_token(token)
    if not invite:
        raise HTTPException(400, "Token de invitación inválido o ya usado")
    if len(password) < 8:
        raise HTTPException(400, "La contraseña debe tener mínimo 8 caracteres")
    existing = get_user_by_email(email.strip())
    if existing:
        # Actualizar password si ya existe (re-registro)
        from tools.auth_manager import update_user
        update_user(existing["id"], password=password, display_name=display_name.strip())
        user = existing
    else:
        user = create_user(email.strip(), display_name.strip(), invite["role"], password=password)
    request.session["user_id"]      = user["id"]
    request.session["user_role"]    = user["role"]
    request.session["display_name"] = user["display_name"]
    return RedirectResponse("/", status_code=303)


# ── IX-1: Admin de usuarios (solo owners) ────────────────────────────────────

@app.get("/admin/users", response_class=HTMLResponse)
async def admin_users_page(request: Request, invite_link: str = ""):
    _require_perm(request, "manage_users")
    from tools.auth_manager import list_users, PERMISSIONS

    permissions_matrix = [
        ("Ver dashboard y features",  {"owner", "developer", "viewer"}),
        ("Lanzar features",           {"owner", "developer"}),
        ("Aprobar planes",            {"owner", "developer"}),
        ("Intervenir mid-flight",     {"owner", "developer"}),
        ("Deploy a Railway",          {"owner"}),
        ("Configuración del sistema", {"owner"}),
        ("Crear/editar proyectos",    {"owner"}),
        ("Gestionar usuarios",        {"owner"}),
    ]

    user = _get_current_user(request)
    return templates.TemplateResponse(request, "admin_users.html", {
        **_base_ctx(request),
        "users":              list_users(),
        "current_user_id":    user["id"] if user else 0,
        "permissions_matrix": permissions_matrix,
        "invite_link":        invite_link,
        "active_page":        "config",
    })


@app.post("/admin/users/invite")
async def admin_invite_user(
    request: Request,
    email: str = Form(...),
    role: str = Form("viewer"),
):
    user = _require_perm(request, "manage_users")
    from tools.auth_manager import create_invite_token
    token = create_invite_token(email.strip(), role, user["id"])
    base_url = str(request.base_url).rstrip("/")
    invite_url = f"{base_url}/register?token={token}"
    return RedirectResponse(f"/admin/users?invite_link={invite_url}", status_code=303)


@app.post("/admin/users/update")
async def admin_update_user(
    request: Request,
    user_id: int = Form(...),
    display_name: str = Form(...),
    role: str = Form("viewer"),
    password: str = Form(""),
):
    _require_perm(request, "manage_users")
    from tools.auth_manager import update_user
    kwargs: dict = {"display_name": display_name, "role": role}
    if password:
        kwargs["password"] = password
    update_user(user_id, **kwargs)
    return RedirectResponse("/admin/users", status_code=303)


@app.post("/admin/users/{user_id}/deactivate")
async def admin_deactivate_user(request: Request, user_id: int):
    _require_perm(request, "manage_users")
    from tools.auth_manager import deactivate_user
    deactivate_user(user_id)
    return JSONResponse({"ok": True})


@app.post("/admin/users/{user_id}/activate")
async def admin_activate_user(request: Request, user_id: int):
    _require_perm(request, "manage_users")
    from tools.auth_manager import update_user
    update_user(user_id, active=1)
    return JSONResponse({"ok": True})


# ── IX-2: Service Worker y Push Notifications ─────────────────────────────────

@app.post("/api/push/subscribe")
async def push_subscribe(request: Request):
    """Guarda la suscripción push del cliente para notificaciones futuras."""
    try:
        sub = await request.json()
    except Exception:
        raise HTTPException(400, "Body JSON inválido")
    # Guardar en archivo (simple, sin DB)
    sub_dir = RUNS_DIR.parent / "push_subscriptions"
    sub_dir.mkdir(parents=True, exist_ok=True)
    import hashlib as _hl
    sub_id = _hl.md5(sub.get("endpoint", "").encode()).hexdigest()[:16]
    (sub_dir / f"{sub_id}.json").write_text(
        json.dumps(sub, ensure_ascii=False), encoding="utf-8"
    )
    return JSONResponse({"ok": True})


# ── P0-B: GitHub OAuth 2.0 ───────────────────────────────────────────────────

def _get_oauth_client():
    """Construye el cliente OAuth de GitHub (lazy, para no fallar si authlib no está instalado)."""
    from config import GITHUB_CLIENT_ID, GITHUB_CLIENT_SECRET, GITHUB_OAUTH_CALLBACK
    try:
        from authlib.integrations.starlette_client import OAuth as _OAuth
        _oauth = _OAuth()
        _oauth.register(
            name="github",
            client_id=GITHUB_CLIENT_ID,
            client_secret=GITHUB_CLIENT_SECRET,
            access_token_url="https://github.com/login/oauth/access_token",
            access_token_params=None,
            authorize_url="https://github.com/login/oauth/authorize",
            authorize_params=None,
            api_base_url="https://api.github.com/",
            client_kwargs={"scope": "repo read:user"},
        )
        return _oauth.github, GITHUB_OAUTH_CALLBACK
    except ImportError:
        return None, None


@app.get("/auth/github")
async def auth_github(request: Request):
    """Inicia el flujo OAuth con GitHub."""
    from config import GITHUB_OAUTH_ENABLED
    if not GITHUB_OAUTH_ENABLED:
        return JSONResponse(
            {"error": "GitHub OAuth no configurado. Agrega GITHUB_CLIENT_ID y GITHUB_CLIENT_SECRET al .env."},
            status_code=400,
        )
    client, callback_url = _get_oauth_client()
    if client is None:
        return JSONResponse({"error": "authlib no instalado. Ejecuta: pip install authlib"}, status_code=500)
    return await client.authorize_redirect(request, callback_url)


@app.get("/auth/callback")
async def auth_callback(request: Request):
    """Callback de GitHub OAuth — guarda el token en sesión y en ConfigStore."""
    from config import GITHUB_OAUTH_ENABLED
    if not GITHUB_OAUTH_ENABLED:
        return RedirectResponse("/")

    client, _ = _get_oauth_client()
    if client is None:
        return RedirectResponse("/?github_error=authlib_missing")

    try:
        token = await client.authorize_access_token(request)
    except Exception as exc:
        logger.warning("GitHub OAuth callback error: %s", exc)
        return RedirectResponse(f"/?github_error=auth_failed")

    # Obtener perfil del usuario
    github_token = token.get("access_token", "")
    github_login = ""
    github_name  = ""
    try:
        resp = await client.get("user", token=token)
        user_data  = resp.json()
        github_login = user_data.get("login", "")
        github_name  = user_data.get("name") or github_login
    except Exception as exc:
        logger.warning("GitHub OAuth: no se pudo obtener perfil: %s", exc)

    # Guardar en sesión (server-side, firmada con itsdangerous)
    request.session["github_token"]  = github_token
    request.session["github_login"]  = github_login
    request.session["github_name"]   = github_name

    # IX-1: Si RBAC activo, crear o recuperar el usuario de GitHub
    if RBAC_ENABLED and github_login:
        try:
            from tools.auth_manager import authenticate_or_create_github
            rbac_user = authenticate_or_create_github(
                github_login,
                github_name or github_login,
                email=f"{github_login}@github.oauth",
            )
            request.session["user_id"]      = rbac_user["id"]
            request.session["user_role"]    = rbac_user["role"]
            request.session["display_name"] = rbac_user.get("display_name", github_login)
        except Exception as exc:
            logger.warning("RBAC: no se pudo autenticar usuario GitHub %s: %s", github_login, exc)

    # Guardar en ConfigStore (→ .env) Y en os.environ para la sesión actual
    # git_tools.py llama os.getenv("GITHUB_TOKEN") en runtime, así lo ve inmediatamente
    if github_token:
        store.save({"GITHUB_TOKEN": github_token, "GITHUB_ACTOR": github_login})
        os.environ["GITHUB_TOKEN"] = github_token
        if github_login:
            os.environ["GITHUB_ACTOR"] = github_login
        logger.info("GitHub OAuth: token guardado para @%s", github_login)

    return RedirectResponse("/?github_connected=1")


@app.get("/auth/logout")
async def auth_logout(request: Request):
    """Limpia la sesión de GitHub."""
    request.session.pop("github_token", None)
    request.session.pop("github_login", None)
    request.session.pop("github_name",  None)
    return RedirectResponse("/?github_disconnected=1")


@app.get("/api/github/status")
async def github_status(request: Request):
    """Estado de la conexión GitHub: login, scopes, repos disponibles."""
    from config import GITHUB_OAUTH_ENABLED, GITHUB_TOKEN
    token  = request.session.get("github_token") or GITHUB_TOKEN or ""
    login  = request.session.get("github_login", "")
    name   = request.session.get("github_name",  "")
    return JSONResponse({
        "oauth_enabled":  GITHUB_OAUTH_ENABLED,
        "connected":      bool(token),
        "login":          login,
        "name":           name,
        "source":         "oauth" if request.session.get("github_token") else ("env" if GITHUB_TOKEN else "none"),
    })


@app.get("/api/github/repos")
async def api_github_repos(request: Request):
    """Descubrimiento dinámico: lista los repos de GitHub accesibles por el token."""
    from config import GITHUB_TOKEN
    from tools.github_repos import list_user_repos
    token = request.session.get("github_token") or GITHUB_TOKEN or ""
    return JSONResponse({"connected": bool(token), "repos": list_user_repos(token)})


@app.post("/api/repos/clone")
async def api_repos_clone(request: Request):
    """Clona (o actualiza) un repo elegido en WORKSPACES_ROOT para usarlo en el pipeline."""
    import os as _os
    from pathlib import Path as _Path
    from config import GITHUB_TOKEN, WORKSPACES_ROOT
    from tools.git_tools import clone_or_update_repo
    body = await request.json()
    clone_url = (body.get("clone_url") or "").strip()
    if not clone_url:
        return JSONResponse({"ok": False, "error": "clone_url requerido"}, status_code=400)
    name = (body.get("name") or "").strip() or clone_url.rstrip("/").split("/")[-1]
    if name.endswith(".git"):
        name = name[:-4]
    token = request.session.get("github_token") or GITHUB_TOKEN or ""
    actor = _os.getenv("GITHUB_ACTOR", "")
    dest = str(_Path(WORKSPACES_ROOT) / name)
    ok = clone_or_update_repo(clone_url, dest, token=token, actor=actor)
    return JSONResponse({"ok": ok, "name": name})


# ── Helpers ───────────────────────────────────────────────────────────────────

def _all_runs() -> list[dict]:
    if not RUNS_DIR.exists():
        return []
    runs = []
    for d in sorted(RUNS_DIR.iterdir(), reverse=True):
        meta_path = d / "metadata.json"
        if not meta_path.exists():
            continue
        meta = json.loads(meta_path.read_text())
        meta["feature_id"] = d.name
        meta["outputs"] = [p.name for p in sorted(d.glob("output_*.md"))]
        runs.append(meta)
    return runs


def _total_cost(runs: list[dict]) -> float:
    return sum(r.get("total_cost_usd", 0) for r in runs)


def _cost_by_status(runs: list[dict]) -> dict:
    buckets: dict[str, float] = {}
    for r in runs:
        s = r.get("status", "?")
        buckets[s] = buckets.get(s, 0) + r.get("total_cost_usd", 0)
    return buckets


# ── Health check (Docker / Railway) ──────────────────────────────────────────

@app.get("/health")
async def health_check():
    """Endpoint de salud para Docker healthcheck y Railway."""
    from datetime import datetime, timezone
    return {"status": "ok", "ts": datetime.now(timezone.utc).isoformat()}


@app.get("/api/sidebar-data")
async def sidebar_data():
    """Datos para el sidebar: últimos 18 runs para mostrar como historial."""
    runs = _all_runs()[:18]
    return JSONResponse({
        "runs": [
            {
                "id":           r.get("feature_id", ""),
                "feature_name": r.get("feature_name", r.get("feature_id", ""))[:52],
                "repo":         r.get("repo_name", ""),
                "status":       r.get("status", ""),
                "started_at":   r.get("started_at", ""),
            }
            for r in runs
        ]
    })


# ── Rutas — Dashboard ─────────────────────────────────────────────────────────

@app.get("/", response_class=HTMLResponse)
async def dashboard(request: Request):
    runs = _all_runs()
    return templates.TemplateResponse(request, "dashboard.html", {
        **_base_ctx(request),
        "runs": runs,
        "total_cost": _total_cost(runs),
        "cost_by_status": _cost_by_status(runs),
        "active_page": "dashboard",
    })


# ── Rutas — Configuración ─────────────────────────────────────────────────────

@app.get("/config", response_class=HTMLResponse)
async def config_page(request: Request, saved: str = ""):
    cfg = store.load()
    extra_keys = store.load_extra_keys()
    return templates.TemplateResponse(request, "config.html", {
        "cfg":              cfg,
        "prices":           PRICES,
        "active_page":      "config",
        "saved":            saved == "1",
        "extra_keys":       extra_keys,
        "repos":            list_repos(),
        "custom_providers": _load_custom_providers(),
    })


@app.get("/skills", response_class=HTMLResponse)
async def skills_page(request: Request, repo: str = ""):
    """Página de gestión de skills del proyecto destino."""
    from tools.skill_tools import list_skills
    from config import resolve_repo_path

    repos  = list_repos()
    if not repo and repos:
        repo = repos[0]["name"]

    skills = []
    if repo:
        try:
            skills = list_skills(resolve_repo_path(repo))
        except Exception:
            skills = []

    return templates.TemplateResponse(request, "skills.html", {
        "repos":       repos,
        "selected_repo": repo,
        "skills":      skills,
        "active_page": "skills",
    })


@app.post("/config")
async def save_config(
    request: Request,
    # API keys
    anthropic_api_key: str = Form(""),
    google_api_key:    str = Form(""),
    zhipu_api_key:     str = Form(""),
    kimi_api_key:      str = Form(""),
    openai_api_key:    str = Form(""),
    nvidia_api_key:    str = Form(""),
    langchain_api_key: str = Form(""),
    langchain_tracing: str = Form("false"),
    # Telegram
    telegram_bot_token: str = Form(""),
    telegram_chat_id:   str = Form(""),
    # Modelos por agente
    model_a0:  str = Form("gemini-3.5-flash"),
    model_a1:  str = Form("gemini-3.5-flash"),
    model_a2:  str = Form(MODEL_STANDARD),
    model_a3:  str = Form(MODEL_STANDARD),
    model_a4:  str = Form("glm-5.1"),
    model_a5:  str = Form("kimi-k2.6"),
    model_a6:  str = Form(MODEL_STANDARD),
    model_a7:  str = Form("gpt-5.5"),
    model_a8:  str = Form("gpt-5.5"),
    model_a11: str = Form(MODEL_STANDARD),
    # Comportamiento del pipeline
    write_to_repo:      str = Form("false"),   # checkbox: "on" cuando activo, ausente si no
    arch_review_interval: int = Form(3),
    # Límites
    max_qa_completo:    int = Form(3),
    max_qa_lite:        int = Form(2),
    max_secops_iter:    int = Form(2),
    max_sandbox_iter:   int = Form(2),
    checkpoint_timeout: int = Form(1800),
    # Auditor periódico
    auditor_enabled:   str = Form("false"),
    auditor_weekday:   int = Form(0),
    auditor_hour:      int = Form(7),
    auditor_max_files: int = Form(30),
    auditor_model:     str = Form("claude-sonnet-4-6"),
    auditor_repo:      str = Form("all"),
    # Seguridad & Acceso
    ui_username:       str = Form(""),
    ui_password:       str = Form(""),
    github_token:      str = Form(""),
    github_actor:      str = Form(""),
    railway_token:        str = Form(""),
    railway_project_id:   str = Form(""),
    extra_vars:           str = Form(""),    # KEY=VALUE por línea
    custom_providers_json: str = Form("[]"), # JSON array de proveedores IA custom
):
    new_cfg = {
        "ANTHROPIC_API_KEY":  anthropic_api_key,
        "GOOGLE_API_KEY":     google_api_key,
        "ZHIPU_API_KEY":      zhipu_api_key,
        "KIMI_API_KEY":       kimi_api_key,
        "OPENAI_API_KEY":     openai_api_key,
        "NVIDIA_API_KEY":     nvidia_api_key,
        "LANGCHAIN_API_KEY":  langchain_api_key,
        "LANGCHAIN_TRACING_V2": "true" if langchain_tracing == "on" else "false",
        "TELEGRAM_BOT_TOKEN": telegram_bot_token,
        "TELEGRAM_CHAT_ID":   telegram_chat_id,
        "MODEL_A0": model_a0,
        "MODEL_A1": model_a1,
        "MODEL_A2": model_a2,
        "MODEL_A3": model_a3,
        "MODEL_A4": model_a4,
        "MODEL_A5": model_a5,
        "MODEL_A6":  model_a6,
        "MODEL_A7":  model_a7,
        "MODEL_A8":  model_a8,
        "MODEL_A11": model_a11,
        "WRITE_TO_REPO":        "true" if write_to_repo == "on" else "false",
        "ARCH_REVIEW_INTERVAL": arch_review_interval,
        "MAX_QA_ITER_COMPLETO":       max_qa_completo,
        "MAX_QA_ITER_LITE":           max_qa_lite,
        "MAX_SECOPS_ITER":            max_secops_iter,
        "MAX_SANDBOX_ITER":           max_sandbox_iter,
        "CHECKPOINT_TIMEOUT_SECONDS": checkpoint_timeout,
        "AUDITOR_ENABLED":   "true" if auditor_enabled == "on" else "false",
        "AUDITOR_WEEKDAY":   auditor_weekday,
        "AUDITOR_HOUR":      auditor_hour,
        "AUDITOR_MAX_FILES": auditor_max_files,
        "AUDITOR_MODEL":     auditor_model,
        "AUDITOR_REPO":      auditor_repo,
        # Seguridad & Acceso
        "UI_USERNAME":   ui_username,
        "UI_PASSWORD":   ui_password,
        "GITHUB_TOKEN":  github_token,
        "GITHUB_ACTOR":  github_actor,
        "RAILWAY_TOKEN":      railway_token,
        "RAILWAY_PROJECT_ID": railway_project_id,
    }
    # Aplicar cambios al scheduler de auditoría si ya está corriendo
    _reschedule_auditor(
        enabled=auditor_enabled == "on",
        weekday=auditor_weekday,
        hour=auditor_hour,
    )
    # Parsear variables adicionales (una por línea, formato KEY=VALUE)
    for line in extra_vars.splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, _, v = line.partition("=")
        k = k.strip()
        if k:  # guardar cualquier key que el usuario defina
            new_cfg[k] = v.strip()

    store.save(new_cfg)

    # Guardar proveedores IA personalizados
    try:
        providers = json.loads(custom_providers_json or "[]")
        if isinstance(providers, list):
            _save_custom_providers(providers)
    except Exception as e:
        logger.warning("Error al guardar custom_providers.json: %s", e)

    return RedirectResponse("/config?saved=1", status_code=303)


# ── Rutas — Nuevo Feature ─────────────────────────────────────────────────────

@app.get("/new", response_class=HTMLResponse)
async def new_feature_page(request: Request):
    cfg = store.load()
    api_key_ok = bool(cfg.get("ANTHROPIC_API_KEY", "").startswith("sk-ant-"))
    repos = list_repos()
    return templates.TemplateResponse(request, "new_feature.html", {
        **_base_ctx(request),
        "active_page": "new",
        "api_key_ok": api_key_ok,
        "repos": repos,
    })


# ── Rutas — Nuevo Proyecto ────────────────────────────────────────────────────

@app.get("/project/new", response_class=HTMLResponse)
async def new_project_page(request: Request):
    cfg = store.load()
    api_key_ok = bool(cfg.get("ANTHROPIC_API_KEY", "").startswith("sk-ant-"))
    repos = list_repos()
    return templates.TemplateResponse(request, "new_project.html", {
        "active_page": "new_project",
        "api_key_ok": api_key_ok,
        "repos": repos,
    })


_ALLOWED_UPLOAD_EXTENSIONS = {
    ".txt", ".md", ".json", ".yaml", ".yml", ".csv", ".pdf", ".docx"
}
_MAX_UPLOAD_SIZE_MB = 10


@app.post("/project/new")
async def start_project(
    project_name: str = Form(...),
    project_brief: str = Form(""),
    repo_name: str = Form(...),
    is_new_project: str = Form("false"),
    audit_mode: str = Form("false"),
    files: List[UploadFile] = File(default=[]),
):
    if not project_name.strip():
        raise HTTPException(400, "El nombre del proyecto no puede estar vacío")
    _is_audit = audit_mode.lower() in ("true", "1", "on")
    if not _is_audit and not project_brief.strip():
        raise HTTPException(400, "El brief del proyecto no puede estar vacío")

    project_id = (
        f"proj_{datetime.now().strftime('%Y%m%d_%H%M%S')}_"
        f"{project_name.strip()[:20].replace(' ', '_').lower()}"
    )

    # ── Guardar archivos subidos ANTES de lanzar el proceso ───────────────────
    uploads_dir = RUNS_DIR / project_id / "uploads"
    uploaded_names: list[str] = []

    for upload in files:
        if not upload.filename:
            continue
        import re as _re
        safe_name = Path(upload.filename).name          # Evitar path traversal
        safe_name = _re.sub(r"[^a-zA-Z0-9._\-]", "_", safe_name)[:128]  # C-02: sanitizar
        ext = Path(safe_name).suffix.lower()
        if ext not in _ALLOWED_UPLOAD_EXTENSIONS:
            continue                                    # Ignorar tipos no soportados

        content = await upload.read()
        if len(content) > _MAX_UPLOAD_SIZE_MB * 1024 * 1024:
            continue                                    # Ignorar archivos demasiado grandes

        uploads_dir.mkdir(parents=True, exist_ok=True)
        (uploads_dir / safe_name).write_bytes(content)
        uploaded_names.append(safe_name)

    # ── Crear directorio del run y lanzar proceso ─────────────────────────────
    (RUNS_DIR / project_id).mkdir(parents=True, exist_ok=True)
    (RUNS_DIR / project_id / "process.pid").write_text("starting")

    is_new   = is_new_project.lower() in ("true", "1", "on")
    is_audit = audit_mode.lower() in ("true", "1", "on")
    # brief vacío → placeholder para el audit (A0 lo ignora y usa el código)
    brief_arg = project_brief.strip() or f"Onboarding de {repo_name.strip()}"
    cmd = [
        sys.executable, "cli.py", "new-project",
        project_name.strip(),
        brief_arg,
        "--repo", repo_name.strip(),
    ] + (["--new"] if is_new else []) + (["--audit"] if is_audit else [])

    subprocess.Popen(
        cmd,
        cwd=str(Path(__file__).parent.parent),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        env={**os.environ, "PROJECT_ID_OVERRIDE": project_id},
    )

    return RedirectResponse(f"/project/{project_id}", status_code=303)


@app.post("/api/projects/{project_id}/import_sessions")
async def import_sessions(project_id: str, file: UploadFile = File(...)):
    """
    V-2: Importa un archivo .md de sesiones manuales y añade los features
    detectados al backlog del proyecto.
    """
    import re as _re
    if not file.filename or not file.filename.endswith(".md"):
        raise HTTPException(400, "Solo se aceptan archivos .md")

    content_bytes = await file.read()
    if len(content_bytes) > 2 * 1024 * 1024:
        raise HTTPException(400, "Archivo demasiado grande (máx. 2 MB)")

    md_content = content_bytes.decode("utf-8", errors="replace")

    try:
        from tools.session_importer import parse_session_plan
        features = parse_session_plan(md_content)
    except Exception as exc:
        raise HTTPException(500, f"Error al parsear el plan de sesiones: {exc}")

    if not features:
        return {"ok": False, "message": "No se detectaron features en el archivo", "count": 0}

    # Leer metadata actual del proyecto y añadir los features al backlog
    meta_path = RUNS_DIR / project_id / "metadata.json"
    if not meta_path.exists():
        raise HTTPException(404, f"Proyecto {project_id!r} no encontrado")

    try:
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        current_backlog = meta.get("backlog", [])
        # Añadir solo los que no estén duplicados por nombre
        existing_names = {f.get("name", "").lower() for f in current_backlog}
        added = []
        for f in features:
            if f["name"].lower() not in existing_names:
                # VI-1: asegurar campo depends_on en features importados
                if "depends_on" not in f:
                    f["depends_on"] = []
                current_backlog.append(f)
                added.append(f["name"])
        meta["backlog"] = current_backlog
        meta_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8")
    except Exception as exc:
        raise HTTPException(500, f"Error al actualizar el backlog: {exc}")

    return {
        "ok": True,
        "count": len(added),
        "added": added,
        "message": f"{len(added)} features importados al backlog",
    }


@app.get("/project/{project_id}", response_class=HTMLResponse)
async def project_detail(request: Request, project_id: str):
    run_dir = RUNS_DIR / project_id
    if not run_dir.exists():
        raise HTTPException(404, "Proyecto no encontrado")

    meta_path = run_dir / "metadata.json"
    meta = json.loads(meta_path.read_text()) if meta_path.exists() else {}

    return templates.TemplateResponse(request, "project_detail.html", {
        "project_id": project_id,
        "meta": meta,
        "active_page": "dashboard",
    })


@app.post("/project/{project_id}/approve-roadmap")
async def approve_roadmap(project_id: str, action: str = Form("approve")):
    """Aprueba o cancela el roadmap desde la UI."""
    run_dir = RUNS_DIR / project_id
    approval_file = run_dir / "pending_approval.txt"
    approval_file.write_text(action)
    return JSONResponse({"ok": True, "action": action})


# ── Rutas — Nuevo Feature ─────────────────────────────────────────────────────

@app.post("/new")
async def start_feature(
    feature_name: str = Form(...),
    mode: str = Form("auto"),
    repo_name: str = Form(...),
):
    if not feature_name.strip():
        raise HTTPException(400, "El nombre del feature no puede estar vacío")
    if not repo_name.strip():
        raise HTTPException(400, "Debes seleccionar un repositorio")

    # El feature_id se genera en cli.py — llamamos al proceso
    cmd = [
        sys.executable, "cli.py", "new-feature",
        feature_name.strip(),
        "--repo", repo_name.strip(),
        "--mode", mode,
    ]
    # Lanzar en background — el usuario verá el progreso en /stream/<feature_id>
    # Generamos el feature_id anticipado para poder redirigir
    feature_id = (
        f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_"
        f"{feature_name.strip()[:20].replace(' ', '_').lower()}"
    )
    env_path = Path(__file__).parent.parent / ".env"
    proc = subprocess.Popen(
        cmd,
        cwd=str(Path(__file__).parent.parent),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        env={**os.environ, "FEATURE_ID_OVERRIDE": feature_id},
    )
    # Guardar PID para status
    (RUNS_DIR / feature_id).mkdir(parents=True, exist_ok=True)
    (RUNS_DIR / feature_id / "process.pid").write_text(str(proc.pid))

    return RedirectResponse(f"/feature/{feature_id}", status_code=303)


# ── Rutas — Detalle de Feature ────────────────────────────────────────────────

@app.get("/feature/{feature_id}", response_class=HTMLResponse)
async def feature_detail(request: Request, feature_id: str):
    run_dir = RUNS_DIR / feature_id
    if not run_dir.exists():
        raise HTTPException(404, "Feature no encontrado")

    meta_path = run_dir / "metadata.json"
    meta = json.loads(meta_path.read_text()) if meta_path.exists() else {}

    outputs = {}
    for p in sorted(run_dir.glob("output_*.md")):
        outputs[p.stem.replace("output_", "")] = p.read_text(encoding="utf-8")

    master_plan = ""
    mp_path = run_dir / "MASTER_PLAN.md"
    if mp_path.exists():
        master_plan = mp_path.read_text(encoding="utf-8")

    return templates.TemplateResponse(request, "feature_detail.html", {
        "feature_id": feature_id,
        "meta": meta,
        "outputs": outputs,
        "master_plan": master_plan,
        "active_page": "dashboard",
    })


# ── Rutas — Resume (aprobación del Stop Protocol desde la UI) ────────────────

@app.post("/feature/{feature_id}/approve")
async def approve_feature(feature_id: str, action: str = Form("approve")):
    """Permite aprobar el MASTER_PLAN o pausar checkpoints desde la UI."""
    run_dir = RUNS_DIR / feature_id
    approval_file = run_dir / "pending_approval.txt"
    approval_file.write_text(action)
    return JSONResponse({"ok": True, "action": action})


# ── Rutas — API de datos (para gráficas JS) ───────────────────────────────────

@app.get("/api/costs")
async def api_costs():
    runs = _all_runs()
    daily: dict[str, float] = {}
    for r in runs:
        day = (r.get("started_at") or "")[:10]
        if day:
            daily[day] = round(daily.get(day, 0) + r.get("total_cost_usd", 0), 6)

    by_agent: dict[str, float] = {}
    run_dirs = list(RUNS_DIR.iterdir()) if RUNS_DIR.exists() else []
    for run_dir in run_dirs:
        meta_path = run_dir / "metadata.json"
        if not meta_path.exists():
            continue
        # Extraer entries de costo si están guardadas
        entries_path = run_dir / "cost_entries.json"
        if entries_path.exists():
            for e in json.loads(entries_path.read_text()):
                ag = e.get("agent", "?")
                by_agent[ag] = round(by_agent.get(ag, 0) + e.get("cost_usd", 0), 6)

    return {
        "total": _total_cost(runs),
        "total_runs": len(runs),
        "daily": daily,
        "by_agent": by_agent,
        "runs": [
            {
                "id": r["feature_id"],
                "name": r.get("feature_name", r["feature_id"]),
                "status": r.get("status", "?"),
                "cost": r.get("total_cost_usd", 0),
                "mode": r.get("mode", "?"),
                "date": (r.get("started_at") or "")[:19],
            }
            for r in runs[:20]
        ],
    }


@app.get("/api/feature/{feature_id}/status")
async def api_feature_status(feature_id: str):
    meta_path = RUNS_DIR / feature_id / "metadata.json"
    if not meta_path.exists():
        return {"status": "not_found"}
    return json.loads(meta_path.read_text())


# ── Páginas — Agente de Noticias ─────────────────────────────────────────────

def _build_news_ctx(cfg_raw: dict) -> dict:
    """Construye el contexto para el template de noticias a partir del cfg raw."""
    hour    = int(cfg_raw.get("NEWS_AGENT_HOUR", "8"))
    topics_raw = cfg_raw.get("NEWS_AGENT_TOPICS", "")
    topics  = [t.strip() for t in topics_raw.split(",") if t.strip()] if topics_raw else []
    return {
        "enabled":    cfg_raw.get("NEWS_AGENT_ENABLED",  "true") == "true",
        "hour":       hour,
        "hour_disp":  f"{hour:02d}:00",
        "provider":   cfg_raw.get("NEWS_AGENT_PROVIDER", "anthropic"),
        "model":      cfg_raw.get("NEWS_AGENT_MODEL",    "claude-haiku-4-5-20251001"),
        "api_key":    cfg_raw.get("NEWS_AGENT_API_KEY",  ""),
        "api_url":    cfg_raw.get("NEWS_AGENT_API_URL",  ""),
        "topics":     topics,
        "tg_custom":  bool(cfg_raw.get("NEWS_AGENT_TG_TOKEN", "")),
        "tg_token":   cfg_raw.get("NEWS_AGENT_TG_TOKEN", ""),
        "tg_chat":    cfg_raw.get("NEWS_AGENT_TG_CHAT",  ""),
    }


@app.get("/news", response_class=HTMLResponse)
async def news_page(request: Request, saved: bool = False):
    cfg_raw = store.load(masked=False)
    nc = _build_news_ctx(cfg_raw)
    return templates.TemplateResponse(request, "news.html", {
        "active_page": "news",
        "nc":          nc,
        "saved":       saved,
    })


@app.post("/news", response_class=HTMLResponse)
async def news_save(
    request: Request,
    news_enabled:   str = Form("off"),
    news_hour:      int = Form(8),
    news_provider:  str = Form("anthropic"),
    news_model:     str = Form("claude-haiku-4-5-20251001"),
    news_api_key:   str = Form(""),
    news_api_url:   str = Form(""),
    news_topics:    str = Form(""),       # JSON array string: ["topic1","topic2"]
    tg_custom:      str = Form("off"),
    news_tg_token:  str = Form(""),
    news_tg_chat:   str = Form(""),
):
    import json as _json
    enabled = news_enabled == "on"

    # Parsear topics: vienen como JSON array desde el frontend
    try:
        topics_list = _json.loads(news_topics) if news_topics else []
    except Exception:
        topics_list = [t.strip() for t in news_topics.split(",") if t.strip()]
    topics_str = ",".join(topics_list)

    new_cfg = {
        "NEWS_AGENT_ENABLED":  "true" if enabled else "false",
        "NEWS_AGENT_HOUR":     str(news_hour),
        "NEWS_AGENT_PROVIDER": news_provider,
        "NEWS_AGENT_MODEL":    news_model,
        "NEWS_AGENT_API_KEY":  news_api_key,
        "NEWS_AGENT_API_URL":  news_api_url,
        "NEWS_AGENT_TOPICS":   topics_str,
        "NEWS_AGENT_TG_TOKEN": news_tg_token if tg_custom == "on" else "",
        "NEWS_AGENT_TG_CHAT":  news_tg_chat  if tg_custom == "on" else "",
    }
    store.save(new_cfg)

    from dotenv import load_dotenv
    load_dotenv(override=True)
    _reschedule_news(enabled=enabled, hour=news_hour)

    return RedirectResponse("/news?saved=true", status_code=303)


# ── API — Agente de Noticias ──────────────────────────────────────────────────

@app.post("/api/news/run")
async def api_news_run(report_type: str = "all"):
    """
    Dispara el agente de noticias manualmente.
    report_type: "news" | "ai_models" | "all"
    """
    try:
        from tools.news_agent import run_news_report, run_ai_models_report, run_daily_reports

        def _run():
            if report_type == "news":
                return {"news": run_news_report()}
            elif report_type == "ai_models":
                return {"ai_models": run_ai_models_report()}
            else:
                run_daily_reports()
                return {"news": True, "ai_models": True}

        result = await asyncio.get_event_loop().run_in_executor(None, _run)
        return {"ok": True, "sent": result}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/news/toggle")
async def api_news_toggle(request: Request):
    """Toggle inmediato del agente — no requiere submit del form completo."""
    body = await request.json()
    enabled = bool(body.get("enabled", True))
    store.save({"NEWS_AGENT_ENABLED": "true" if enabled else "false"})
    cfg_raw = store.load(masked=False)
    hour = int(cfg_raw.get("NEWS_AGENT_HOUR", "8"))
    _reschedule_news(enabled=enabled, hour=hour)
    return {"ok": True, "enabled": enabled}


@app.get("/api/news/status")
async def api_news_status():
    """Estado actual del scheduler de noticias (lee del .env, no de módulo cacheado)."""
    cfg_raw = store.load(masked=False)
    enabled = cfg_raw.get("NEWS_AGENT_ENABLED", "true") == "true"
    hour    = int(cfg_raw.get("NEWS_AGENT_HOUR", "8"))
    model   = cfg_raw.get("NEWS_AGENT_MODEL", "claude-haiku-4-5-20251001")
    next_run = None
    if _news_scheduler:
        job = _news_scheduler.get_job("daily_news_report")
        if job and job.next_run_time:
            next_run = job.next_run_time.strftime("%Y-%m-%d %H:%M %Z")
    return {
        "enabled":          enabled,
        "hour":             hour,
        "model":            model,
        "next_run":         next_run,
        "scheduler_running": bool(_news_scheduler and _news_scheduler.running),
    }


# ── API — Auditor de Codebase ─────────────────────────────────────────────────

@app.post("/api/auditor/run")
async def api_auditor_run(request: Request):
    """
    Dispara una auditoría on-demand.
    Body JSON opcional: { "repo": "all" | "nombre-del-repo", "telegram": true|false }
    """
    try:
        body = {}
        try:
            body = await request.json()
        except Exception:
            pass

        repo_filter  = body.get("repo", "all") or "all"
        send_telegram = body.get("telegram", True)

        from tools.codebase_auditor import run_audit, get_status
        status = get_status()
        if status["running"]:
            return JSONResponse(
                {"ok": False, "message": "Ya hay una auditoría en curso. Espera a que termine."},
                status_code=409,
            )

        import threading
        t = threading.Thread(
            target=run_audit,
            kwargs={"repo_filter": repo_filter, "send_telegram": send_telegram},
            daemon=True,
            name=f"audit-{repo_filter}",
        )
        t.start()
        label = "todos los repos" if repo_filter == "all" else f"repo '{repo_filter}'"
        return {
            "ok": True,
            "repo_filter": repo_filter,
            "message": f"Auditoría iniciada para {label}. Polling /api/auditor/status para el resultado.",
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/auditor/toggle")
async def api_auditor_toggle(request: Request):
    """Toggle inmediato del auditor — no requiere submit del form completo."""
    body    = await request.json()
    enabled = bool(body.get("enabled", True))
    store.save({"AUDITOR_ENABLED": "true" if enabled else "false"})
    cfg_raw = store.load(masked=False)
    weekday = int(cfg_raw.get("AUDITOR_WEEKDAY", "0"))
    hour    = int(cfg_raw.get("AUDITOR_HOUR", "7"))
    _reschedule_auditor(enabled=enabled, weekday=weekday, hour=hour)
    return {"ok": True, "enabled": enabled}


@app.get("/api/auditor/status")
async def api_auditor_status():
    """Estado completo del auditor: scheduler + estado en vivo + últimos resultados."""
    from tools.codebase_auditor import get_status as _audit_get_status

    cfg_raw  = store.load(masked=False)
    enabled  = cfg_raw.get("AUDITOR_ENABLED", "true") == "true"
    weekday  = int(cfg_raw.get("AUDITOR_WEEKDAY", "0"))
    hour     = int(cfg_raw.get("AUDITOR_HOUR", "7"))
    model    = cfg_raw.get("AUDITOR_MODEL", "claude-sonnet-4-6")
    repo_cfg = cfg_raw.get("AUDITOR_REPO", "all")

    next_run = None
    if _audit_scheduler:
        job = _audit_scheduler.get_job("codebase_audit")
        if job and job.next_run_time:
            next_run = job.next_run_time.strftime("%Y-%m-%d %H:%M %Z")

    _WEEKDAYS = ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado", "Domingo"]
    live = _audit_get_status()

    return {
        "enabled":           enabled,
        "weekday":           weekday,
        "weekday_name":      _WEEKDAYS[weekday],
        "hour":              hour,
        "model":             model,
        "repo_cfg":          repo_cfg,
        "next_run":          next_run,
        "scheduler_running": bool(_audit_scheduler and _audit_scheduler.running),
        # Estado en vivo
        "running":           live["running"],
        "last_results":      live["last_results"],
    }


@app.get("/api/auditor/result/{repo_name}")
async def api_auditor_result(repo_name: str):
    """Devuelve el informe completo de la última auditoría de un repo específico."""
    from tools.codebase_auditor import get_result
    result = get_result(repo_name)
    if result is None:
        raise HTTPException(status_code=404, detail=f"Sin resultado para '{repo_name}'")
    return result


# ── API — Bot de Telegram ─────────────────────────────────────────────────────

@app.get("/api/bot/status")
async def api_bot_status():
    """Estado del bot de Telegram: si el thread de polling está activo y si el token funciona."""
    cfg      = store.load(masked=False)
    token    = cfg.get("TELEGRAM_BOT_TOKEN", "")
    chat_id  = cfg.get("TELEGRAM_CHAT_ID", "")
    configured = bool(token and chat_id)

    thread_alive = bool(
        _tg_bot_thread and _tg_bot_thread.is_alive()
    )

    # Verificar que el token sea válido haciendo getMe
    bot_info = None
    if token:
        try:
            import httpx as _httpx
            r = _httpx.get(
                f"https://api.telegram.org/bot{token}/getMe",
                timeout=5,
            )
            data = r.json()
            if data.get("ok"):
                bot_info = {
                    "username":   data["result"]["username"],
                    "first_name": data["result"]["first_name"],
                }
        except Exception:
            pass

    return {
        "configured":   configured,
        "thread_alive": thread_alive,
        "bot_info":     bot_info,
        "chat_id":      chat_id,
    }


@app.post("/api/bot/send_test")
async def api_bot_send_test():
    """Envía un mensaje de prueba al chat configurado."""
    cfg     = store.load(masked=False)
    token   = cfg.get("TELEGRAM_BOT_TOKEN", "")
    chat_id = cfg.get("TELEGRAM_CHAT_ID", "")
    if not token or not chat_id:
        raise HTTPException(status_code=400, detail="Bot no configurado")
    try:
        import httpx as _httpx
        r = _httpx.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={
                "chat_id":    chat_id,
                "text":       "✅ Fábrica de Software — Prueba de conexión exitosa.\n\nEnvía /ayuda para ver los comandos disponibles.",
                "parse_mode": "Markdown",
            },
            timeout=10,
        )
        data = r.json()
        if not data.get("ok"):
            raise HTTPException(status_code=500, detail=str(data))
        return {"ok": True, "message_id": data["result"]["message_id"]}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


# ── Skills del proyecto ──────────────────────────────────────────────────────

@app.get("/api/skills")
async def api_list_skills(repo: str = ""):
    """Lista las skills del repo indicado (o del primero disponible si está vacío)."""
    from tools.skill_tools import list_skills
    from config import resolve_repo_path, list_repos

    if not repo:
        repos = list_repos()
        if not repos:
            return {"skills": [], "repo": "", "skills_dir": ""}
        repo = repos[0]["name"]

    repo_path = resolve_repo_path(repo)
    skills = list_skills(repo_path)
    return {
        "repo": repo,
        "skills_dir": f"{repo}/docs/skills/",
        "skills": [
            {"name": s["name"], "description": s["description"], "path": s["path"]}
            for s in skills
        ],
    }


@app.get("/api/skills/{skill_name}")
async def api_get_skill(skill_name: str, repo: str = ""):
    """Devuelve el contenido completo de una skill."""
    from tools.skill_tools import list_skills
    from config import resolve_repo_path, list_repos

    if not repo:
        repos = list_repos()
        repo = repos[0]["name"] if repos else ""
    if not repo:
        raise HTTPException(status_code=404, detail="No hay repos disponibles")

    skills = list_skills(resolve_repo_path(repo))
    skill = next((s for s in skills if s["name"] == skill_name), None)
    if not skill:
        raise HTTPException(status_code=404, detail=f"Skill '{skill_name}' no encontrada")
    return skill


@app.post("/api/skills")
async def api_create_skill(request: Request):
    """Crea una nueva skill en el repo. Body: {repo, name, description, content}."""
    from tools.skill_tools import create_skill
    from config import resolve_repo_path

    data = await request.json()
    repo    = data.get("repo", "")
    name    = data.get("name", "").strip()
    desc    = data.get("description", "").strip()
    content = data.get("content", "").strip()

    if not repo or not name:
        raise HTTPException(status_code=400, detail="Se requieren 'repo' y 'name'")

    path = create_skill(resolve_repo_path(repo), name, desc, content)
    return {"ok": True, "path": path, "name": name}


@app.put("/api/skills/{skill_name}")
async def api_update_skill(skill_name: str, request: Request):
    """Actualiza una skill existente. Body: {repo, description, content}."""
    from tools.skill_tools import list_skills, update_skill
    from config import resolve_repo_path, list_repos

    data = await request.json()
    repo    = data.get("repo", "")
    desc    = data.get("description", "")
    content = data.get("content", "")

    if not repo:
        repos = list_repos()
        repo = repos[0]["name"] if repos else ""

    skills = list_skills(resolve_repo_path(repo))
    skill = next((s for s in skills if s["name"] == skill_name), None)
    if not skill:
        raise HTTPException(status_code=404, detail=f"Skill '{skill_name}' no encontrada")

    update_skill(skill["path"], desc, content)
    return {"ok": True, "name": skill_name}


@app.get("/api/projects/{project_id}/quality")
async def api_project_quality(project_id: str):
    """Métricas de calidad acumuladas del proyecto (Bloque I)."""
    from tools.quality_tracker import compute_trend, propose_standards_update
    import json as _json

    metrics_path = RUNS_DIR / project_id / "quality_metrics.jsonl"
    features: list[dict] = []
    if metrics_path.exists():
        for line in metrics_path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line:
                try:
                    features.append(_json.loads(line))
                except Exception:
                    pass

    trend    = compute_trend(project_id)
    proposal = propose_standards_update(project_id)

    return {
        "trend":    trend,
        "features": features[-20:],   # últimos 20 features
        "proposal": proposal,
    }


@app.delete("/api/skills/{skill_name}")
async def api_delete_skill(skill_name: str, repo: str = ""):
    """Elimina una skill del repo."""
    from tools.skill_tools import list_skills, delete_skill
    from config import resolve_repo_path, list_repos

    if not repo:
        repos = list_repos()
        repo = repos[0]["name"] if repos else ""

    skills = list_skills(resolve_repo_path(repo))
    skill = next((s for s in skills if s["name"] == skill_name), None)
    if not skill:
        raise HTTPException(status_code=404, detail=f"Skill '{skill_name}' no encontrada")

    delete_skill(skill["path"])
    return {"ok": True, "deleted": skill_name}


# ── SSE — Stream de logs en tiempo real ───────────────────────────────────────

@app.get("/stream/{feature_id}")
async def stream_logs(feature_id: str):
    """Server-Sent Events: emite líneas del log del feature en tiempo real."""
    run_dir = RUNS_DIR / feature_id

    async def event_generator() -> AsyncIterator[str]:
        log_path = run_dir / "run.log"
        sent_lines = 0
        idle_ticks = 0

        while idle_ticks < 120:  # timeout 2 min sin nuevas líneas
            if log_path.exists():
                lines = log_path.read_text(encoding="utf-8").splitlines()
                new_lines = lines[sent_lines:]
                for line in new_lines:
                    yield f"data: {line}\n\n"
                sent_lines += len(new_lines)   # BUG-008: fuera del loop, incremento correcto
                if new_lines:
                    idle_ticks = 0

            # Verificar si el proceso terminó
            meta_path = run_dir / "metadata.json"
            if meta_path.exists():
                meta = json.loads(meta_path.read_text())
                status = meta.get("status", "")
                if status in ("completado", "detenido", "aprobado"):
                    yield f"data: [DONE] status={status}\n\n"
                    return

            idle_ticks += 1
            await asyncio.sleep(1)

        yield "data: [TIMEOUT]\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream")


# ═══════════════════════════════════════════════════════════════════════════════
# VII-1 — Chat pre-planificación
# ═══════════════════════════════════════════════════════════════════════════════

@app.get("/prechat", response_class=HTMLResponse)
async def prechat_page(request: Request, feature_name: str = "", repo: str = "", mode: str = "auto"):
    """Página de chat pre-planificación — se llega desde /new con params opcionales."""
    return templates.TemplateResponse(request, "prechat.html", {
        "feature_name": feature_name,
        "repo":         repo,
        "mode":         mode,
        "repos":        list_repos(),
        "active_page":  "new",
    })


@app.post("/api/prechat")
async def api_prechat(request: Request):
    """
    Stream SSE del chat pre-planificación con el A0.
    Body JSON: {messages: [{role, content}], model?: str}
    """
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(400, "Body JSON inválido")

    messages = body.get("messages", [])
    model    = body.get("model", None)

    if not messages:
        raise HTTPException(400, "messages requerido")

    async def event_generator():
        import asyncio
        from nodes.a0_prechat import stream_response

        loop = asyncio.get_event_loop()
        # stream_response es síncrono con yield — lo ejecutamos en un thread
        def _gen():
            return list(stream_response(messages, model))

        try:
            # Ejecutar en thread para no bloquear el event loop
            tokens = await loop.run_in_executor(None, _gen)
            for token in tokens:
                # Escapar newlines en el valor SSE
                safe = token.replace("\n", "\\n")
                yield f"data: {json.dumps({'token': token})}\n\n"
            yield f"data: {json.dumps({'done': True})}\n\n"
        except Exception as exc:
            logger.exception("prechat stream error: %s", exc)
            yield f"data: {json.dumps({'error': str(exc)})}\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream")


@app.post("/api/prechat/confirm")
async def api_prechat_confirm(request: Request):
    """
    Guarda el refined_brief y lanza el pipeline con él.
    Body JSON: {feature_name, repo_name, mode, refined_brief, conversation}
    """
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(400, "Body JSON inválido")

    feature_name  = body.get("feature_name", "").strip()
    repo_name     = body.get("repo_name", "").strip()
    mode          = body.get("mode", "auto")
    refined_brief = body.get("refined_brief", "").strip()

    if not feature_name or not repo_name:
        raise HTTPException(400, "feature_name y repo_name son requeridos")

    feature_id = (
        f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_"
        f"{feature_name[:20].replace(' ', '_').lower()}"
    )

    # Guardar el refined_brief en metadata para que el CLI lo cargue
    (RUNS_DIR / feature_id).mkdir(parents=True, exist_ok=True)
    import json as _json
    (RUNS_DIR / feature_id / "metadata.json").write_text(
        _json.dumps({"refined_brief": refined_brief, "feature_name": feature_name}),
        encoding="utf-8",
    )

    # Lanzar pipeline con env var adicional para el refined_brief
    cmd = [
        sys.executable, "cli.py", "new-feature",
        feature_name,
        "--repo", repo_name,
        "--mode", mode,
    ]
    env = {
        **os.environ,
        "FEATURE_ID_OVERRIDE":   feature_id,
        "REFINED_BRIEF_OVERRIDE": refined_brief[:2000],  # limitado para env var
    }
    proc = subprocess.Popen(
        cmd,
        cwd=str(Path(__file__).parent.parent),
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        env=env,
    )
    (RUNS_DIR / feature_id / "process.pid").write_text(str(proc.pid))

    return JSONResponse({"ok": True, "feature_id": feature_id, "redirect": f"/feature/{feature_id}"})


# ═══════════════════════════════════════════════════════════════════════════════
# VII-2 — Observabilidad en vivo (SSE de eventos)
# ═══════════════════════════════════════════════════════════════════════════════

@app.get("/session/{feature_id}", response_class=HTMLResponse)
async def session_live(request: Request, feature_id: str):
    """Vista en vivo del feature — muestra agentes, tokens, costos en tiempo real."""
    run_dir = RUNS_DIR / feature_id
    meta = {}
    if (run_dir / "metadata.json").exists():
        meta = json.loads((run_dir / "metadata.json").read_text())

    from tools.event_bus import get_recent_events
    recent_events = get_recent_events(feature_id, limit=200)

    return templates.TemplateResponse(request, "session_detail.html", {
        "feature_id":    feature_id,
        "meta":          meta,
        "recent_events": recent_events,
        "active_page":   "dashboard",
    })


@app.get("/api/sessions/{feature_id}/stream")
async def session_stream(feature_id: str):
    """SSE endpoint — hace tail del events.jsonl y lo streamea al cliente."""
    from tools.event_bus import tail_sse

    async def event_generator():
        async for chunk in tail_sse(feature_id):
            yield chunk

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control":               "no-cache",
            "X-Accel-Buffering":           "no",   # nginx: deshabilitar buffer
            "Access-Control-Allow-Origin": "*",
        },
    )


@app.get("/api/sessions/{feature_id}/events")
async def session_events(feature_id: str, limit: int = 100):
    """Devuelve los últimos N eventos del feature (para carga inicial)."""
    from tools.event_bus import get_recent_events
    return JSONResponse({"events": get_recent_events(feature_id, limit=limit)})


@app.post("/api/sessions/{feature_id}/intervene")
async def session_intervene(feature_id: str, request: Request):
    """
    VIII-1: Envía instrucción correctiva al pipeline en curso.
    El próximo agente en llamar al LLM leerá e inyectará esta instrucción.
    Body JSON: { "text": "Instrucción del Founder..." }
    """
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(400, "Body JSON inválido")

    text = body.get("text", "").strip()
    if not text:
        raise HTTPException(400, "El campo 'text' es requerido")

    try:
        from tools.event_bus import post_intervention
        post_intervention(feature_id, text)
        return JSONResponse({"ok": True, "feature_id": feature_id, "preview": text[:100]})
    except Exception as exc:
        logger.exception("session_intervene error: %s", exc)
        raise HTTPException(500, str(exc))


# ═══════════════════════════════════════════════════════════════════════════════
# VII-3 — Railway Deploy
# ═══════════════════════════════════════════════════════════════════════════════

@app.get("/deploy", response_class=HTMLResponse)
async def deploy_page(request: Request):
    """Panel de deploy a Railway."""
    from config import FABRICA_DIR
    cfg = store.load(masked=False)
    railway_token      = cfg.get("RAILWAY_TOKEN", "") or os.getenv("RAILWAY_TOKEN", "")
    railway_project_id = cfg.get("RAILWAY_PROJECT_ID", "") or os.getenv("RAILWAY_PROJECT_ID", "")

    return templates.TemplateResponse(request, "deploy.html", {
        # Con el account token basta para ver TODOS los proyectos (cuenta enlazada).
        "railway_configured": bool(railway_token),
        "railway_project_id": railway_project_id,
        "repos":              list_repos(),
        "active_page":        "deploy",
    })


@app.post("/api/deploy/railway")
async def api_deploy_railway(request: Request):
    """Dispara un deploy en Railway."""
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(400, "Body JSON inválido")

    service_id  = body.get("service_id", "")
    environment = body.get("environment", "production")

    try:
        from tools.railway_client import trigger_deploy
        result = await trigger_deploy(service_id=service_id, environment=environment)
        return JSONResponse(result)
    except Exception as exc:
        logger.exception("railway deploy error: %s", exc)
        return JSONResponse({"error": str(exc)}, status_code=500)


@app.get("/api/deploy/railway/status")
async def api_deploy_status(deployment_id: str = ""):
    """Polling del estado de un deploy Railway."""
    try:
        from tools.railway_client import get_deployment_status
        result = await get_deployment_status(deployment_id)
        return JSONResponse(result)
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=500)


@app.get("/api/deploy/railway/services")
async def api_railway_services():
    """Lista los servicios del proyecto Railway configurado."""
    try:
        from tools.railway_client import list_services
        result = await list_services()
        return JSONResponse(result)
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=500)


@app.get("/api/railway/projects")
async def api_railway_projects():
    """Mejora B: lista TODOS los proyectos de la cuenta Railway enlazada + estado."""
    try:
        from tools.railway_client import list_projects
        return JSONResponse(await list_projects())
    except Exception as exc:
        return JSONResponse({"error": str(exc), "projects": []}, status_code=200)
