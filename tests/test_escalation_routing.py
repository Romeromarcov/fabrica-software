"""
Tests F6 — la decisión del Founder en qa_escalation se HONRA en el grafo.

Antes, `qa_escalation` siempre iba a `pipeline_detenido` (la decisión ACEPTAR/REDISEÑAR/CANCELAR
era decorativa). Ahora el router enruta según la decisión y el nodo la expone en el state.
"""
from graph import _route_after_escalation
from nodes.human_nodes import qa_escalation
from unittest.mock import patch


def test_router_aceptar_continues():
    assert _route_after_escalation({"escalation_decision": "ACEPTAR"}) == "aceptar"


def test_router_redisenar_rebuilds():
    assert _route_after_escalation({"escalation_decision": "REDISEÑAR"}) == "redisenar"
    assert _route_after_escalation({"escalation_decision": "REDISENAR"}) == "redisenar"


def test_router_cancelar_stops():
    assert _route_after_escalation({"escalation_decision": "CANCELAR"}) == "cancelar"


def test_router_unknown_or_empty_stops():
    assert _route_after_escalation({}) == "cancelar"
    assert _route_after_escalation({"escalation_decision": "loquesea"}) == "cancelar"


# ── el nodo expone la decisión en el state ───────────────────────────────────

def _run_node_with_input(resp):
    state = {"mode": "lite", "feature_id": "F1", "feature_name": "x", "secops_iterations": 0,
             "qa_report": "", "qa_iterations": 2, "project_id": ""}
    with patch("nodes.human_nodes.interrupt", return_value=resp), \
         patch("nodes.human_nodes.save_run_metadata"), \
         patch("tools.telegram.notify_escalation"):
        return qa_escalation(state)


def test_node_exposes_aceptar_without_error():
    out = _run_node_with_input("ACEPTAR")
    assert out["escalation_decision"] == "ACEPTAR"
    assert "errors" not in out   # ACEPTAR no debe inyectar un error que contamine el state


def test_node_redisenar_resets_qa_iterations():
    out = _run_node_with_input("REDISEÑAR")
    assert out["escalation_decision"] == "REDISEÑAR"
    assert out["qa_iterations"] == 0


def test_node_cancelar_sets_error():
    out = _run_node_with_input("CANCELAR")
    assert out["escalation_decision"] == "CANCELAR"
    assert out.get("errors")
