"""Tests del reporte de release develop→main (PLAN_BLINDAJE_TOTAL D3.1)."""
from tools.release_report import (
    FeatureRelease,
    build_release_report,
    format_release_md,
)


def _gov(tier="LOW"):
    return {"risk_level": tier, "status": "completo", "security_verdict": "PASS"}


def test_empty_release_not_ready():
    r = build_release_report([])
    assert r["ready"] is False
    assert r["feature_count"] == 0


def test_single_promotable_feature_ready():
    f = FeatureRelease("f1", governance=_gov("LOW"), days_in_dev=2, runtime_errors=0)
    r = build_release_report([f])
    assert r["ready"] is True
    assert r["blocked"] == []
    assert r["features"][0]["promotable"] is True


def test_runtime_errors_block_release():
    f = FeatureRelease("f1", governance=_gov("LOW"), days_in_dev=5, runtime_errors=2)
    r = build_release_report([f])
    assert r["ready"] is False
    assert "f1" in r["blocked"]


def test_open_audit_findings_block_release():
    f = FeatureRelease("f1", governance=_gov("LOW"), days_in_dev=5,
                       runtime_errors=0, open_audit_findings=1)
    r = build_release_report([f])
    assert r["ready"] is False
    assert "f1" in r["blocked"]


def test_high_tier_needs_real_usage():
    f = FeatureRelease("f1", governance=_gov("HIGH"), days_in_dev=10,
                       runtime_errors=0, real_usage_verified=False)
    assert build_release_report([f])["ready"] is False
    f.real_usage_verified = True
    assert build_release_report([f])["ready"] is True


def test_mixed_features_one_blocks_release():
    ok = FeatureRelease("ok", governance=_gov("LOW"), days_in_dev=2)
    bad = FeatureRelease("bad", governance=_gov("MEDIUM"), days_in_dev=0.5)
    r = build_release_report([ok, bad])
    assert r["ready"] is False
    assert r["blocked"] == ["bad"]
    assert r["feature_count"] == 2


def test_format_md_ready_and_blocked():
    ready = build_release_report([FeatureRelease("f1", governance=_gov("LOW"), days_in_dev=2)])
    md_ready = format_release_md(ready)
    assert "✅ LISTO" in md_ready
    assert "f1" in md_ready

    blocked = build_release_report([FeatureRelease("f2", governance=_gov("HIGH"), days_in_dev=1)])
    md_blocked = format_release_md(blocked)
    assert "⛔ BLOQUEADO" in md_blocked
    assert "⚠️" in md_blocked  # razones de bloqueo listadas
