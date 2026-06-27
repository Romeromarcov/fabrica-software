"""
Tests F4.3 — RBAC en el backend (autorización por rol en endpoints mutantes).

Verifica la decisión pura `authorize_mutation` (devuelve None si se permite, o la acción que
falta si se deniega → 403) y el mapa ruta→acción. Aceptación: una petición mutante sin el rol
requerido es denegada (403); el owner pasa; los GET no se ven afectados; los mutantes públicos
(prechat, push) se permiten a cualquier usuario.
"""
from ui import server


OWNER = {"id": 1, "role": "owner"}
DEVELOPER = {"id": 2, "role": "developer"}
VIEWER = {"id": 3, "role": "viewer"}


# ── required_action_for ──────────────────────────────────────────────────────

def test_map_sensitive_prefixes():
    assert server.required_action_for("/api/meta/build-agent") == "config"
    assert server.required_action_for("/api/deploy/railway") == "deploy"
    assert server.required_action_for("/admin/users/invite") == "manage_users"
    assert server.required_action_for("/project/new") == "create_project"
    assert server.required_action_for("/feature/X/approve") == "approve"
    assert server.required_action_for("/api/sessions/X/intervene") == "intervene"


def test_map_project_new_before_project_prefix():
    # /project/new (create_project) debe ganar sobre /project/ (approve).
    assert server.required_action_for("/project/new") == "create_project"
    assert server.required_action_for("/project/X/approve-roadmap") == "approve"


def test_map_default_action_for_other_mutations():
    assert server.required_action_for("/algo/desconocido") == "launch_feature"


# ── authorize_mutation: la aceptación ────────────────────────────────────────

def test_get_requests_are_never_blocked():
    assert server.authorize_mutation("GET", "/api/deploy/railway", VIEWER) is None


def test_viewer_denied_on_privileged_mutation():
    # Aceptación: petición mutante sin el rol → 403 (acción faltante).
    assert server.authorize_mutation("POST", "/api/deploy/railway", VIEWER) == "deploy"
    assert server.authorize_mutation("POST", "/config", VIEWER) == "config"
    assert server.authorize_mutation("POST", "/api/meta/build-agent", VIEWER) == "config"


def test_developer_denied_on_owner_only_action():
    # developer NO tiene config/deploy/create_project.
    assert server.authorize_mutation("POST", "/api/deploy/railway", DEVELOPER) == "deploy"
    assert server.authorize_mutation("POST", "/config", DEVELOPER) == "config"


def test_developer_allowed_on_its_actions():
    assert server.authorize_mutation("POST", "/new", DEVELOPER) is None              # launch_feature
    assert server.authorize_mutation("POST", "/feature/X/approve", DEVELOPER) is None  # approve
    assert server.authorize_mutation("POST", "/api/sessions/X/intervene", DEVELOPER) is None


def test_owner_allowed_everywhere():
    for path in ("/api/deploy/railway", "/config", "/api/meta/build-agent",
                 "/project/new", "/admin/users/invite", "/new"):
        assert server.authorize_mutation("POST", path, OWNER) is None


def test_no_user_is_denied():
    assert server.authorize_mutation("POST", "/new", None) == "launch_feature"


def test_public_mutations_allowed_for_any_user():
    # prechat y push/subscribe: cualquier usuario autenticado (incluido viewer).
    assert server.authorize_mutation("POST", "/api/prechat", VIEWER) is None
    assert server.authorize_mutation("POST", "/api/push/subscribe", VIEWER) is None


def test_delete_and_put_are_mutating():
    assert server.authorize_mutation("DELETE", "/api/skills/x", VIEWER) == "config"
    assert server.authorize_mutation("PUT", "/api/skills/x", VIEWER) == "config"
