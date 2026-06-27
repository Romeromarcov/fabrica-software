"""
Tests F1 — Intercambio de objetos validados A1→A2→A4 (aceptación del plan).

Con STRUCTURED_ARTIFACTS_ENABLED=true, A1 emite un MasterPlan validado en el state,
A2 lo consume y emite un DBSchema validado, y A4 recibe ambos. Con el flag off, el
comportamiento es idéntico al de hoy (sin campos `*_artifact`).
"""
from state import CostEntry


def _cost():
    return CostEntry(agent="x", model="m", input_tokens=0, output_tokens=0, cost_usd=0.0)


def _patch_common(monkeypatch):
    monkeypatch.setattr("tools.file_tools.save_master_plan", lambda *a, **k: "/tmp/mp.md")
    monkeypatch.setattr("tools.file_tools.save_run_metadata", lambda *a, **k: None)
    monkeypatch.setattr("tools.file_tools.save_agent_output", lambda *a, **k: None)


def _a1_state():
    return {
        "repo_name": "demo", "repo_path": "", "mode": "lite", "feature_id": "F1",
        "feature_name": "crud", "project_id": "",
    }


def test_a1_emits_validated_master_plan_when_enabled(monkeypatch):
    import nodes.a1_planificador as a1
    _patch_common(monkeypatch)
    monkeypatch.setattr("config.STRUCTURED_ARTIFACTS_ENABLED", True, raising=False)
    monkeypatch.setattr(a1, "call_agent",
                        lambda **k: ("MASTER_PLAN\nRISK_LEVEL: LOW\n", _cost()))

    out = a1.a1_planificador(_a1_state())
    art = out.get("master_plan_artifact")
    assert art is not None
    assert art["agent_id"] == "a1_pm"
    assert art["risk_level"] in ("LOW", "MEDIUM", "HIGH")


def test_a1_no_artifact_when_disabled(monkeypatch):
    import nodes.a1_planificador as a1
    _patch_common(monkeypatch)
    monkeypatch.setattr("config.STRUCTURED_ARTIFACTS_ENABLED", False, raising=False)
    monkeypatch.setattr(a1, "call_agent", lambda **k: ("MASTER_PLAN\n", _cost()))

    out = a1.a1_planificador(_a1_state())
    assert "master_plan_artifact" not in out


def test_a2_consumes_a1_and_emits_dbschema(monkeypatch):
    import nodes.a2_db as a2
    _patch_common(monkeypatch)
    monkeypatch.setattr("config.STRUCTURED_ARTIFACTS_ENABLED", True, raising=False)
    # Aislar dependencias de contexto de A2.
    monkeypatch.setattr("tools.architecture_record.adr_context_block", lambda *a, **k: "")
    monkeypatch.setattr("tools.project_memory.get_memory_context", lambda *a, **k: "")
    monkeypatch.setattr("tools.context_retriever.get_relevant_context", lambda *a, **k: "")
    monkeypatch.setattr("tools.session_memory.load_memory", lambda *a, **k: "")
    monkeypatch.setattr(a2, "call_agent",
                        lambda **k: ("modelos y migration de la tabla", _cost()))

    # State que ya trae el artefacto validado de A1 (cadena A1→A2).
    state = {
        "repo_path": "", "project_id": "", "feature_id": "F1",
        "master_plan": "plan",
        "master_plan_artifact": {"agent_id": "a1_pm", "risk_level": "LOW", "tasks": []},
    }
    out = a2.a2_db(state)
    art = out.get("db_schema_artifact")
    assert art is not None
    assert art["agent_id"] == "a2-db"
    assert art["needs_migrations"] is True   # "migration" aparece en el output
