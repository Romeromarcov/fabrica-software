"""Tests del Factory Modifier (PLAN_PLATAFORMA_V2 Fase 7 — auto-modificación).

La parte LLM se mockea (callable inyectable); prompts y registry se redirigen a tmp_path.
El foco es la CONTENCIÓN: doble gate, deny-list dura y ruteo por PR (nunca main).
"""
import json
from pathlib import Path

import pytest

import tools.factory_modifier as fm


# ── normalización ────────────────────────────────────────────────────────────

def test_normalize_fills_defaults():
    c = fm.normalize_factory_change({"kind": "prompt", "target": "agents/a/p.md", "content": "x"})
    assert c["mode"] == "replace"
    assert c["rationale"] == ""
    assert c["agent_id"] is None


def test_normalize_ignores_unknown_keys():
    c = fm.normalize_factory_change({"kind": "prompt", "hacky": "rm -rf"})
    assert "hacky" not in c


# ── validación: caminos válidos ───────────────────────────────────────────────

def test_validate_ok_prompt():
    c = fm.normalize_factory_change(
        {"kind": "prompt", "target": "agents/agent_04_backend/system_prompt.md",
         "content": "Usa type hints.", "mode": "append"})
    assert fm.validate_factory_change(c) == []


def test_validate_ok_registry_field():
    c = fm.normalize_factory_change(
        {"kind": "registry_field", "agent_id": "A4", "field": "model_fallbacks",
         "value": ["gemini-2.5-flash-lite"]})
    assert fm.validate_factory_change(c) == []


# ── validación: deny-list dura ─────────────────────────────────────────────────

def test_validate_bad_kind():
    assert any("kind" in e for e in fm.validate_factory_change({"kind": "delete_repo"}))


@pytest.mark.parametrize("target", [
    ".github/workflows/ci.yml",
    "config.py",
    "graph.py",
    "tools/factory_modifier.py",
    "tools/auth.py",
    "scripts/clone_targets.py",
    "ui/server.py",
    "/etc/passwd",
    "agents/../config.py",
])
def test_validate_blocks_protected_prompt_paths(target):
    c = fm.normalize_factory_change({"kind": "prompt", "target": target, "content": "x"})
    errs = fm.validate_factory_change(c)
    assert errs, f"esperaba bloqueo para {target}"


def test_validate_prompt_must_be_under_agents_and_md():
    c = fm.normalize_factory_change({"kind": "prompt", "target": "docs/readme.txt", "content": "x"})
    errs = fm.validate_factory_change(c)
    assert any("agents/" in e for e in errs)
    assert any(".md" in e for e in errs)


def test_validate_prompt_empty_content():
    c = fm.normalize_factory_change({"kind": "prompt", "target": "agents/x/p.md", "content": "   "})
    assert any("content" in e for e in fm.validate_factory_change(c))


def test_validate_blocks_immutable_registry_field():
    for field in ("id", "pipeline", "node_name", "agent_key", "uses_llm"):
        c = fm.normalize_factory_change(
            {"kind": "registry_field", "agent_id": "A4", "field": field, "value": "x"})
        assert any("inmutable" in e for e in fm.validate_factory_change(c)), field


def test_validate_blocks_unknown_registry_field():
    c = fm.normalize_factory_change(
        {"kind": "registry_field", "agent_id": "A4", "field": "secret_backdoor", "value": "x"})
    assert any("no es modificable" in e for e in fm.validate_factory_change(c))


def test_validate_blocks_security_reviewer_agents():
    for agent in ("A8", "A8_5", "A85"):
        c = fm.normalize_factory_change(
            {"kind": "registry_field", "agent_id": agent, "field": "role", "value": "weak"})
        assert any("revisor de seguridad" in e for e in fm.validate_factory_change(c)), agent


def test_is_protected_target():
    assert fm.is_protected_target({"kind": "prompt", "target": ".github/x.md"}) is True
    assert fm.is_protected_target({"kind": "registry_field", "agent_id": "A8"}) is True
    assert fm.is_protected_target({"kind": "registry_field", "agent_id": "A4"}) is False
    assert fm.is_protected_target({"kind": "unknown"}) is True   # fail-safe


# ── build (LLM inyectado) ──────────────────────────────────────────────────────

def test_build_with_dict_llm():
    fake = {"kind": "prompt", "target": "agents/a/p.md", "content": "y", "mode": "replace"}
    c = fm.build_factory_change("endurece el prompt", llm=lambda _r: fake)
    assert c["kind"] == "prompt" and c["content"] == "y"


def test_build_invalid_json_raises():
    with pytest.raises(ValueError, match="JSON válido"):
        fm.build_factory_change("x", llm=lambda _r: "no json")


def test_build_non_dict_raises():
    with pytest.raises(ValueError, match="dict"):
        fm.build_factory_change("x", llm=lambda _r: ["lista"])


