"""
Verificación de los módulos PLAN_MEJORAS (de CLAIMED → VERIFIED).

Tests offline y deterministas: NO tocan red ni LLM. Toda llamada a un proveedor
(call_agent, httpx, Anthropic SDK) se mockea o se sortea testeando helpers puros.

Cobertura:
  - event_bus      (VII-2 / VIII-1): round-trip de eventos e intervenciones
  - dynamic_router (VIII-2):         contrato de predict_routing()
  - auth_manager   (IX-1 / P0-B):    hash/verify de password + matriz de roles can()
  - debate_panel   (VIII-3):         importabilidad + gating del flag en el grafo
  - a0_prechat     (VII-1):          importabilidad + helper puro extract_refined_brief
  - railway_client (VII-3):          construcción/parseo de requests con _gql mockeado
  - lightning      (P0-A):           Literal de mode + routing salta gates pesados
"""
from __future__ import annotations

import asyncio

import pytest


# ── event_bus (VII-2 / VIII-1) ────────────────────────────────────────────────

def test_event_bus_post_and_get_recent(monkeypatch, tmp_path):
    """emit() persiste un evento y get_recent_events() lo devuelve."""
    import tools.event_bus as eb
    # Redirigir el directorio de runs a tmp para no escribir en el volumen real
    monkeypatch.setattr(eb, "RUNS_DIR", tmp_path)

    fid = "feat-eventbus-iso"
    eb.emit(fid, "A4 Backend", "info", model="claude-sonnet-4-6", msg="hola mundo")
    eb.emit_info(fid, "A5 Frontend", "segundo evento")

    events = eb.get_recent_events(fid)
    assert len(events) == 2
    # El primer evento conserva los campos clave
    assert events[0]["agent"] == "A4 Backend"
    assert events[0]["status"] == "info"
    assert events[0]["msg"] == "hola mundo"
    assert events[1]["msg"] == "segundo evento"


def test_event_bus_get_recent_missing_feature(monkeypatch, tmp_path):
    """get_recent_events() de un feature inexistente devuelve lista vacía."""
    import tools.event_bus as eb
    monkeypatch.setattr(eb, "RUNS_DIR", tmp_path)
    assert eb.get_recent_events("no-existe") == []


def test_event_bus_intervention_round_trip(monkeypatch, tmp_path):
    """post_intervention() → pop_intervention() round-trip; segundo pop = None."""
    import tools.event_bus as eb
    monkeypatch.setattr(eb, "RUNS_DIR", tmp_path)

    fid = "feat-intervention-iso"
    assert eb.pop_intervention(fid) is None   # nada pendiente al inicio

    eb.post_intervention(fid, "  usa async en vez de threads  ")
    popped = eb.pop_intervention(fid)
    assert popped == "usa async en vez de threads"   # se hace strip()

    # Segundo pop: la intervención ya se consumió (atómico)
    assert eb.pop_intervention(fid) is None


# ── dynamic_router (VIII-2) ───────────────────────────────────────────────────

def test_dynamic_router_default_without_project():
    """predict_routing() sin project_id devuelve el default desactivado, sin crash."""
    from tools.dynamic_router import predict_routing
    pred = predict_routing("añadir endpoint de login", project_id=None)
    assert isinstance(pred, dict)
    # Contrato: flags booleanos + metadata
    for flag in ("needs_backend", "needs_frontend", "needs_db", "needs_mcp", "activated"):
        assert isinstance(pred[flag], bool)
    assert pred["activated"] is False          # sin historial → desactivado
    assert pred["history_size"] == 0
    assert isinstance(pred["confidence"], float)


def test_dynamic_router_insufficient_history(monkeypatch):
    """Con historial < MIN_FEATURES el router queda desactivado (no entrena)."""
    import tools.dynamic_router as dr
    # Historial vacío aunque el proyecto exista
    monkeypatch.setattr(dr, "_load_feature_history", lambda pid: [])
    pred = dr.predict_routing("dashboard nuevo", project_id="proj-1")
    assert pred["activated"] is False
    assert isinstance(pred, dict)


