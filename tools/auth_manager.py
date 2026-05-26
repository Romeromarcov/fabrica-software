"""
IX-1 — Gestor de usuarios y roles (RBAC básico).

Almacena usuarios en SQLite (users.db, separado del state de LangGraph).
No añade dependencias externas — usa hashlib stdlib para hashing.

Roles:
  owner     — Acceso total: config, deploy, gestión de usuarios, crear proyectos
  developer — Puede lanzar features e intervenir; sin deploy ni gestión de usuarios
  viewer    — Solo lectura: dashboard, features, sesiones en vivo

Activación: RBAC_ENABLED=true en .env (default: false → compatible hacia atrás).
"""
from __future__ import annotations

import hashlib
import logging
import os
import secrets
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

_DB_PATH: Path | None = None


def _get_db_path() -> Path:
    global _DB_PATH
    if _DB_PATH is None:
        try:
            from config import DB_PATH
            _DB_PATH = DB_PATH.parent / "users.db"
        except Exception:
            _DB_PATH = Path("data/users.db")
    return _DB_PATH


def _get_conn() -> sqlite3.Connection:
    path = _get_db_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    return conn


def _init_db() -> None:
    with _get_conn() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                email         TEXT UNIQUE NOT NULL,
                display_name  TEXT NOT NULL,
                password_hash TEXT DEFAULT '',
                role          TEXT NOT NULL DEFAULT 'viewer',
                github_login  TEXT DEFAULT '',
                created_at    TEXT DEFAULT (datetime('now')),
                last_login    TEXT DEFAULT '',
                active        INTEGER DEFAULT 1
            )
        """)
        conn.execute("""
            CREATE TABLE IF NOT EXISTS invite_tokens (
                token      TEXT PRIMARY KEY,
                email      TEXT NOT NULL,
                role       TEXT NOT NULL DEFAULT 'viewer',
                created_by INTEGER NOT NULL,
                expires_at TEXT NOT NULL,
                used       INTEGER DEFAULT 0
            )
        """)
        conn.commit()


# ── Password hashing ─────────────────────────────────────────────────────────

def _hash_password(password: str) -> str:
    """PBKDF2-HMAC-SHA256 con salt aleatorio. No requiere dependencias externas."""
    salt = secrets.token_hex(16)
    dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 260_000)
    return f"pbkdf2:{salt}:{dk.hex()}"


def _verify_password(password: str, stored: str) -> bool:
    if not stored:
        return False
    try:
        algo, salt, stored_hex = stored.split(":", 2)
        if algo != "pbkdf2":
            return False
        dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 260_000)
        return secrets.compare_digest(dk.hex(), stored_hex)
    except Exception:
        return False


# ── CRUD de usuarios ─────────────────────────────────────────────────────────

def get_user_by_email(email: str) -> dict | None:
    _init_db()
    with _get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM users WHERE email=? AND active=1", (email.lower(),)
        ).fetchone()
        return dict(row) if row else None


def get_user_by_id(user_id: int) -> dict | None:
    _init_db()
    with _get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM users WHERE id=? AND active=1", (user_id,)
        ).fetchone()
        return dict(row) if row else None


def get_user_by_github(github_login: str) -> dict | None:
    _init_db()
    with _get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM users WHERE github_login=? AND active=1", (github_login,)
        ).fetchone()
        return dict(row) if row else None


def list_users() -> list[dict]:
    _init_db()
    with _get_conn() as conn:
        rows = conn.execute(
            "SELECT * FROM users ORDER BY role, created_at"
        ).fetchall()
        return [dict(r) for r in rows]


def create_user(
    email: str,
    display_name: str,
    role: str = "viewer",
    password: str = "",
    github_login: str = "",
) -> dict:
    _init_db()
    pw_hash = _hash_password(password) if password else ""
    with _get_conn() as conn:
        conn.execute(
            """INSERT INTO users
               (email, display_name, role, password_hash, github_login)
               VALUES (?,?,?,?,?)""",
            (email.lower(), display_name, role, pw_hash, github_login),
        )
        conn.commit()
    return get_user_by_email(email)  # type: ignore[return-value]


def update_user(user_id: int, **kwargs) -> None:
    _init_db()
    allowed = {"display_name", "role", "active", "github_login", "email"}
    fields: dict = {k: v for k, v in kwargs.items() if k in allowed}
    if "password" in kwargs and kwargs["password"]:
        fields["password_hash"] = _hash_password(kwargs["password"])
    if not fields:
        return
    set_clause = ", ".join(f"{k}=?" for k in fields)
    values = list(fields.values()) + [user_id]
    with _get_conn() as conn:
        conn.execute(f"UPDATE users SET {set_clause} WHERE id=?", values)
        conn.commit()


def deactivate_user(user_id: int) -> None:
    _init_db()
    with _get_conn() as conn:
        conn.execute("UPDATE users SET active=0 WHERE id=?", (user_id,))
        conn.commit()


def authenticate(email: str, password: str) -> dict | None:
    """Autentica con email + password. Actualiza last_login si ok."""
    user = get_user_by_email(email)
    if not user:
        return None
    if not _verify_password(password, user.get("password_hash", "")):
        return None
    with _get_conn() as conn:
        conn.execute(
            "UPDATE users SET last_login=datetime('now') WHERE id=?", (user["id"],)
        )
        conn.commit()
    return user


def authenticate_or_create_github(github_login: str, display_name: str, email: str = "") -> dict:
    """
    Busca un usuario por github_login. Si no existe, lo crea.
    Si es el primer usuario en el sistema, lo crea como owner.
    """
    user = get_user_by_github(github_login)
    if user:
        # Actualizar last_login
        with _get_conn() as conn:
            conn.execute(
                "UPDATE users SET last_login=datetime('now') WHERE id=?", (user["id"],)
            )
            conn.commit()
        return user

    # Decidir rol: si no hay usuarios activos, el primero es owner
    _init_db()
    with _get_conn() as conn:
        count = conn.execute("SELECT COUNT(*) FROM users WHERE active=1").fetchone()[0]
    role = "owner" if count == 0 else "viewer"

    fallback_email = email or f"{github_login}@github.oauth"
    try:
        return create_user(
            email=fallback_email,
            display_name=display_name or github_login,
            role=role,
            github_login=github_login,
        )
    except Exception:
        # Email duplicado — intentar buscar por email
        return get_user_by_email(fallback_email) or {  # type: ignore[return-value]
            "id": 0, "display_name": github_login, "role": "viewer",
        }


# ── Bootstrap: migración desde BasicAuth ─────────────────────────────────────

def ensure_owner_exists() -> bool:
    """
    Si no hay owners, crea uno desde UI_USERNAME/UI_PASSWORD (BasicAuth legacy).
    Devuelve True si existe al menos un owner activo.
    """
    _init_db()
    with _get_conn() as conn:
        count = conn.execute(
            "SELECT COUNT(*) FROM users WHERE role='owner' AND active=1"
        ).fetchone()[0]
    if count > 0:
        return True

    # Intentar migrar desde BasicAuth
    username = os.getenv("UI_USERNAME", "")
    password = os.getenv("UI_PASSWORD", "")
    if username and password:
        try:
            create_user(
                email=f"{username}@fabrica.local",
                display_name=username,
                role="owner",
                password=password,
            )
            logger.info(
                "RBAC: owner creado automáticamente desde UI_USERNAME='%s'", username
            )
            return True
        except Exception as exc:
            logger.warning("RBAC: no se pudo crear owner desde BasicAuth: %s", exc)

    return False


# ── Permisos ─────────────────────────────────────────────────────────────────

PERMISSIONS: dict[str, set[str]] = {
    "owner": {
        "view", "approve", "launch_feature", "intervene",
        "deploy", "config", "manage_users", "create_project",
    },
    "developer": {
        "view", "approve", "launch_feature", "intervene",
    },
    "viewer": {
        "view",
    },
}

ROLE_LABELS = {
    "owner":     "👑 Owner",
    "developer": "🛠 Developer",
    "viewer":    "👁 Viewer",
}

ROLE_COLORS = {
    "owner":     "#a78bfa",
    "developer": "#fb923c",
    "viewer":    "#94a3b8",
}


def can(user: dict, action: str) -> bool:
    """Comprueba si el usuario tiene permiso para la acción dada."""
    role = user.get("role", "viewer")
    return action in PERMISSIONS.get(role, set())


# ── Tokens de invitación ──────────────────────────────────────────────────────

def create_invite_token(email: str, role: str, created_by: int) -> str:
    """Genera un token de invitación para registrar un nuevo usuario."""
    _init_db()
    token = secrets.token_urlsafe(32)
    expires = (datetime.now(timezone.utc) + timedelta(days=7)).isoformat()
    with _get_conn() as conn:
        conn.execute(
            "INSERT INTO invite_tokens (token, email, role, created_by, expires_at) VALUES (?,?,?,?,?)",
            (token, email.lower(), role, created_by, expires),
        )
        conn.commit()
    return token


def consume_invite_token(token: str) -> dict | None:
    """Valida y consume un token de invitación. Devuelve {email, role} o None."""
    _init_db()
    with _get_conn() as conn:
        row = conn.execute(
            "SELECT * FROM invite_tokens WHERE token=? AND used=0", (token,)
        ).fetchone()
        if not row:
            return None
        row = dict(row)
        expires = datetime.fromisoformat(row["expires_at"])
        if expires.tzinfo is None:
            expires = expires.replace(tzinfo=timezone.utc)
        if datetime.now(timezone.utc) > expires:
            return None
        conn.execute("UPDATE invite_tokens SET used=1 WHERE token=?", (token,))
        conn.commit()
    return {"email": row["email"], "role": row["role"]}
