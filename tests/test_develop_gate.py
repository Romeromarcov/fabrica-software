"""Tests de la compuerta efímero → develop/dev (PLAN_BLINDAJE_TOTAL D2.1)."""
import pytest

from tools import develop_gate as dg


def test_mergeable_when_all_green():
    d = dg.is_mergeable_to_develop(
        ephemeral_passed=True,
        internal_gates_green=True,
        independent_review_passed=True,
    )
    assert d.mergeable is True
    assert d.reasons == []


def test_blocked_when_ephemeral_fails():
    d = dg.is_mergeable_to_develop(
        ephemeral_passed=False,
        internal_gates_green=True,
        independent_review_passed=True,
    )
    assert d.mergeable is False
    assert any("efímero" in r for r in d.reasons)


def test_blocked_when_internal_gates_red():
    d = dg.is_mergeable_to_develop(
        ephemeral_passed=True,
        internal_gates_green=False,
        independent_review_passed=True,
    )
    assert d.mergeable is False
    assert any("internos" in r for r in d.reasons)


def test_blocked_when_independent_review_missing():
    d = dg.is_mergeable_to_develop(
        ephemeral_passed=True,
        internal_gates_green=True,
        independent_review_passed=False,
    )
    assert d.mergeable is False
    assert any("revisor independiente" in r for r in d.reasons)


def test_all_reasons_accumulate():
    d = dg.is_mergeable_to_develop(
        ephemeral_passed=False,
        internal_gates_green=False,
        independent_review_passed=False,
    )
    assert d.mergeable is False
    assert len(d.reasons) == 3
    assert d.as_dict()["mergeable"] is False


def test_tier_agnostic_high_risk_still_mergeable_to_develop():
    # No hay parámetro de tier: dev es donde madura el riesgo, no donde se filtra.
    d = dg.is_mergeable_to_develop(
        ephemeral_passed=True,
        internal_gates_green=True,
        independent_review_passed=True,
    )
    assert d.mergeable is True


# ── Plan de deploy a dev ──────────────────────────────────────────────────────

def test_build_dev_deploy_plan_shape():
    plan = dg.build_dev_deploy_plan(
        service_id="svc-1", environment_id="env-dev", feature_id="F1"
    )
    assert plan["service_id"] == "svc-1"
    assert plan["environment"] == "env-dev"
    assert plan["stage"] == "dev"
    assert plan["feature_id"] == "F1"


def test_build_dev_deploy_plan_requires_service():
    with pytest.raises(ValueError):
        dg.build_dev_deploy_plan(service_id="", environment_id="env", feature_id="F1")


def test_build_dev_deploy_plan_requires_environment():
    with pytest.raises(ValueError):
        dg.build_dev_deploy_plan(service_id="svc", environment_id="", feature_id="F1")