def test_dynamic_router_build_hint_empty_when_inactive():
    """build_routing_hint() no genera texto si activated=False."""
    from tools.dynamic_router import build_routing_hint
    assert build_routing_hint({"activated": False}) == ""


# ── auth_manager (IX-1 / P0-B) ────────────────────────────────────────────────

def test_auth_password_hash_verify_round_trip():
    """_hash_password/_verify_password: round-trip correcto y rechazo de mala pass."""
    from tools.auth_manager import _hash_password, _verify_password
    h = _hash_password("S3cret-pass!")
    assert h.startswith("pbkdf2:")
    assert _verify_password("S3cret-pass!", h) is True
    assert _verify_password("otra-cosa", h) is False
    # Hash vacío (usuario sin password, p.ej. solo OAuth) → siempre False
    assert _verify_password("lo-que-sea", "") is False


def test_auth_password_hash_is_salted():
    """Dos hashes de la misma password difieren (salt aleatorio)."""
    from tools.auth_manager import _hash_password, _verify_password
    h1 = _hash_password("misma")
    h2 = _hash_password("misma")
    assert h1 != h2
    assert _verify_password("misma", h1) and _verify_password("misma", h2)


def test_auth_role_matrix_can():
    """can(): owner puede todo; viewer no puede launch/deploy; developer intermedio."""
    from tools.auth_manager import can

    owner = {"role": "owner"}
    developer = {"role": "developer"}
    viewer = {"role": "viewer"}

    # Owner: acceso total
    for action in ("view", "launch_feature", "deploy", "config", "manage_users"):
        assert can(owner, action) is True

    # Viewer: solo lectura — NO puede lanzar ni desplegar
    assert can(viewer, "view") is True
    assert can(viewer, "launch_feature") is False
    assert can(viewer, "deploy") is False

    # Developer: puede lanzar/intervenir pero NO deploy ni manage_users
    assert can(developer, "launch_feature") is True
    assert can(developer, "deploy") is False
    assert can(developer, "manage_users") is False

    # Rol desconocido / acción desconocida → False seguro
    assert can({"role": "ghost"}, "view") is False
    assert can(owner, "accion_inexistente") is False


# ── debate_panel (VIII-3) ─────────────────────────────────────────────────────

def test_debate_panel_node_importable():
    """El nodo run_debate existe y es importable/llamable."""
    from nodes.debate_panel import run_debate
    assert callable(run_debate)


def test_debate_panel_skips_without_master_plan(monkeypatch):
    """run_debate sin master_plan devuelve debate_done=True sin llamar al LLM."""
    import nodes.debate_panel as dp

    # Centinela: si se llamara a call_agent, el test fallaría
    def _boom(*a, **k):  # pragma: no cover - no debe ejecutarse
        raise AssertionError("call_agent no debería invocarse sin master_plan")

    monkeypatch.setattr(dp, "call_agent", _boom)
    out = dp.run_debate({"master_plan": "", "feature_id": ""})
    assert out["debate_done"] is True
    assert "omitido" in out["debate_summary"].lower()


def test_graph_route_skips_debate_when_flag_disabled(monkeypatch):
    """Con DEBATE_PANEL_ENABLED=False, HIGH risk NO va a debate_panel."""
    import config
    import graph

    monkeypatch.setattr(config, "DEBATE_PANEL_ENABLED", False, raising=False)
    state = {
        "risk_level": "HIGH",
        "mode": "completo",
        "debate_done": False,
        # campos que consume _route_after_plan vía approval_action
        "confidence_score": 50,
        "project_mode": True,
    }
    # Sin flag → cae al flujo normal de aprobación, jamás "debate_panel"
    assert graph._route_after_plan_or_debate(state) != "debate_panel"


