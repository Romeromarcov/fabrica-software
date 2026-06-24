"""
tools/auth.py — Guards de autorización RBAC (PLAN_MEJORAS IX-1, núcleo offline).

Decorators framework-agnósticos construidos sobre `auth_manager.can()` y la matriz
PERMISSIONS. NO dependen de Flask/sesiones: protegen cualquier función que reciba un
`user` (dict con 'role') vía kwarg `user=` o como primer argumento posicional. La capa
de sesión web (Flask-Login, login.html, admin_users.html) es UI y queda fuera de este
núcleo verificable.

Uso:
    @require_can("deploy")
    def trigger_deploy(user, ...): ...

    @require_role("owner", "developer")
    def launch(user, ...): ...

Sin side effects al importar.
"""
from __future__ import annotations

import functools
from typing import Callable

from tools.auth_manager import PERMISSIONS, can


class AuthorizationError(PermissionError):
    """Se lanza cuando un usuario no tiene permiso para la acción/rol requerido."""


def _extract_user(args: tuple, kwargs: dict) -> dict:
    user = kwargs.get("user")
    if user is None and args and isinstance(args[0], dict):
        user = args[0]
    if not isinstance(user, dict):
        raise AuthorizationError(
            "no se pudo determinar el usuario (pásalo como kwarg user= o primer argumento dict)"
        )
    return user


def check_access(user: dict, action: str) -> bool:
    """Wrapper explícito sobre auth_manager.can() (no lanza)."""
    return can(user, action)


def require_can(action: str) -> Callable:
    """Decorator: exige que el usuario tenga permiso para `action`, o lanza AuthorizationError."""
    if not any(action in perms for perms in PERMISSIONS.values()):
        raise ValueError(f"acción desconocida '{action}' (no está en ninguna entrada de PERMISSIONS)")

    def deco(fn: Callable) -> Callable:
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            user = _extract_user(args, kwargs)
            if not can(user, action):
                raise AuthorizationError(
                    f"el rol '{user.get('role', 'viewer')}' no puede '{action}'"
                )
            return fn(*args, **kwargs)
        return wrapper
    return deco


def require_role(*roles: str) -> Callable:
    """Decorator: exige que el rol del usuario esté en `roles`, o lanza AuthorizationError."""
    allowed = set(roles)
    unknown = allowed - set(PERMISSIONS)
    if unknown:
        raise ValueError(f"rol(es) desconocido(s): {sorted(unknown)}")

    def deco(fn: Callable) -> Callable:
        @functools.wraps(fn)
        def wrapper(*args, **kwargs):
            user = _extract_user(args, kwargs)
            if user.get("role") not in allowed:
                raise AuthorizationError(
                    f"el rol '{user.get('role', 'viewer')}' no está autorizado "
                    f"(se requiere uno de {sorted(allowed)})"
                )
            return fn(*args, **kwargs)
        return wrapper
    return deco
