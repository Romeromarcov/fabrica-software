"""Tests de la página /marketing y su ruta de lanzamiento (web)."""
import pytest
from starlette.testclient import TestClient

import ui.server as srv
import nodes.marketing as m


@pytest.fixture
def tc():
    return TestClient(srv.app)


def test_marketing_page_renders_and_lists_pipelines(tc):
    resp = tc.get("/marketing")
    assert resp.status_code == 200
    body = resp.text
    assert "Nueva pieza" in body
    assert "Pipelines disponibles" in body
    # software y marketing aparecen con runtime dedicado
    assert "marketing" in body
    assert "dedicado" in body


def test_launch_requires_pieza_and_brief(tc):
    assert tc.post("/api/marketing/launch", json={"pieza": "", "brief": ""}).status_code == 400
    assert tc.post("/api/marketing/launch", json={"pieza": "x", "brief": ""}).status_code == 400


def test_launch_runs_pipeline(tc, monkeypatch):
    def _approve(**k):
        return ("ok\nRISK_LEVEL: LOW\nCONFIDENCE_SCORE: 90\nBRAND_PASSED: true\n"
                "COMPLIANCE_CLEAR: true\nADVERSARIAL_CLEAR: true", None)
    monkeypatch.setattr(m, "call_agent", _approve)
    monkeypatch.setattr("config.MARKETING_PUBLISH_ENABLED", False, raising=False)
    res = tc.post("/api/marketing/launch", json={"pieza": "p1", "brief": "lanzamiento"})
    assert res.status_code == 200
    body = res.json()
    assert body["ok"] is True
    r = body["result"]
    assert r["brand_passed"] is True
    assert r["preview_passed"] is True
    assert r["publish_ref"].startswith("dryrun:")