def test_graph_route_enters_debate_when_flag_enabled(monkeypatch):
    """Con DEBATE_PANEL_ENABLED=True + HIGH + no-lightning + no-done → debate_panel."""
    import config
    import graph

    monkeypatch.setattr(config, "DEBATE_PANEL_ENABLED", True, raising=False)
    state = {
        "risk_level": "HIGH",
        "mode": "completo",
        "debate_done": False,
        "confidence_score": 50,
        "project_mode": True,
    }
    assert graph._route_after_plan_or_debate(state) == "debate_panel"


def test_graph_route_no_debate_when_already_done(monkeypatch):
    """Aun con flag y HIGH, si debate_done=True no se re-entra al debate (no loop)."""
    import config
    import graph

    monkeypatch.setattr(config, "DEBATE_PANEL_ENABLED", True, raising=False)
    state = {
        "risk_level": "HIGH",
        "mode": "completo",
        "debate_done": True,
        "confidence_score": 50,
        "project_mode": True,
    }
    assert graph._route_after_plan_or_debate(state) != "debate_panel"


def test_graph_route_lightning_skips_debate(monkeypatch):
    """Lightning nunca pasa por el debate aunque el flag esté activo y risk=HIGH."""
    import config
    import graph

    monkeypatch.setattr(config, "DEBATE_PANEL_ENABLED", True, raising=False)
    state = {
        "risk_level": "HIGH",
        "mode": "lightning",
        "debate_done": False,
        "confidence_score": 50,
        "project_mode": True,
    }
    assert graph._route_after_plan_or_debate(state) != "debate_panel"


# ── a0_prechat (VII-1) ────────────────────────────────────────────────────────

def test_a0_prechat_importable():
    """stream_response es importable (nodo LLM — no se ejecuta aquí)."""
    from nodes.a0_prechat import stream_response
    assert callable(stream_response)


def test_a0_prechat_extract_refined_brief_from_assistant():
    """extract_refined_brief extrae el bloque REFINED_BRIEF del último assistant."""
    from nodes.a0_prechat import extract_refined_brief
    conv = [
        {"role": "user", "content": "quiero login"},
        {"role": "assistant", "content": "preámbulo\nREFINED_BRIEF\nLogin con OAuth"},
    ]
    out = extract_refined_brief(conv)
    assert out.startswith("REFINED_BRIEF")
    assert "Login con OAuth" in out


def test_a0_prechat_extract_refined_brief_fallback():
    """Sin bloque explícito, genera un brief de respaldo con los mensajes del user."""
    from nodes.a0_prechat import extract_refined_brief
    conv = [
        {"role": "user", "content": "endpoint de reportes"},
        {"role": "assistant", "content": "ok, ¿qué columnas?"},
    ]
    out = extract_refined_brief(conv)
    assert "REFINED_BRIEF" in out
    assert "endpoint de reportes" in out


# ── railway_client (VII-3) ────────────────────────────────────────────────────

def test_railway_headers_requires_token(monkeypatch):
    """_headers() lanza ValueError claro si no hay RAILWAY_TOKEN ni ConfigStore."""
    import sys
    import types
    import tools.railway_client as rc

    monkeypatch.delenv("RAILWAY_TOKEN", raising=False)
    # Forzar que el fallback al ConfigStore no aporte token (devuelve {})
    fake = types.ModuleType("ui.config_store")

    class _CS:
        def load(self, masked=False):
            return {}

    fake.ConfigStore = _CS
    monkeypatch.setitem(sys.modules, "ui.config_store", fake)

    with pytest.raises(ValueError):
        rc._headers()


def test_railway_headers_builds_bearer(monkeypatch):
    """_headers() construye Authorization Bearer + Content-Type JSON con token."""
    import tools.railway_client as rc
    monkeypatch.setenv("RAILWAY_TOKEN", "railway_abc123")
    h = rc._headers()
    assert h["Authorization"] == "Bearer railway_abc123"
    assert h["Content-Type"] == "application/json"


