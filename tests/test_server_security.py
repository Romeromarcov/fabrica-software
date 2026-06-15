"""Tests del Bloque A (PLAN_BLINDAJE_TOTAL) — endurecimiento de seguridad de la UI.

Cubre:
  A1.2 — Autenticación obligatoria (la UI no arranca sin auth).
  A1.3 — Validación anti path-traversal de project_id / feature_id.
  A1.4 — Whitelist de acciones de aprobación y de repo_name.
  A3.4 — Features importados requieren aprobación antes de ejecutarse.
"""
import asyncio

import pytest
from fastapi import HTTPException

import ui.server as srv


# ── A1.3 — path traversal ─────────────────────────────────────────────────────

def test_safe_run_dir_accepts_valid_id():
    p = srv._safe_run_dir("20260615_120000_feature")
    assert str(p).startswith(str(srv._RUNS_DIR_RESOLVED))


@pytest.mark.parametrize("bad", [
    "../../etc/passwd",
    "..",
    "a/b",
    "/etc/passwd",
    "foo/../../bar",
    "",
    "x" * 65,            # supera 64 chars
    "with space",
    "semi;colon",
    "dot.dot",           # el punto no está permitido por la regex
])
def test_safe_run_dir_rejects_traversal_and_invalid(bad):
    with pytest.raises(HTTPException) as ei:
        srv._safe_run_dir(bad)
    assert ei.value.status_code == 403


def test_safe_run_dir_stays_under_runs_dir():
    # Un id válido jamás resuelve fuera de RUNS_DIR
    p = srv._safe_run_dir("abc-DEF_123")
    assert srv._RUNS_DIR_RESOLVED == p or srv._RUNS_DIR_RESOLVED in p.parents


# ── A1.4 — whitelist de acciones ──────────────────────────────────────────────

@pytest.mark.parametrize("action", ["approve", "cancel", "vetar", "reject", "CONTINUAR"])
def test_validate_action_allows_whitelist(action):
    assert srv._validate_action(action) == action


@pytest.mark.parametrize("action", ["rm -rf /", "delete", "../x", "", "APPROVE"])
def test_validate_action_rejects_others(action):
    with pytest.raises(HTTPException) as ei:
        srv._validate_action(action)
    assert ei.value.status_code == 400


# ── A1.4 — whitelist de repo_name ─────────────────────────────────────────────

def test_validate_repo_name_against_list_repos(monkeypatch):
    monkeypatch.setattr(srv, "list_repos", lambda: [{"name": "omni-erp"}, {"name": "otro"}])
    assert srv._validate_repo_name(" omni-erp ") == "omni-erp"
    for bad in ["no-existe", "", "../../etc"]:
        with pytest.raises(HTTPException) as ei:
            srv._validate_repo_name(bad)
        assert ei.value.status_code == 400


# ── A1.2 — autenticación obligatoria ──────────────────────────────────────────

def test_enforce_ui_auth_raises_when_no_auth(monkeypatch):
    monkeypatch.setattr(srv, "RBAC_ENABLED", False)
    monkeypatch.setattr(srv, "_basic_auth_on", False)
    monkeypatch.setattr(srv, "_UI_ALLOW_NO_AUTH", False)
    with pytest.raises(RuntimeError):
        srv._enforce_ui_auth_configured()


def test_enforce_ui_auth_ok_with_basic_auth(monkeypatch):
    monkeypatch.setattr(srv, "RBAC_ENABLED", False)
    monkeypatch.setattr(srv, "_basic_auth_on", True)
    monkeypatch.setattr(srv, "_UI_ALLOW_NO_AUTH", False)
    srv._enforce_ui_auth_configured()  # no debe lanzar


def test_enforce_ui_auth_ok_with_rbac(monkeypatch):
    monkeypatch.setattr(srv, "RBAC_ENABLED", True)
    monkeypatch.setattr(srv, "_basic_auth_on", False)
    monkeypatch.setattr(srv, "_UI_ALLOW_NO_AUTH", False)
    srv._enforce_ui_auth_configured()


def test_enforce_ui_auth_allows_optout(monkeypatch):
    monkeypatch.setattr(srv, "RBAC_ENABLED", False)
    monkeypatch.setattr(srv, "_basic_auth_on", False)
    monkeypatch.setattr(srv, "_UI_ALLOW_NO_AUTH", True)
    srv._enforce_ui_auth_configured()  # solo advierte, no lanza


# ── A3.4 — features importados requieren aprobación ───────────────────────────

def test_get_ready_indices_skips_pending_approval():
    from tools.branch_manager import get_ready_indices
    backlog = [
        {"name": "a", "status": "pending", "depends_on": [], "pending_approval": True},
        {"name": "b", "status": "pending", "depends_on": []},
    ]
    ready = get_ready_indices(backlog, {}, max_parallel=5)
    assert ready == [1]  # 'a' (importado sin aprobar) se omite


def test_pick_next_feature_skips_pending_approval(monkeypatch, tmp_path):
    import graph_project
    monkeypatch.setattr(graph_project, "save_run_metadata", lambda *a, **k: None)
    state = {
        "project_id": "p1",
        "backlog": [
            {"name": "a", "status": "pending", "pending_approval": True, "depends_on": []},
            {"name": "b", "status": "pending", "depends_on": []},
        ],
    }
    out = graph_project.pick_next_feature(state)
    assert out["current_feature_index"] == 1  # se salta 'a' y elige 'b'


def test_import_sessions_tags_imported_pending(monkeypatch, tmp_path):
    """import_sessions marca los features con source=imported y pending_approval=True."""
    import json
    from starlette.datastructures import UploadFile, Headers
    from io import BytesIO

    # Redirigir RUNS_DIR del módulo y su versión resuelta al tmp_path
    monkeypatch.setattr(srv, "RUNS_DIR", tmp_path)
    monkeypatch.setattr(srv, "_RUNS_DIR_RESOLVED", tmp_path.resolve())
    proj = tmp_path / "proj_x"
    proj.mkdir()
    (proj / "metadata.json").write_text(json.dumps({"backlog": []}), encoding="utf-8")

    monkeypatch.setattr(
        srv, "parse_session_plan", lambda md: [{"name": "Feat Uno", "description": "x"}],
        raising=False,
    )
    # parse_session_plan se importa dentro de la función desde tools.session_importer;
    # parcheamos ahí para asegurar el valor.
    import tools.session_importer as si
    monkeypatch.setattr(si, "parse_session_plan",
                        lambda md: [{"name": "Feat Uno", "description": "x"}])

    upload = UploadFile(
        filename="sesiones.md",
        file=BytesIO(b"# plan\n- Feat Uno"),
        headers=Headers({"content-type": "text/markdown"}),
    )
    result = asyncio.run(srv.import_sessions("proj_x", upload))
    assert result["ok"] is True
    assert result["pending_approval"] is True

    meta = json.loads((proj / "metadata.json").read_text())
    assert len(meta["backlog"]) == 1
    f = meta["backlog"][0]
    assert f["source"] == "imported"
    assert f["pending_approval"] is True
