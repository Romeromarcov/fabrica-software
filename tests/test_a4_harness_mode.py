"""
Test F2 paso 2 — A4 en modo harness usa el loop ReAct; con el flag off, call_agent directo.
"""
from state import CostEntry


def _cost():
    return CostEntry(agent="a4", model="m", input_tokens=1, output_tokens=1, cost_usd=0.0)


def _a4_state():
    return {
        "repo_path": "/repo/demo", "project_id": "", "feature_id": "F1",
        "feature_name": "crud", "master_plan": "plan", "db_schema": "schema",
        "qa_report": None, "qa_iterations": 0,
    }


def _patch_a4_context(monkeypatch):
    import nodes.a4_backend as a4
    monkeypatch.setattr(a4, "lessons_for_context", lambda *a, **k: "")
    monkeypatch.setattr(a4, "build_fewshots", lambda *a, **k: "")
    monkeypatch.setattr("tools.file_tools.save_agent_output", lambda *a, **k: None)
    monkeypatch.setattr("tools.architecture_record.adr_context_block", lambda *a, **k: "")
    monkeypatch.setattr("tools.project_memory.get_memory_context", lambda *a, **k: "")
    monkeypatch.setattr("tools.stack_reader.read_stack", lambda *a, **k: {})
    monkeypatch.setattr("tools.stack_reader.get_backend_instructions", lambda *a, **k: "")
    monkeypatch.setattr("tools.context_retriever.get_relevant_context", lambda *a, **k: "")
    monkeypatch.setattr("tools.learning_memory.recurring_error_patterns", lambda *a, **k: [])
    monkeypatch.setattr("tools.learning_memory.hard_instruction_block", lambda *a, **k: "")


def test_a4_uses_react_loop_when_harness_enabled(monkeypatch):
    import nodes.a4_backend as a4
    _patch_a4_context(monkeypatch)
    monkeypatch.setattr("config.HARNESS_MODE_ENABLED", True, raising=False)
    monkeypatch.setattr("config.STRUCTURED_ARTIFACTS_ENABLED", False, raising=False)

    called = {"react": 0, "direct": 0}

    def fake_react(**k):
        called["react"] += 1
        return ("backend via harness", [_cost(), _cost()])

    monkeypatch.setattr("nodes.base.call_agent_react", fake_react)
    monkeypatch.setattr(a4, "call_agent", lambda **k: (called.__setitem__("direct", called["direct"] + 1), ("x", _cost()))[1])

    out = a4.a4_backend(_a4_state())
    assert out["backend_code"] == "backend via harness"
    assert called["react"] == 1 and called["direct"] == 0
    assert len(out["cost_entries"]) == 2


def test_a4_uses_direct_call_when_harness_disabled(monkeypatch):
    import nodes.a4_backend as a4
    _patch_a4_context(monkeypatch)
    monkeypatch.setattr("config.HARNESS_MODE_ENABLED", False, raising=False)
    monkeypatch.setattr("config.STRUCTURED_ARTIFACTS_ENABLED", False, raising=False)
    monkeypatch.setattr(a4, "call_agent", lambda **k: ("backend directo", _cost()))

    out = a4.a4_backend(_a4_state())
    assert out["backend_code"] == "backend directo"
    assert len(out["cost_entries"]) == 1
