"""Tests del soporte de despliegue en Railway: mapeo openclaw, TARGET_REPOS, clone."""
import shutil
import subprocess

import pytest

import config
from openclaw.client import profile_for, AGENT_PROFILE_MAP


# ── Mapeo OpenClaw corregido + fallback ────────────────────────────────────────

def test_profile_map_matches_current_agents():
    # Las claves deben ser los agent_key reales del pipeline (= SYSTEM_PROMPT_PATHS)
    for key in ("a1_pm", "a2_db", "a3_mcp", "a4_backend", "a5_frontend",
                "a6_refactor", "a7_qa", "a8_secops"):
        assert key in AGENT_PROFILE_MAP
    # Las claves viejas/equivocadas ya NO están
    for old in ("a2_backend", "a3_frontend", "a4_qa", "a6_db", "a8_mcp"):
        assert old not in AGENT_PROFILE_MAP


def test_profile_for_fallback():
    assert profile_for("a4_backend") == "a4-backend"
    # agent_key no mapeado → slug determinista, nunca rompe
    assert profile_for("a99_nuevo") == "a99-nuevo"


# ── Parser de TARGET_REPOS ──────────────────────────────────────────────────────

def test_parse_target_repos_name_url_branch(monkeypatch):
    monkeypatch.setattr(
        config, "TARGET_REPOS",
        "omni-erp=https://github.com/org/omni-erp.git#main, https://github.com/org/otro.git",
    )
    repos = config.parse_target_repos()
    assert repos[0] == {"name": "omni-erp",
                        "url": "https://github.com/org/omni-erp.git", "branch": "main"}
    # sin nombre → derivado de la URL; sin rama → vacío
    assert repos[1]["name"] == "otro"
    assert repos[1]["url"] == "https://github.com/org/otro.git"
    assert repos[1]["branch"] == ""


def test_parse_target_repos_empty(monkeypatch):
    monkeypatch.setattr(config, "TARGET_REPOS", "")
    assert config.parse_target_repos() == []


# ── Clone-on-startup (git real, hermético) ─────────────────────────────────────

@pytest.mark.skipif(shutil.which("git") is None, reason="git no disponible")
def test_clone_or_update_repo(tmp_path):
    from tools.git_tools import clone_or_update_repo

    origin = tmp_path / "origin"
    origin.mkdir()

    def run(*a, cwd):
        subprocess.run(["git", *a], cwd=str(cwd), check=True, capture_output=True, text=True)

    run("init", "-b", "main", cwd=origin)
    run("config", "user.email", "t@t.com", cwd=origin)
    run("config", "user.name", "t", cwd=origin)
    (origin / "f.txt").write_text("v1\n")
    run("add", "-A", cwd=origin); run("commit", "-m", "c1", cwd=origin)

    dest = tmp_path / "dest"
    # 1) clona
    assert clone_or_update_repo(str(origin), str(dest), branch="main") is True
    assert (dest / "f.txt").exists()

    # 2) nuevo commit en origin → update trae el cambio (fetch + reset --hard)
    (origin / "f2.txt").write_text("v2\n")
    run("add", "-A", cwd=origin); run("commit", "-m", "c2", cwd=origin)
    assert clone_or_update_repo(str(origin), str(dest), branch="main") is True
    assert (dest / "f2.txt").exists()


def test_auth_url_injects_token():
    from tools.git_tools import _auth_url
    out = _auth_url("https://github.com/org/repo.git", "TOK", "user")
    assert out == "https://user:TOK@github.com/org/repo.git"
    # sin token → sin cambios; con credenciales ya presentes → sin doble inyección
    assert _auth_url("https://github.com/org/repo.git", "") == "https://github.com/org/repo.git"
    assert _auth_url("https://u:t@github.com/x.git", "TOK") == "https://u:t@github.com/x.git"
