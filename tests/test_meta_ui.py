"""Tests de la página /meta y sus rutas API (meta-agentes en la UI).

No tocan el LLM: prueban el render de la página, la validación de entrada (request
requerido) y los gates de registro (flag off → bloqueado). La parte LLM (build-*) se
ejercita con request vacío para no salir a la red.
"""
import pytest
from starlette.testclient import TestClient

import ui.server as srv


@pytest.fixture
def tc():
    return TestClient(srv.app)


def test_meta_page_renders(tc):
    resp = tc.get("/meta")
    assert resp.status_code == 200
    body = resp.text
    assert "Meta-agentes" in body
    assert "Crear agente" in body
    # La creación de pipelines se consolidó en el constructor conversacional (no card aparte).
    assert "Constructor conversacional" in body
    assert "Crear pipeline" not in body
    # Lanzar/listar pipelines se movió aquí desde /marketing.
    assert "Lanzar pipeline" in body
    assert "Factory Modifier" in body


def test_build_agent_requires_request(tc):
    assert tc.post("/api/meta/build-agent", json={"request": ""}).status_code == 400


def test_build_agent_sets_pipeline_and_returns_warnings(tc, monkeypatch):
    import tools.agent_builder as ab
    import tools.dedup_check as dc
    # Mock del LLM: definición mínima sin pipeline explícito.
    monkeypatch.setattr(ab, "build_agent_definition",
                        lambda req: ab.normalize_agent_definition(
                            {"id": "SEO1", "role": "Optimizador SEO", "uses_llm": True}))
    # Hay ya un agente parecido en la fábrica.
    monkeypatch.setattr(dc, "find_similar_agents",
                        lambda role, **k: [{"id": "OLD", "role": "Optimizador SEO",
                                            "pipeline": "marketing", "score": 0.9}])
    res = tc.post("/api/meta/build-agent", json={"request": "agente seo", "pipeline": "marketing"})
    body = res.json()
    assert body["ok"] is True
    assert body["definition"]["pipeline"] == "marketing"   # el destino elegido se aplica
    assert body["warnings"] and body["warnings"][0]["id"] == "OLD"


def test_build_pipeline_requires_request(tc):
    assert tc.post("/api/meta/build-pipeline", json={"request": "  "}).status_code == 400


def test_build_factory_change_requires_request(tc):
    assert tc.post("/api/meta/build-factory-change", json={"request": ""}).status_code == 400


def test_register_agent_blocked_when_flag_off(tc, monkeypatch):
    monkeypatch.setattr("config.AGENT_BUILDER_ENABLED", False, raising=False)
    res = tc.post("/api/meta/register-agent", json={
        "definition": {"id": "ZZ1", "role": "x", "pipeline": "software", "uses_llm": True}})
    body = res.json()
    assert body["ok"] is False
    assert "AGENT_BUILDER_ENABLED" in body["error"]


def test_register_pipeline_blocked_when_flag_off(tc, monkeypatch):
    monkeypatch.setattr("config.PIPELINE_BUILDER_ENABLED", False, raising=False)
    res = tc.post("/api/meta/register-pipeline", json={
        "definition": {"name": "zztest", "entry": "X", "agents": ["X"]}})
    body = res.json()
    assert body["ok"] is False
    assert "PIPELINE_BUILDER_ENABLED" in body["error"]
