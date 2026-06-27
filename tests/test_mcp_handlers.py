"""
Tests F5 — handlers del servidor MCP y registro de tools.

Los handlers se prueban con dependencias mockeadas (config.list_repos, read_run_metadata) y
un `launcher` inyectado → sin lanzar el grafo real ni necesitar LLM. También se verifica que
mcp_server registra exactamente el contrato de tools esperado.
"""
import pytest

from tools import mcp_handlers as h


# ── list_repos ───────────────────────────────────────────────────────────────

def test_list_repos_ok(monkeypatch):
    monkeypatch.setattr("config.list_repos", lambda: [{"name": "omnierp", "path": "/r/omnierp"}])
    r = h.list_repos()
    assert r["ok"] and r["repos"][0]["name"] == "omnierp"


def test_list_repos_tolerates_error(monkeypatch):
    def boom():
        raise RuntimeError("WORKSPACES_ROOT no existe")
    monkeypatch.setattr("config.list_repos", boom)
    r = h.list_repos()
    assert r["ok"] is False and "WORKSPACES_ROOT" in r["error"]


# ── get_feature_status ───────────────────────────────────────────────────────

def test_get_feature_status_found(monkeypatch):
    monkeypatch.setattr("tools.file_tools.read_run_metadata",
                        lambda fid: {"status": "en_progreso", "current_agent": "a4_backend"})
    r = h.get_feature_status("F1")
    assert r["ok"] and r["status"] == "en_progreso" and r["current_agent"] == "a4_backend"


def test_get_feature_status_not_found(monkeypatch):
    monkeypatch.setattr("tools.file_tools.read_run_metadata", lambda fid: {})
    assert h.get_feature_status("noexiste")["ok"] is False


def test_get_feature_status_requires_id():
    assert h.get_feature_status("")["ok"] is False


# ── create_feature ───────────────────────────────────────────────────────────

def _stub_repos(monkeypatch):
    monkeypatch.setattr("config.list_repos", lambda: [{"name": "omnierp", "path": "/r/omnierp"}])
    monkeypatch.setattr("config.resolve_repo_path", lambda name: f"/r/{name}")
    monkeypatch.setattr("tools.file_tools.save_run_metadata", lambda *a, **k: None)


def test_create_feature_launches_async(monkeypatch):
    _stub_repos(monkeypatch)
    launched = {}

    def fake_launcher(feature_id, feature_name, mode, repo_name, repo_path):
        launched.update(feature_id=feature_id, repo=repo_name, mode=mode)

    r = h.create_feature("crud usuarios", "omnierp", mode="lite", launcher=fake_launcher)
    assert r["ok"] is True
    assert r["feature_id"] == launched["feature_id"]   # devolvió el id que lanzó
    assert launched["repo"] == "omnierp" and launched["mode"] == "lite"


def test_create_feature_rejects_unknown_repo(monkeypatch):
    _stub_repos(monkeypatch)
    r = h.create_feature("x", "inexistente", launcher=lambda *a: None)
    assert r["ok"] is False and "repo no encontrado" in r["error"]


def test_create_feature_rejects_bad_mode(monkeypatch):
    _stub_repos(monkeypatch)
    r = h.create_feature("x", "omnierp", mode="turbo", launcher=lambda *a: None)
    assert r["ok"] is False and "modo inválido" in r["error"]


def test_create_feature_requires_name():
    assert h.create_feature("", "omnierp", launcher=lambda *a: None)["ok"] is False


def test_run_pipeline_rejects_unknown_pipeline():
    r = h.run_pipeline("x", "omnierp", pipeline="marketing", launcher=lambda *a: None)
    assert r["ok"] is False


def test_make_feature_id_slug():
    fid = h.make_feature_id("CRUD de Usuarios")
    assert fid.endswith("crud_de_usuarios") and "_" in fid


# ── servidor MCP: contrato de tools ──────────────────────────────────────────

def test_mcp_server_registers_expected_tools():
    import asyncio
    import mcp_server
    tools = asyncio.run(mcp_server.mcp.list_tools())
    names = {t.name for t in tools}
    assert set(mcp_server.TOOL_NAMES) == names


def test_mcp_server_import_has_no_side_effects():
    # Importar no debe arrancar el servidor (solo bajo __main__/run()).
    import importlib
    import mcp_server
    importlib.reload(mcp_server)
    assert mcp_server.mcp is not None
