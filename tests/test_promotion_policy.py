"""Tests de la política de maduración por riesgo (PLAN_BLINDAJE_TOTAL D2.3)."""
from tools.promotion_policy import (
    MATURATION_DAYS,
    PromotionDecision,
    is_promotable,
    required_maturation_days,
)


def test_required_days_per_tier():
    assert required_maturation_days("LOW") == 1
    assert required_maturation_days("MEDIUM") == 3
    assert required_maturation_days("HIGH") == 7


def test_unknown_tier_treated_as_high():
    assert required_maturation_days("nope") == MATURATION_DAYS["HIGH"]
    assert required_maturation_days("") == MATURATION_DAYS["HIGH"]


def test_low_promotable_after_one_day():
    d = is_promotable("LOW", days_in_dev=1, runtime_errors_clean=True)
    assert isinstance(d, PromotionDecision)
    assert d.promotable is True
    assert d.required_days == 1


def test_low_not_promotable_too_soon():
    d = is_promotable("LOW", days_in_dev=0.5, runtime_errors_clean=True)
    assert d.promotable is False
    assert any("maduración insuficiente" in r for r in d.reasons)


def test_medium_needs_three_days():
    assert is_promotable("MEDIUM", 2.9, True).promotable is False
    assert is_promotable("MEDIUM", 3, True).promotable is True


def test_runtime_errors_block_promotion():
    d = is_promotable("MEDIUM", 10, runtime_errors_clean=False)
    assert d.promotable is False
    assert any("errores de runtime" in r for r in d.reasons)


def test_high_requires_real_usage():
    # tiempo suficiente y sin errores, pero sin uso real → no promovible
    d = is_promotable("HIGH", 10, runtime_errors_clean=True, real_usage_verified=False)
    assert d.promotable is False
    assert any("uso real" in r for r in d.reasons)
    # con uso real verificado → promovible
    d2 = is_promotable("HIGH", 7, runtime_errors_clean=True, real_usage_verified=True)
    assert d2.promotable is True


def test_high_still_blocked_if_too_soon_even_with_usage():
    d = is_promotable("HIGH", 6.9, runtime_errors_clean=True, real_usage_verified=True)
    assert d.promotable is False


def test_unknown_tier_conservative():
    # tier desconocido = HIGH: exige 7d + uso real
    d = is_promotable("weird", 10, runtime_errors_clean=True, real_usage_verified=False)
    assert d.tier == "HIGH"
    assert d.promotable is False


def test_multiple_reasons_accumulate():
    d = is_promotable("HIGH", 1, runtime_errors_clean=False, real_usage_verified=False)
    assert d.promotable is False
    assert len(d.reasons) == 3
