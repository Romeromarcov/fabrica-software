"""Test de UI — PLAN.md 1.5: el panel del feature muestra los archivos escritos al repo.

Verifica de extremo a extremo (ruta /feature/{id}) que `files_written` de
`metadata.json` se renderiza en la página de detalle del feature.
"""
import json

import pytest
from starlette.testclient import TestClient

import ui.server as srv


@pytest.fixture
def client(tmp_path, monkeypatch):
    # Aísla el directorio de runs para no tocar datos reales.
    monkeypatch.setattr(srv, "RUNS_DIR", tmp_path)
    monkeypatch.setattr(srv, "_RUNS_DIR_RESOLVED", tmp_path.resolve())
    return TestClient(srv.app), tmp_path


def test_feature_detail_lists_files_written(client):
    tc, runs = client
    feature_id = "20260618_120000_demo"
    run_dir = runs / feature_id
    run_dir.mkdir(parents=True)
    (run_dir / "metadata.json").write_text(json.dumps({
        "feature_name": "Demo feature",
        "status": "completado",
        "files_written": ["apps/core/models.py", "apps/core/views.py"],
    }), encoding="utf-8")

    resp = tc.get(f"/feature/{feature_id}")
    assert resp.status_code == 200
    body = resp.text
    assert "Archivos escritos al repo" in body
    assert "apps/core/models.py" in body
    assert "apps/core/views.py" in body


def test_feature_detail_no_files_section_when_absent(client):
    tc, runs = client
    feature_id = "20260618_130000_nofiles"
    run_dir = runs / feature_id
    run_dir.mkdir(parents=True)
    (run_dir / "metadata.json").write_text(json.dumps({
        "feature_name": "Sin archivos",
        "status": "completado",
    }), encoding="utf-8")

    resp = tc.get(f"/feature/{feature_id}")
    assert resp.status_code == 200
    assert "Archivos escritos al repo" not in resp.text
