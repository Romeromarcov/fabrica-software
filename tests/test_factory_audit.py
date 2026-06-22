"""
Tests del PR3: clasificación de riesgo (factory_modifier.risk_level), store de propuestas
(factory_proposals) y motor de auditoría de la fábrica (factory_audit). LLM/apply inyectables;
nada sale a la red ni toca git.
"""
import pytest

from tools import factory_modifier as fm
from tools import factory_proposals as fp
from tools import factory_audit as fa


# ── risk_level ────────────────────────────────────────────────────────────────

def test_risk_prompt_append_is_low_replace_is_medium():
    assert fm.risk_level({"kind": "prompt", "mode": "append"}) == "low"
    assert fm.risk_level({"kind": "prompt", "mode": "replace"}) == "medium"


def test_risk_registry_model_low_role_medium_judge_high():
    assert fm.risk_level({"kind": "registry_field", "field": "model"}) == "low"
    assert fm.risk_level({"kind": "registry_field", "field": "role"}) == "medium"
    assert fm.risk_level({"kind": "registry_field", "field": "judge"}) == "high"


def test_risk_unknown_kind_is_high():
    assert fm.risk_level({"kind": "otra-cosa"}) == "high"


# ── factory_proposals (store) ─────────────────────────────────────────────────

@pytest.fixture
def store(tmp_path):
    return tmp_path / "props.json"


def test_add_and_list_proposal(store):
    item = fp.add_proposal({"kind": "prompt", "mode": "append"}, rationale="mejora",
                           risk="low", path=store)
    assert item["status"] == "pending" and item["id"]
    listed = fp.list_proposals(path=store)
    assert len(listed) == 1 and listed[0]["id"] == item["id"]


def test_set_status_records_history_and_fields(store):
    item = fp.add_proposal({"kind": "prompt"}, risk="low", path=store)
    fp.set_status(item["id"], "applied", branch="factory/x", path=store)
    got = fp.get_proposal(item["id"], path=store)
    assert got["status"] == "applied" and got["branch"] == "factory/x"
    assert got["history"][-1]["to"] == "applied"


def test_set_status_rejects_invalid_and_missing(store):
    item = fp.add_proposal({"kind": "prompt"}, path=store)
    with pytest.raises(ValueError):
        fp.set_status(item["id"], "no-existe", path=store)
    with pytest.raises(KeyError):
        fp.set_status("zzz", "merged", path=store)


def test_list_filters_by_status(store):
    a = fp.add_proposal({"kind": "prompt"}, risk="low", path=store)
    fp.add_proposal({"kind": "prompt"}, risk="high", path=store)
    fp.set_status(a["id"], "dismissed", path=store)
    assert len(fp.list_proposals("pending", path=store)) == 1
    assert len(fp.list_proposals("dismissed", path=store)) == 1


# ── cadencia ──────────────────────────────────────────────────────────────────

def test_feature_cadence_due():
    assert fa.feature_cadence_due(10, 10) is True
    assert fa.feature_cadence_due(10, 9) is False
    assert fa.feature_cadence_due(0, 100) is False   # desactivado


# ── run_factory_audit ─────────────────────────────────────────────────────────

_LLM_OUT = """Aquí tienes:
[
  {"kind":"prompt","target":"agents/agent_04_backend/system_prompt.md","mode":"append",
   "content":"Usa type hints siempre.","rationale":"calidad"},
  {"kind":"registry_field","agent_id":"A4","field":"role","value":"Backend Senior","rationale":"claridad"}
]"""


def test_run_audit_generates_and_auto_applies_low_risk(tmp_path, monkeypatch):
    store = tmp_path / "props.json"
    applied = []
    def _fake_apply(change, *, branch, repo_root, approved):
        applied.append((change["kind"], branch, approved))
        return {"applied": True}

    summary = fa.run_factory_audit(
        llm=lambda snap: _LLM_OUT, repo_root=tmp_path, auto_apply_low=True,
        store_path=store, apply_fn=_fake_apply,
    )
    assert summary["generated"] == 2
    # El prompt-append (low) se auto-aplica; el role-change (medium) queda pending.
    assert summary["auto_applied"] == 1
    assert summary["pending"] == 1
    assert applied and applied[0][0] == "prompt"
    # La propuesta low quedó en 'applied' con rama; la medium en 'pending'.
    statuses = {p["risk"]: p["status"] for p in fp.list_proposals(path=store)}
    assert statuses["low"] == "applied"
    assert statuses["medium"] == "pending"


def test_run_audit_no_autoapply_keeps_all_pending(tmp_path):
    store = tmp_path / "props.json"
    summary = fa.run_factory_audit(
        llm=lambda snap: _LLM_OUT, repo_root=tmp_path, auto_apply_low=False,
        store_path=store, apply_fn=lambda *a, **k: {"applied": True},
    )
    assert summary["auto_applied"] == 0
    assert summary["pending"] == 2


def test_run_audit_invalid_json_generates_nothing(tmp_path):
    store = tmp_path / "props.json"
    summary = fa.run_factory_audit(
        llm=lambda snap: "no hay json aquí", repo_root=tmp_path, store_path=store,
        apply_fn=lambda *a, **k: {},
    )
    assert summary["generated"] == 0 and summary["pending"] == 0
