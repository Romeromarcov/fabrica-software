"""
Tests de las rutas web del PR3 (auditoría de la fábrica + aprobación de propuestas) y de la
cadencia por features. El store de propuestas se redirige a tmp; nada toca git ni red.
"""
import pytest
from starlette.testclient import TestClient

import ui.server as srv
from tools import factory_proposals as fp
from tools import factory_audit as fa


@pytest.fixture
def tc():
    return TestClient(srv.app)


@pytest.fixture(autouse=True)
def _store(tmp_path, monkeypatch):
    # Redirige el store de propuestas a un archivo temporal (default _store_path).
    store = tmp_path / "props.json"
    monkeypatch.setattr(fp, "_store_path", lambda path=None: path if path else store)
    return store


def test_meta_page_shows_factory_audit_card(tc):
    body = tc.get("/meta").text
    assert "Auditoría de la fábrica" in body
    assert "Auditar ahora" in body


def test_proposals_route_lists(tc, _store):
    fp.add_proposal({"kind": "prompt", "mode": "append"}, risk="low")
    res = tc.get("/api/meta/factory-audit/proposals")
    body = res.json()
    assert body["ok"] is True and len(body["proposals"]) == 1


def test_dismiss_route(tc, _store):
    item = fp.add_proposal({"kind": "prompt"}, risk="low")
    res = tc.post(f"/api/meta/factory-audit/proposals/{item['id']}/dismiss")
    assert res.json()["ok"] is True
    assert fp.get_proposal(item["id"])["status"] == "dismissed"


def test_dismiss_unknown_is_404(tc):
    assert tc.post("/api/meta/factory-audit/proposals/zzz/dismiss").status_code == 404


def test_apply_unknown_is_404(tc):
    assert tc.post("/api/meta/factory-audit/proposals/zzz/apply").status_code == 404


def test_run_route_invokes_engine(tc, monkeypatch):
    called = {}
    def _fake_run(**kwargs):
        called.update(kwargs)
        return {"generated": 2, "auto_applied": 1, "pending": 1, "errors": []}
    monkeypatch.setattr("tools.factory_audit.run_factory_audit", _fake_run)
    res = tc.post("/api/meta/factory-audit/run")
    body = res.json()
    assert body["ok"] is True and body["summary"]["generated"] == 2


# ── Cadencia por features ────────────────────────────────────────────────────

def test_on_feature_started_triggers_every_n(tmp_path):
    counter = tmp_path / "c.json"
    runs = []
    def _runner(**k): runs.append(k)
    # No dispara en features 1 y 2…
    for _ in range(2):
        fired = fa.on_feature_started(enabled=True, mode="features", every_n=3,
                                      runner=_runner, counter_path=counter)
        assert fired is False
    # …y sí en la tercera, reiniciando el contador.
    fired = fa.on_feature_started(enabled=True, mode="features", every_n=3,
                                  runner=_runner, counter_path=counter)
    assert fired is True and len(runs) == 1


def test_on_feature_started_ignores_time_mode(tmp_path):
    counter = tmp_path / "c.json"
    fired = fa.on_feature_started(enabled=True, mode="time", every_n=1,
                                  runner=lambda **k: None, counter_path=counter)
    assert fired is False
