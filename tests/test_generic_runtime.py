"""Tests del runtime genérico (graph_generic.py) y su ruta /api/pipeline/launch.

Ejecuta pipelines reales del repo (software, marketing) con el resolver genérico y el LLM
mockeado, verificando que produce una salida por agente acumulada en orden.
"""
import pytest
from starlette.testclient import TestClient

import graph_generic as gg
import ui.server as srv


def test_build_and_compile_generic_graph():
    assert gg.build_generic_graph("marketing") is not None
    assert gg.compile_generic_graph("marketing") is not None


def test_run_generic_collects_outputs_per_agent(monkeypatch):
    calls = {"n": 0}

    def _fake(**k):
        calls["n"] += 1
        return (f"salida-{calls['n']}", None)

    monkeypatch.setattr(gg, "call_agent", _fake)
    final = gg.run_generic_pipeline("marketing", "haz una pieza")
    outs = final["outputs"]
    # marketing tiene 10 agentes (M0..M8 + M6_5) → una salida por agente, en orden.
    assert len(outs) == 10
    assert outs[0]["agent"] == "M0"
    assert all(o["output"].startswith("salida-") for o in outs)


def test_run_generic_records_agent_error(monkeypatch):
    def _boom(**k):
        raise RuntimeError("fallo del proveedor")
    monkeypatch.setattr(gg, "call_agent", _boom)
    final = gg.run_generic_pipeline("marketing", "x")
    assert final["errors"]
    assert "[error:" in final["outputs"][0]["output"]


# ── Ruta web ───────────────────────────────────────────────────────────────────

@pytest.fixture
def tc():
    return TestClient(srv.app)


def test_pipeline_launch_requires_pipeline_and_brief(tc):
    assert tc.post("/api/pipeline/launch", json={"pipeline": "", "brief": ""}).status_code == 400
    assert tc.post("/api/pipeline/launch", json={"pipeline": "marketing", "brief": ""}).status_code == 400


def test_pipeline_launch_runs(tc, monkeypatch):
    monkeypatch.setattr(gg, "call_agent", lambda **k: ("ok", None))
    res = tc.post("/api/pipeline/launch", json={"pipeline": "marketing", "brief": "demo"})
    assert res.status_code == 200
    body = res.json()
    assert body["ok"] is True
    assert len(body["outputs"]) == 10


def test_marketing_page_shows_generic_launcher(tc):
    body = tc.get("/marketing").text
    # El card del lanzador genérico siempre está; los pipelines actuales son dedicados.
    assert "runtime genérico" in body
    assert "dedicado" in body
    assert 'id="gPipeline"' in body
