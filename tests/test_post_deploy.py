"""Tests del smoke post-deploy + rollback (PLAN_BLINDAJE_TOTAL D3.3).

Verifica el núcleo PURO: evaluación de checks, veredicto agregado, alerta Telegram
con el comando de rollback y la decisión orquestada.
"""
from tools import post_deploy as pd


# ── Checks individuales ───────────────────────────────────────────────────────

def test_default_smoke_checks_includes_healthz():
    names = {c.name for c in pd.default_smoke_checks()}
    assert "healthz" in names


def test_evaluate_check_status_ok():
    c = pd.SmokeCheck("healthz", "/healthz", 200)
    r = pd.evaluate_check(c, 200)
    assert r["ok"] is True


def test_evaluate_check_status_mismatch():
    c = pd.SmokeCheck("healthz", "/healthz", 200)
    r = pd.evaluate_check(c, 503)
    assert r["ok"] is False
    assert "503" in r["detail"]


def test_evaluate_check_body_contains():
    c = pd.SmokeCheck("home", "/", 200, expect_contains="Fábrica")
    assert pd.evaluate_check(c, 200, "<h1>Fábrica</h1>")["ok"] is True
    assert pd.evaluate_check(c, 200, "<h1>otra</h1>")["ok"] is False


# ── Veredicto agregado ────────────────────────────────────────────────────────

def test_evaluate_smoke_all_pass():
    results = [{"name": "a", "ok": True, "detail": ""}, {"name": "b", "ok": True, "detail": ""}]
    v = pd.evaluate_smoke(results)
    assert v["passed"] is True
    assert v["failed"] == 0


def test_evaluate_smoke_one_fail():
    results = [{"name": "a", "ok": True, "detail": ""}, {"name": "b", "ok": False, "detail": "x"}]
    v = pd.evaluate_smoke(results)
    assert v["passed"] is False
    assert v["failed"] == 1
    assert v["failed_checks"][0]["name"] == "b"


def test_evaluate_smoke_empty_is_not_passed():
    assert pd.evaluate_smoke([])["passed"] is False


# ── Alerta Telegram ───────────────────────────────────────────────────────────

def test_build_smoke_alert_empty_when_passed():
    assert pd.build_smoke_alert("release-20260618-02", {"passed": True}, {}) == ""


def test_build_smoke_alert_includes_rollback_command():
    smoke = {"passed": False, "total": 2, "failed": 1,
             "failed_checks": [{"name": "healthz", "detail": "status 503 ≠ esperado 200 (/healthz)"}]}
    rollback = {"can_rollback": True, "target_tag": "release-20260618-01",
                "command": "git checkout release-20260618-01 && railway up --detach"}
    msg = pd.build_smoke_alert("release-20260618-02", smoke, rollback)
    assert "FALLÓ" in msg
    assert "release-20260618-01" in msg
    assert "railway up" in msg


def test_build_smoke_alert_warns_when_no_rollback():
    smoke = {"passed": False, "total": 1, "failed": 1,
             "failed_checks": [{"name": "home", "detail": "status 500"}]}
    rollback = {"can_rollback": False, "target_tag": None, "command": None}
    msg = pd.build_smoke_alert("release-20260618-01", smoke, rollback)
    assert "manual" in msg.lower()


# ── Decisión orquestada ───────────────────────────────────────────────────────

def test_post_deploy_decision_pass():
    results = [{"name": "healthz", "ok": True, "detail": "OK"}]
    d = pd.post_deploy_decision(
        deploy_tag="release-20260618-02",
        results=results,
        existing_tags=["release-20260618-01", "release-20260618-02"],
    )
    assert d["ok"] is True
    assert d["alert"] == ""
    assert d["rollback"] is None


def test_post_deploy_decision_fail_triggers_rollback_and_alert():
    results = [{"name": "healthz", "ok": False, "detail": "status 503"}]
    d = pd.post_deploy_decision(
        deploy_tag="release-20260618-02",
        results=results,
        existing_tags=["release-20260618-01", "release-20260618-02"],
        current_tag="release-20260618-02",
    )
    assert d["ok"] is False
    assert d["rollback"]["can_rollback"] is True
    assert d["rollback"]["target_tag"] == "release-20260618-01"
    assert "release-20260618-01" in d["alert"]


def test_post_deploy_decision_fail_no_prior_tag():
    results = [{"name": "healthz", "ok": False, "detail": "status 503"}]
    d = pd.post_deploy_decision(
        deploy_tag="release-20260618-01",
        results=results,
        existing_tags=["release-20260618-01"],
        current_tag="release-20260618-01",
    )
    assert d["ok"] is False
    assert d["rollback"]["can_rollback"] is False
