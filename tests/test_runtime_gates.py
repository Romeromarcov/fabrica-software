"""Tests offline de tools/runtime_gates.py (PLAN_BLINDAJE_TOTAL — Bloque B / D).

Totalmente offline: no se levanta ningún servidor ni se toca subprocess/red de verdad.
  • run_django_migrate: se parchea `_run`.
  • smoke_http / wait_for_http: se parchea `_http_get` (y `_probe` / `_sleep` para wait).
"""
from __future__ import annotations

from pathlib import Path

from tools import runtime_gates as rg


# ── B2.1 — run_django_migrate ─────────────────────────────────────────────────

def _fake_project_with_manage(tmp_path: Path) -> str:
    (tmp_path / "manage.py").write_text("# fixture manage.py\n", encoding="utf-8")
    return str(tmp_path)


def test_migrate_success_path(tmp_path, monkeypatch):
    proj = _fake_project_with_manage(tmp_path)

    calls: list[list[str]] = []

    def fake_run(cmd, cwd, *, env=None, timeout=120):
        calls.append(cmd)
        return 0, "OK"

    monkeypatch.setattr(rg, "_run", fake_run)
    res = rg.run_django_migrate(proj, database_url="postgres://fab:fab@localhost:5432/fabtest")

    assert res["gate"] == "migrate-real"
    assert res["passed"] is True
    # Debe correr makemigrations --check --dry-run ANTES del migrate.
    assert calls[0][:3] == ["python", "manage.py", "makemigrations"]
    assert "--check" in calls[0] and "--dry-run" in calls[0]
    assert calls[1][:3] == ["python", "manage.py", "migrate"]
    assert "--noinput" in calls[1]


def test_migrate_nonzero_rc_fails_with_stderr(tmp_path, monkeypatch):
    proj = _fake_project_with_manage(tmp_path)

    def fake_run(cmd, cwd, *, env=None, timeout=120):
        # makemigrations check pasa; migrate falla con rc!=0.
        if "migrate" in cmd:
            return 1, "django.db.utils.ProgrammingError: relation does not exist"
        return 0, "OK"

    monkeypatch.setattr(rg, "_run", fake_run)
    res = rg.run_django_migrate(proj, database_url="postgres://x")

    assert res["passed"] is False
    assert "ProgrammingError" in res["stderr"]


def test_migrate_drift_check_failure_fails(tmp_path, monkeypatch):
    proj = _fake_project_with_manage(tmp_path)

    def fake_run(cmd, cwd, *, env=None, timeout=120):
        # makemigrations --check detecta drift (rc!=0) → debe fallar antes del migrate.
        return 1, "Your models have changes not yet reflected in a migration"

    monkeypatch.setattr(rg, "_run", fake_run)
    res = rg.run_django_migrate(proj)

    assert res["passed"] is False
    assert "makemigrations" in res["stderr"]


def test_migrate_missing_manage_py_is_fail_not_skip(tmp_path, monkeypatch):
    # Sin manage.py: NUNCA passed=True (F1.1: ausencia de herramienta = FALLO).
    def boom(*a, **k):  # _run no debe ni llamarse
        raise AssertionError("_run no debería ejecutarse si falta manage.py")

    monkeypatch.setattr(rg, "_run", boom)
    res = rg.run_django_migrate(str(tmp_path))

    assert res["passed"] is False
    assert "manage.py" in res["stderr"]


# ── B2.4 — smoke_http ─────────────────────────────────────────────────────────

def test_smoke_all_200_passes(monkeypatch):
    monkeypatch.setattr(rg, "_http_get", lambda url, *, timeout=10: 200)
    res = rg.smoke_http("http://localhost:8000", ["/", "/health/"])

    assert res["gate"] == "smoke-http"
    assert res["passed"] is True
    assert {r["path"] for r in res["results"]} == {"/", "/health/"}
    assert all(r["status"] == 200 for r in res["results"])


def test_smoke_one_500_fails(monkeypatch):
    def fake_get(url, *, timeout=10):
        return 500 if url.endswith("/boom") else 200

    monkeypatch.setattr(rg, "_http_get", fake_get)
    res = rg.smoke_http("http://localhost:8000", ["/", "/boom"])

    assert res["passed"] is False
    assert "500" in res["stderr"]


def test_smoke_connection_error_fails(monkeypatch):
    def fake_get(url, *, timeout=10):
        raise ConnectionError("connection refused")

    monkeypatch.setattr(rg, "_http_get", fake_get)
    res = rg.smoke_http("http://localhost:8000", ["/"])

    assert res["passed"] is False
    assert res["results"][0]["status"] is None
    assert "conexión" in res["stderr"]


def test_smoke_401_still_passes(monkeypatch):
    # 401/403 = "respondió" (auth requerida), no crash → pasa.
    monkeypatch.setattr(rg, "_http_get", lambda url, *, timeout=10: 401)
    res = rg.smoke_http("http://localhost:8000", ["/protected/"])

    assert res["passed"] is True
    assert res["results"][0]["status"] == 401


def test_smoke_unexpected_404_fails(monkeypatch):
    # Un 4xx fuera de expected (ruta rota) también falla el smoke.
    monkeypatch.setattr(rg, "_http_get", lambda url, *, timeout=10: 404)
    res = rg.smoke_http("http://localhost:8000", ["/missing/"])

    assert res["passed"] is False
    assert "404" in res["stderr"]


# ── wait_for_http ──────────────────────────────────────────────────────────────

def test_wait_answers_on_third_attempt(monkeypatch):
    state = {"n": 0}

    def fake_probe(url, *, timeout=2.0):
        state["n"] += 1
        return state["n"] >= 3

    monkeypatch.setattr(rg, "_probe", fake_probe)
    monkeypatch.setattr(rg, "_sleep", lambda s: None)  # sin dormir de verdad

    assert rg.wait_for_http("http://localhost:8000", attempts=10, delay=0.01) is True
    assert state["n"] == 3


def test_wait_never_answers_returns_false(monkeypatch):
    monkeypatch.setattr(rg, "_probe", lambda url, *, timeout=2.0: False)
    monkeypatch.setattr(rg, "_sleep", lambda s: None)

    assert rg.wait_for_http("http://localhost:8000", attempts=5, delay=0.01) is False


# ── workflow bloque-d.yml: existe y declara el servicio Postgres ───────────────

def test_bloque_d_workflow_valid_and_uses_postgres():
    import yaml

    wf = Path(__file__).resolve().parent.parent / ".github" / "workflows" / "bloque-d.yml"
    assert wf.is_file()
    doc = yaml.safe_load(wf.read_text(encoding="utf-8"))
    job = doc["jobs"]["runtime-gates"]
    assert "postgres" in job["services"]
    assert job["services"]["postgres"]["image"].startswith("postgres")
    # No debe colisionar con los checks requeridos existentes.
    assert job["name"] == "runtime-gates (postgres real)"
