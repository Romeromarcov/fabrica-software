"""Tests del paralelismo intra-feature A4+A5 (PLAN_PLATAFORMA_V2 R3).

NOTA: este archivo cubre R3 (PARALLEL_AGENTS_ENABLED). El paralelismo a NIVEL feature
(PARALLEL_FEATURES_ENABLED / worktrees) vive en test_parallel_safety.py / test_worktree_wiring.py
y queda intocado.
"""
import graph
import nodes.a45_parallel as par
from state import CostEntry


def _ce(agent):
    return CostEntry(agent=agent, model="m", input_tokens=1, output_tokens=1, cost_usd=0.01)


def test_a45_parallel_merges_both(monkeypatch):
    calls = []

    def fake_a4(state):
        calls.append("a4")
        return {"backend_code": "BACKEND", "current_agent": "a4_backend",
                "cost_entries": [_ce("A4")], "errors": []}

    def fake_a5(state):
        calls.append("a5")
        return {"frontend_code": "FRONTEND", "current_agent": "a5_frontend",
                "cost_entries": [_ce("A5")], "errors": []}

    monkeypatch.setattr("nodes.a4_backend.a4_backend", fake_a4)
    monkeypatch.setattr("nodes.a5_frontend.a5_frontend", fake_a5)

    out = par.a45_parallel({"feature_id": "f", "mode": "completo"})
    assert out["backend_code"] == "BACKEND"
    assert out["frontend_code"] == "FRONTEND"
    assert out["current_agent"] == "a45_parallel"
    # cost_entries de ambos, concatenadas una vez
    assert len(out["cost_entries"]) == 2
    assert {"a4", "a5"} == set(calls)


def test_a45_parallel_concatenates_errors(monkeypatch):
    monkeypatch.setattr("nodes.a4_backend.a4_backend",
                        lambda s: {"backend_code": "B", "cost_entries": [], "errors": ["e1"]})
    monkeypatch.setattr("nodes.a5_frontend.a5_frontend",
                        lambda s: {"frontend_code": "F", "cost_entries": [], "errors": ["e2"]})
    out = par.a45_parallel({"feature_id": "f"})
    assert out["errors"] == ["e1", "e2"]


# ── Routing: _use_parallel_agents + edges (flag on/off) ──────────────────────

def test_use_parallel_disabled_by_default(monkeypatch):
    monkeypatch.setattr("config.PARALLEL_AGENTS_ENABLED", False, raising=False)
    state = {"mode": "completo", "skip_backend": False, "skip_frontend": False}
    assert graph._use_parallel_agents(state) is False


def test_use_parallel_enabled_both_active(monkeypatch):
    monkeypatch.setattr("config.PARALLEL_AGENTS_ENABLED", True, raising=False)
    state = {"mode": "completo", "skip_backend": False, "skip_frontend": False}
    assert graph._use_parallel_agents(state) is True


def test_use_parallel_off_when_skip(monkeypatch):
    monkeypatch.setattr("config.PARALLEL_AGENTS_ENABLED", True, raising=False)
    assert graph._use_parallel_agents(
        {"mode": "completo", "skip_backend": True, "skip_frontend": False}) is False
    assert graph._use_parallel_agents(
        {"mode": "completo", "skip_backend": False, "skip_frontend": True}) is False


def test_use_parallel_off_in_lightning(monkeypatch):
    monkeypatch.setattr("config.PARALLEL_AGENTS_ENABLED", True, raising=False)
    assert graph._use_parallel_agents(
        {"mode": "lightning", "skip_backend": False, "skip_frontend": False}) is False


def test_route_after_db_parallel(monkeypatch):
    monkeypatch.setattr("config.PARALLEL_AGENTS_ENABLED", True, raising=False)
    state = {"mode": "completo", "needs_mcp": False, "skip_backend": False, "skip_frontend": False}
    assert graph._route_after_db(state) == "a45_parallel"


def test_route_after_db_sequential_when_off(monkeypatch):
    monkeypatch.setattr("config.PARALLEL_AGENTS_ENABLED", False, raising=False)
    state = {"mode": "completo", "needs_mcp": False, "skip_backend": False, "skip_frontend": False}
    assert graph._route_after_db(state) == "a4_backend"


def test_route_after_mcp_parallel(monkeypatch):
    monkeypatch.setattr("config.PARALLEL_AGENTS_ENABLED", True, raising=False)
    state = {"mode": "completo", "skip_backend": False, "skip_frontend": False}
    assert graph._route_after_mcp(state) == "a45_parallel"


def test_route_after_approval_lite_parallel(monkeypatch):
    monkeypatch.setattr("config.PARALLEL_AGENTS_ENABLED", True, raising=False)
    state = {"founder_approval": True, "mode": "lite",
             "skip_backend": False, "skip_frontend": False}
    assert graph._route_after_approval(state) == "parallel_agents"


def test_graph_has_parallel_node_and_compiles():
    g = graph.build_graph()
    assert "a45_parallel" in g.nodes
    assert g.compile() is not None
