"""Tests de RBAC (PLAN_MEJORAS IX-1): tools/auth.py (guards) + núcleo de auth_manager."""
import pytest

from tools.auth import (
    AuthorizationError,
    check_access,
    require_can,
    require_role,
)
from tools import auth_manager as am

OWNER = {"role": "owner"}
DEV = {"role": "developer"}
VIEWER = {"role": "viewer"}


# ── auth_manager: matriz can() + hashing (núcleo de seguridad, antes sin tests) ──

def test_can_owner_all():
    for action in am.PERMISSIONS["owner"]:
        assert am.can(OWNER, action)


def test_can_developer_cannot_deploy():
    assert am.can(DEV, "launch_feature") is True
    assert am.can(DEV, "deploy") is False
    assert am.can(DEV, "manage_users") is False


def test_can_viewer_only_view():
    assert am.can(VIEWER, "view") is True
    assert am.can(VIEWER, "approve") is False


def test_can_unknown_role_denied():
    assert am.can({"role": "ghost"}, "view") is False


def test_password_hash_roundtrip():
    h = am._hash_password("s3cr3t-clave")
    assert h != "s3cr3t-clave"                 # no es texto plano
    assert am._verify_password("s3cr3t-clave", h) is True
    assert am._verify_password("incorrecta", h) is False


# ── tools/auth: decorators ──────────────────────────────────────────────────

def test_require_can_allows():
    @require_can("deploy")
    def deploy(user):
        return "deployed"
    assert deploy(OWNER) == "deployed"


def test_require_can_denies():
    @require_can("deploy")
    def deploy(user):
        return "deployed"
    with pytest.raises(AuthorizationError):
        deploy(DEV)


def test_require_can_user_as_kwarg():
    @require_can("launch_feature")
    def launch(*, user, name):
        return name
    assert launch(user=DEV, name="feat-x") == "feat-x"


def test_require_can_unknown_action_raises_at_decoration():
    with pytest.raises(ValueError, match="acción desconocida"):
        @require_can("teleport")
        def f(user):
            return 1


def test_require_role_allows_and_denies():
    @require_role("owner", "developer")
    def launch(user):
        return "ok"
    assert launch(DEV) == "ok"
    with pytest.raises(AuthorizationError):
        launch(VIEWER)


def test_require_role_unknown_role_raises():
    with pytest.raises(ValueError, match="desconocido"):
        @require_role("superadmin")
        def f(user):
            return 1


def test_missing_user_raises():
    @require_can("view")
    def f(x):
        return x
    with pytest.raises(AuthorizationError, match="no se pudo determinar"):
        f("no-soy-user")


def test_check_access_wrapper():
    assert check_access(OWNER, "config") is True
    assert check_access(VIEWER, "config") is False