# ── plan ────────────────────────────────────────────────────────────────────

def test_plan_marks_blocked():
    c = fm.normalize_factory_change({"kind": "prompt", "target": "config.py", "content": "x"})
    assert "BLOQUEADO" in fm.plan_factory_change(c, branch="feature/x")


def test_plan_marks_valid():
    c = fm.normalize_factory_change(
        {"kind": "prompt", "target": "agents/x/p.md", "content": "ok", "mode": "replace"})
    assert "VÁLIDO" in fm.plan_factory_change(c, branch="feature/x")


# ── apply: doble gate + ruteo por PR ───────────────────────────────────────────

def _enable(monkeypatch):
    monkeypatch.setattr("config.FACTORY_MODIFIER_ENABLED", True, raising=False)


def _prompt_change():
    return fm.normalize_factory_change(
        {"kind": "prompt", "target": "agents/agent_04_backend/system_prompt.md",
         "content": "Nuevo prompt.", "mode": "replace"})


def test_apply_blocked_when_flag_off(tmp_path, monkeypatch):
    monkeypatch.setattr("config.FACTORY_MODIFIER_ENABLED", False, raising=False)
    with pytest.raises(PermissionError, match="FACTORY_MODIFIER_ENABLED"):
        fm.apply_factory_change(_prompt_change(), approved=True, branch="feature/x", repo_root=tmp_path)


def test_apply_requires_approval(tmp_path, monkeypatch):
    _enable(monkeypatch)
    with pytest.raises(PermissionError, match="aprobación"):
        fm.apply_factory_change(_prompt_change(), approved=False, branch="feature/x", repo_root=tmp_path)


@pytest.mark.parametrize("branch", ["main", "master", ""])
def test_apply_never_on_protected_branch(tmp_path, monkeypatch, branch):
    _enable(monkeypatch)
    with pytest.raises(PermissionError, match="rama de trabajo|main"):
        fm.apply_factory_change(_prompt_change(), approved=True, branch=branch, repo_root=tmp_path)


def test_apply_rejects_protected_target(tmp_path, monkeypatch):
    _enable(monkeypatch)
    c = fm.normalize_factory_change({"kind": "prompt", "target": "config.py", "content": "x"})
    with pytest.raises(ValueError, match="inválido"):
        fm.apply_factory_change(c, approved=True, branch="feature/x", repo_root=tmp_path)


def test_apply_prompt_replace_writes_file(tmp_path, monkeypatch):
    _enable(monkeypatch)
    rec = fm.apply_factory_change(_prompt_change(), approved=True, branch="feature/x", repo_root=tmp_path)
    assert rec["applied"] is True
    written = (tmp_path / "agents/agent_04_backend/system_prompt.md").read_text()
    assert written == "Nuevo prompt."


def test_apply_prompt_append_preserves_previous(tmp_path, monkeypatch):
    _enable(monkeypatch)
    target = tmp_path / "agents/agent_04_backend/system_prompt.md"
    target.parent.mkdir(parents=True)
    target.write_text("Base.")
    c = fm.normalize_factory_change(
        {"kind": "prompt", "target": "agents/agent_04_backend/system_prompt.md",
         "content": "Adición.", "mode": "append"})
    fm.apply_factory_change(c, approved=True, branch="feature/x", repo_root=tmp_path)
    assert target.read_text() == "Base.\nAdición."


def test_apply_registry_field(tmp_path, monkeypatch):
    _enable(monkeypatch)
    reg = {"version": 1, "agents": [
        {"id": "A4", "role": "Backend", "pipeline": "software", "uses_llm": True,
         "model": None, "model_fallbacks": []},
    ]}
    p = tmp_path / "registry.json"
    p.write_text(json.dumps(reg), encoding="utf-8")
    c = fm.normalize_factory_change(
        {"kind": "registry_field", "agent_id": "A4", "field": "model_fallbacks",
         "value": ["gemini-2.5-flash-lite"]})
    rec = fm.apply_factory_change(c, approved=True, branch="feature/x", registry_path=p)
    assert rec["old_value"] == []
    on_disk = json.loads(Path(p).read_text())
    a4 = next(a for a in on_disk["agents"] if a["id"] == "A4")
    assert a4["model_fallbacks"] == ["gemini-2.5-flash-lite"]


def test_apply_registry_unknown_agent(tmp_path, monkeypatch):
    _enable(monkeypatch)
    p = tmp_path / "registry.json"
    p.write_text(json.dumps({"version": 1, "agents": []}), encoding="utf-8")
    c = fm.normalize_factory_change(
        {"kind": "registry_field", "agent_id": "ZZZ", "field": "role", "value": "x"})
    with pytest.raises(ValueError, match="no existe"):
        fm.apply_factory_change(c, approved=True, branch="feature/x", registry_path=p)
