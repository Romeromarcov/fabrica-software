"""
Tests de tools/factory_pr.py — orquestación git/PR del flujo de aprobación. git (runner) y la
API de GitHub (gh) se inyectan; no se ejecuta git real ni se llama a la red.
"""
import pytest

from tools import factory_proposals as fp
from tools import factory_pr as fpr


@pytest.fixture
def store(tmp_path):
    return tmp_path / "props.json"


@pytest.fixture(autouse=True)
def _enable_flag(monkeypatch):
    monkeypatch.setattr("config.FACTORY_MODIFIER_ENABLED", True, raising=False)
    monkeypatch.setattr("config.GITHUB_REPO", "Romeromarcov/fabrica-software", raising=False)


def _proposal(store):
    return fp.add_proposal(
        {"kind": "prompt", "target": "agents/a/system_prompt.md", "mode": "append",
         "content": "x"}, rationale="mejora", risk="low", path=store)


def test_apply_and_open_pr_happy_path(store, tmp_path):
    calls = []
    def runner(args, cwd=None): calls.append(args); return ""
    def gh(method, path, payload=None):
        assert method == "POST" and path.endswith("/pulls")
        return {"html_url": "https://github.com/x/y/pull/9", "number": 9}
    applied = []
    def apply_fn(change, **k): applied.append(change); return {"applied": True}

    item = _proposal(store)
    out = fpr.apply_and_open_pr(item, approved=True, repo_root=tmp_path,
                                runner=runner, gh=gh, apply_fn=apply_fn, store_path=store)
    assert out["pr_url"].endswith("/pull/9") and out["pr_number"] == 9
    # git: checkout -B, add, commit, push.
    cmds = [c[1] for c in calls if len(c) > 1]
    assert "checkout" in cmds and "add" in cmds and "commit" in cmds and "push" in cmds
    assert applied  # el cambio se aplicó
    saved = fp.get_proposal(item["id"], path=store)
    assert saved["status"] == "pr_open" and saved["pr_number"] == 9


def test_apply_blocked_when_flag_off(store, tmp_path, monkeypatch):
    monkeypatch.setattr("config.FACTORY_MODIFIER_ENABLED", False, raising=False)
    item = _proposal(store)
    with pytest.raises(PermissionError):
        fpr.apply_and_open_pr(item, approved=True, repo_root=tmp_path,
                              runner=lambda *a, **k: "", gh=lambda *a, **k: {},
                              apply_fn=lambda *a, **k: {}, store_path=store)


def test_apply_blocked_when_not_approved(store, tmp_path):
    item = _proposal(store)
    with pytest.raises(PermissionError):
        fpr.apply_and_open_pr(item, approved=False, repo_root=tmp_path,
                              runner=lambda *a, **k: "", gh=lambda *a, **k: {},
                              apply_fn=lambda *a, **k: {}, store_path=store)


def test_merge_pr_happy_path(store):
    item = _proposal(store)
    fp.set_status(item["id"], "pr_open", pr_number=42, path=store)
    item = fp.get_proposal(item["id"], path=store)
    def gh(method, path, payload=None):
        assert method == "PUT" and path.endswith("/42/merge")
        return {"merged": True}
    out = fpr.merge_pr(item, approved=True, gh=gh, store_path=store)
    assert out["merged"] is True
    assert fp.get_proposal(item["id"], path=store)["status"] == "merged"


def test_merge_requires_pr_number(store):
    item = _proposal(store)  # sin pr_number
    with pytest.raises(ValueError):
        fpr.merge_pr(item, approved=True, gh=lambda *a, **k: {"merged": True}, store_path=store)


def test_merge_raises_when_github_refuses(store):
    item = _proposal(store)
    fp.set_status(item["id"], "pr_open", pr_number=7, path=store)
    item = fp.get_proposal(item["id"], path=store)
    def gh(method, path, payload=None): return {"merged": False, "message": "blocked"}
    with pytest.raises(RuntimeError):
        fpr.merge_pr(item, approved=True, gh=gh, store_path=store)