def test_railway_trigger_deploy_parses_mutation(monkeypatch):
    """trigger_deploy() pasa el serviceId correcto a _gql y parsea el deploymentId."""
    import tools.railway_client as rc

    captured = {}

    async def _fake_gql(query, variables=None):
        captured["query"] = query
        captured["variables"] = variables
        return {"serviceInstanceDeploy": "dep-xyz-789"}

    monkeypatch.setattr(rc, "_gql", _fake_gql)
    out = asyncio.run(rc.trigger_deploy("svc-123"))

    assert captured["variables"]["serviceId"] == "svc-123"
    assert out["ok"] is True
    assert out["deployment_id"] == "dep-xyz-789"
    assert out["status"] == "BUILDING"


def test_railway_trigger_deploy_validates_service_id():
    """trigger_deploy() sin service_id lanza ValueError (no llega a la red)."""
    import tools.railway_client as rc
    with pytest.raises(ValueError):
        asyncio.run(rc.trigger_deploy(""))


def test_railway_get_status_parses_response(monkeypatch):
    """get_deployment_status() parsea status/url (prefiere staticUrl) de _gql."""
    import tools.railway_client as rc

    async def _fake_gql(query, variables=None):
        assert variables["deploymentId"] == "dep-1"
        return {"deployment": {
            "id": "dep-1", "status": "SUCCESS",
            "staticUrl": "https://app.up.railway.app", "url": "https://fallback",
            "createdAt": "2026-06-16T00:00:00Z",
        }}

    monkeypatch.setattr(rc, "_gql", _fake_gql)
    out = asyncio.run(rc.get_deployment_status("dep-1"))
    assert out["status"] == "SUCCESS"
    assert out["url"] == "https://app.up.railway.app"   # staticUrl tiene prioridad
    assert out["id"] == "dep-1"


def test_railway_get_status_requires_id():
    """get_deployment_status() sin id devuelve error sin tocar la red."""
    import tools.railway_client as rc
    out = asyncio.run(rc.get_deployment_status(""))
    assert "error" in out


# ── lightning mode (P0-A) ─────────────────────────────────────────────────────

def test_lightning_is_valid_mode_literal():
    """'lightning' es un valor válido del Literal mode en state.py."""
    import typing
    import state
    mode_type = state.FabricaState.__annotations__["mode"]
    # Literal["completo","lite","auto","lightning"]
    assert "lightning" in typing.get_args(mode_type)


def test_lightning_initial_state_accepts_mode():
    """initial_state acepta mode='lightning' y lo conserva."""
    from state import initial_state
    st = initial_state(
        feature_id="f1", feature_name="rápido", mode="lightning",
        repo_name="r", repo_path="/tmp/r",
    )
    assert st["mode"] == "lightning"


def test_lightning_routing_skips_heavy_gates():
    """Lightning salta las puertas pesadas en cada nodo de routing del grafo."""
    import graph
    light = {"mode": "lightning"}

    # A4 Backend → A10 directo (omite A5/A6/A7/A8/A9)
    assert graph._route_after_backend(light) == "a10_code_writer"
    # A5 Frontend → A10 (omite A6/A7/A8/A9)
    assert graph._route_after_frontend(light) == "a10_code_writer"
    # A10 → lightning_complete (omite sandbox)
    assert graph._route_after_code_writer(light) == "lightning_complete"


def test_lightning_route_after_approval():
    """Tras aprobación, lightning va a A4 backend (omite A2 DB / A3 MCP)."""
    import graph
    st = {"founder_approval": True, "mode": "lightning", "skip_backend": False}
    assert graph._route_after_approval(st) == "lightning"
    # lightning + skip_backend → frontend directo
    st2 = {"founder_approval": True, "mode": "lightning", "skip_backend": True}
    assert graph._route_after_approval(st2) == "frontend_only"
