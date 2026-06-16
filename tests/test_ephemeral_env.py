"""
PLAN_BLINDAJE_TOTAL — D1.1 + D1.3: pruebas del orquestador de entornos efímeros.

Toda interacción con docker pasa por `tools.ephemeral_env._run`; los tests lo
parchean para correr OFFLINE (sin daemon docker). Cubren:
  • `project_name`: sanitiza/trunca, determinista, prefijo fab-eph-.
  • `compose_config`/`compose_yaml`: servicios, postgres:16 + healthcheck,
    DATABASE_URL → db, límites de recursos (defaults y explícitos), redis opcional.
  • `create_ephemeral_env`: éxito (ok=True, `up -d --wait` con el proyecto correcto)
    y fallo (ok=False + teardown intentado).
  • `ephemeral_env`: teardown garantizado aunque el cuerpo lance.
  • `select_orphans`: puro — solo fab-eph-* más viejos que max_age.
  • Timeout: `_run` que lanza TimeoutExpired → fallo + teardown, sin excepción.
"""
from __future__ import annotations

import subprocess

import pytest
import yaml

from tools import ephemeral_env as ee


# ── project_name (puro) ────────────────────────────────────────────────────────

def test_project_name_sanitiza_y_minuscula():
    assert ee.project_name("Feature/ABC_123") == "fab-eph-feature-abc-123"


def test_project_name_determinista():
    assert ee.project_name("feat-x") == ee.project_name("feat-x")


def test_project_name_solo_chars_validos():
    name = ee.project_name("Weird!!  Name@@##")
    body = name[len(ee.PROJECT_PREFIX):]
    assert all(c.islower() or c.isdigit() or c == "-" for c in body)
    assert not body.startswith("-") and not body.endswith("-")


def test_project_name_trunca():
    name = ee.project_name("x" * 200)
    assert len(name) <= 48
    assert name.startswith("fab-eph-")
    assert not name.endswith("-")


def test_project_name_vacio_usa_anon():
    assert ee.project_name("") == "fab-eph-anon"
    assert ee.project_name("!!!") == "fab-eph-anon"


# ── compose_config / compose_yaml (puro) ───────────────────────────────────────

def test_compose_config_servicios_basicos():
    cfg = ee.compose_config("/repo", "feat-1")
    assert set(cfg["services"]) == {"app", "db"}
    assert cfg["name"] == "fab-eph-feat-1"
    assert cfg["services"]["db"]["image"] == "postgres:16"


def test_compose_config_db_healthcheck():
    cfg = ee.compose_config("/repo", "feat-1")
    hc = cfg["services"]["db"]["healthcheck"]
    assert "test" in hc and hc["retries"] >= 1


def test_compose_config_app_depends_on_db_healthy():
    cfg = ee.compose_config("/repo", "feat-1")
    dep = cfg["services"]["app"]["depends_on"]
    assert dep["db"]["condition"] == "service_healthy"


def test_compose_config_database_url_apunta_a_db():
    cfg = ee.compose_config("/repo", "feat-1")
    url = cfg["services"]["app"]["environment"]["DATABASE_URL"]
    assert "@db:5432/" in url and url.startswith("postgresql://")


def test_compose_config_limites_por_defecto(monkeypatch):
    import config
    monkeypatch.setattr(config, "EPHEMERAL_MEM_LIMIT", "512m", raising=False)
    monkeypatch.setattr(config, "EPHEMERAL_CPUS", "0.5", raising=False)
    cfg = ee.compose_config("/repo", "feat-1")
    for svc in ("app", "db"):
        s = cfg["services"][svc]
        assert s["mem_limit"] == "512m"
        assert s["cpus"] == "0.5"
        assert s["deploy"]["resources"]["limits"]["memory"] == "512m"
        assert s["deploy"]["resources"]["limits"]["cpus"] == "0.5"


def test_compose_config_limites_explicitos():
    cfg = ee.compose_config("/repo", "feat-1",
                            limits={"mem_limit": "2g", "cpus": "2.0"})
    s = cfg["services"]["app"]
    assert s["mem_limit"] == "2g"
    assert s["cpus"] == "2.0"
    assert s["deploy"]["resources"]["limits"] == {"cpus": "2.0", "memory": "2g"}


def test_compose_config_redis_opcional():
    sin = ee.compose_config("/repo", "feat-1")
    assert "redis" not in sin["services"]
    con = ee.compose_config("/repo", "feat-1", with_redis=True)
    assert "redis" in con["services"]
    assert con["services"]["redis"]["image"] == "redis:7"
    assert con["services"]["app"]["depends_on"]["redis"]["condition"] == "service_healthy"
    assert con["services"]["app"]["environment"]["REDIS_URL"].startswith("redis://redis")


