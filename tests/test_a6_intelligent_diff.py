"""Integración del diff inteligente M4 en a6_refactor (PLAN_PLATAFORMA_V2 Fase 1).

Verifica que A6 registra `refactor_change_ratio` en el state y que, con el gate on,
una reescritura masiva dispara la escalación. Se mockea el LLM — sin red.
"""
import pytest

import nodes.a6_refactor as a6


def _base_state(backend="", output_marker="✅ LISTO PARA QA"):
    return {
        "feature_id": "feat-1",
        "feature_name": "demo",
        "project_id": "",
        "project_name": "proj",
        "repo_path": "/tmp/repo",
        "master_plan": "plan",
        "backend_code": backend,
        "frontend_code": "",
        "qa_report": "",
        "qa_iterations": 0,
        "sandbox_passed": True,
        "sandbox_iterations": 0,
        "sandbox_gate_failures": [],
        "sandbox_results": "",
        "db_schema": "",
        "mcp_tools": "",
    }


@pytest.fixture
def _mock_a6(monkeypatch):
    monkeypatch.setattr(a6, "save_agent_output", lambda *a, **k: None)
    monkeypatch.setattr("tools.architecture_record.adr_context_block", lambda *a, **k: "")
    escalations = []
    monkeypatch.setattr(a6, "notify_escalation", lambda **k: escalations.append(k))
    return escalations


def test_records_change_ratio(monkeypatch, _mock_a6):
    monkeypatch.setattr(a6, "call_agent", lambda **k: ("código\n✅ LISTO PARA QA", {"cost_usd": 0}))
    out = a6.a6_refactor(_base_state(backend="código original"))
    assert "refactor_change_ratio" in out
    assert isinstance(out["refactor_change_ratio"], float)


def test_gate_on_escalates_on_massive_rewrite(monkeypatch, _mock_a6):
    # Salida totalmente distinta del input → ratio alto → escala con gate on.
    monkeypatch.setattr("config.INTELLIGENT_DIFF_GATE", True, raising=False)
    monkeypatch.setattr("config.INTELLIGENT_DIFF_THRESHOLD", 0.3, raising=False)
    monkeypatch.setattr(a6, "call_agent",
                        lambda **k: ("ZZZZ totalmente distinto\n✅ LISTO PARA QA", {"cost_usd": 0}))
    a6.a6_refactor(_base_state(backend="aaaa bbbb cccc dddd"))
    assert _mock_a6, "se esperaba una escalación por sobre-refactor"


def test_gate_off_does_not_escalate(monkeypatch, _mock_a6):
    monkeypatch.setattr("config.INTELLIGENT_DIFF_GATE", False, raising=False)
    monkeypatch.setattr(a6, "call_agent",
                        lambda **k: ("ZZZZ distinto\n✅ LISTO PARA QA", {"cost_usd": 0}))
    a6.a6_refactor(_base_state(backend="aaaa bbbb"))
    assert _mock_a6 == []  # sin escalación con gate off