def test_compose_yaml_serializa_y_reparsea():
    cfg = ee.compose_config("/repo", "feat-1")
    text = ee.compose_yaml(cfg)
    assert isinstance(text, str)
    back = yaml.safe_load(text)
    assert back["services"]["db"]["image"] == "postgres:16"
    assert back["name"] == "fab-eph-feat-1"


# ── create_ephemeral_env ────────────────────────────────────────────────────────

def test_create_ephemeral_env_exito(monkeypatch):
    calls = []

    def fake_run(cmd, *, cwd=None, timeout=120):
        calls.append(cmd)
        return ("up", "", 0)

    monkeypatch.setattr(ee, "_run", fake_run)
    res = ee.create_ephemeral_env("/repo", "feat-1")
    assert res["ok"] is True
    assert res["project"] == "fab-eph-feat-1"
    # Se llamó `compose up -d --wait` con el proyecto correcto.
    up = calls[0]
    assert up[:3] == ["docker", "compose", "-p"]
    assert up[3] == "fab-eph-feat-1"
    assert "up" in up and "--wait" in up
    # En éxito NO se hace teardown.
    assert not any("down" in c for c in calls)


def test_create_ephemeral_env_fallo_hace_teardown(monkeypatch):
    calls = []

    def fake_run(cmd, *, cwd=None, timeout=120):
        calls.append(cmd)
        if "up" in cmd:
            return ("", "boom: build failed", 1)
        return ("", "", 0)  # el down

    monkeypatch.setattr(ee, "_run", fake_run)
    res = ee.create_ephemeral_env("/repo", "feat-1")
    assert res["ok"] is False
    assert "boom" in res["stderr"]
    # Teardown intentado.
    assert any("down" in c for c in calls)


# ── ephemeral_env context manager ───────────────────────────────────────────────

def test_ephemeral_env_teardown_garantizado_en_excepcion(monkeypatch):
    calls = []

    def fake_run(cmd, *, cwd=None, timeout=120):
        calls.append(cmd)
        return ("", "", 0)

    monkeypatch.setattr(ee, "_run", fake_run)

    with pytest.raises(RuntimeError):
        with ee.ephemeral_env("/repo", "feat-1") as env:
            assert env["ok"] is True
            raise RuntimeError("explota el cuerpo")

    # Aun con la excepción, el `down` corrió en el finally.
    assert any("down" in c for c in calls)


def test_ephemeral_env_teardown_en_salida_normal(monkeypatch):
    calls = []
    monkeypatch.setattr(ee, "_run",
                        lambda cmd, *, cwd=None, timeout=120: calls.append(cmd) or ("", "", 0))
    with ee.ephemeral_env("/repo", "feat-1"):
        pass
    assert any("down" in c for c in calls)


# ── select_orphans (puro) ───────────────────────────────────────────────────────

def test_select_orphans_solo_viejos_y_con_prefijo():
    now = 1000.0
    projects = [
        {"project": "fab-eph-old", "created": 0.0},        # edad 1000 → reap
        {"project": "fab-eph-new", "created": 990.0},      # edad 10 → no
        {"project": "otro-proyecto", "created": 0.0},      # sin prefijo → no
        {"project": "fab-eph-nots", "created": None},      # sin timestamp → no
    ]
    res = ee.select_orphans(projects, max_age=100, now=now)
    assert res == ["fab-eph-old"]


def test_select_orphans_borde_no_incluye_iguales():
    now = 1000.0
    projects = [{"project": "fab-eph-edge", "created": 900.0}]  # edad exacta 100
    assert ee.select_orphans(projects, max_age=100, now=now) == []


# ── Timeout ─────────────────────────────────────────────────────────────────────

def test_create_ephemeral_env_timeout_hace_teardown_sin_lanzar(monkeypatch):
    calls = []

    def fake_run(cmd, *, cwd=None, timeout=120):
        calls.append(cmd)
        if "up" in cmd:
            raise subprocess.TimeoutExpired(cmd, timeout)
        return ("", "", 0)  # el down sí responde

    monkeypatch.setattr(ee, "_run", fake_run)
    res = ee.create_ephemeral_env("/repo", "feat-1", timeout=5)
    assert res["ok"] is False
    assert "timeout" in res["stderr"].lower()
    assert any("down" in c for c in calls)


def test_destroy_idempotente_no_lanza_en_timeout(monkeypatch):
    def fake_run(cmd, *, cwd=None, timeout=120):
        raise subprocess.TimeoutExpired(cmd, timeout)

    monkeypatch.setattr(ee, "_run", fake_run)
    # No debe propagar; devuelve False.
    assert ee.destroy_ephemeral_env("feat-1") is False
