"""Tests del núcleo de promoción a producción (PLAN_BLINDAJE_TOTAL D3.2).

Verifica los tres invariantes PUROS: deploy solo desde main, tag/release por
promoción (secuencia por día) y rollback = redeploy del tag de release anterior.
"""
import pytest

from tools import deploy_release as dr


# ── Deploy solo desde main ────────────────────────────────────────────────────

def test_assert_prod_deployable_allows_main():
    assert dr.assert_prod_deployable("main") is True


def test_assert_prod_deployable_blocks_feature_branch():
    with pytest.raises(dr.ProdDeployError):
        dr.assert_prod_deployable("feature/20260618-algo")


def test_assert_prod_deployable_blocks_develop_and_empty():
    with pytest.raises(dr.ProdDeployError):
        dr.assert_prod_deployable("develop")
    with pytest.raises(dr.ProdDeployError):
        dr.assert_prod_deployable("")


# ── Tag/release por promoción ─────────────────────────────────────────────────

def test_next_release_tag_first_of_day():
    assert dr.next_release_tag([], "20260618") == "release-20260618-01"


def test_next_release_tag_increments_same_day():
    existing = ["release-20260618-01", "release-20260618-02"]
    assert dr.next_release_tag(existing, "20260618") == "release-20260618-03"


def test_next_release_tag_resets_per_day():
    existing = ["release-20260617-05"]
    assert dr.next_release_tag(existing, "20260618") == "release-20260618-01"


def test_next_release_tag_ignores_foreign_tags():
    existing = ["v1.2.3", "nightly-x", "release-20260618-01"]
    assert dr.next_release_tag(existing, "20260618") == "release-20260618-02"


def test_next_release_tag_rejects_bad_date():
    with pytest.raises(ValueError):
        dr.next_release_tag([], "2026-06-18")


def test_parse_release_tag_roundtrip_and_reject():
    assert dr.parse_release_tag("release-20260618-07") == ("20260618", 7)
    assert dr.parse_release_tag("v1.0.0") is None
    assert dr.parse_release_tag("") is None


def test_sorted_release_tags_chronological():
    tags = ["release-20260618-02", "release-20260617-09", "release-20260618-01", "junk"]
    assert dr.sorted_release_tags(tags) == [
        "release-20260617-09",
        "release-20260618-01",
        "release-20260618-02",
    ]


# ── Rollback = redeploy del tag anterior ──────────────────────────────────────

def test_previous_release_tag_penultimate_by_default():
    tags = ["release-20260618-01", "release-20260618-02", "release-20260618-03"]
    assert dr.previous_release_tag(tags) == "release-20260618-02"


def test_previous_release_tag_relative_to_current():
    tags = ["release-20260618-01", "release-20260618-02", "release-20260618-03"]
    assert dr.previous_release_tag(tags, "release-20260618-03") == "release-20260618-02"
    assert dr.previous_release_tag(tags, "release-20260618-01") is None


def test_previous_release_tag_none_when_single():
    assert dr.previous_release_tag(["release-20260618-01"]) is None
    assert dr.previous_release_tag([]) is None


def test_build_rollback_plan_happy_path():
    tags = ["release-20260618-01", "release-20260618-02"]
    plan = dr.build_rollback_plan(tags)
    assert plan["can_rollback"] is True
    assert plan["target_tag"] == "release-20260618-01"
    assert "release-20260618-01" in plan["command"]
    assert "railway" in plan["command"]


def test_build_rollback_plan_cannot_rollback():
    plan = dr.build_rollback_plan(["release-20260618-01"])
    assert plan["can_rollback"] is False
    assert plan["target_tag"] is None
    assert plan["command"] is None


# ── ReleaseRecord ─────────────────────────────────────────────────────────────

def test_build_release_record_mints_tag_and_validates_branch():
    rec = dr.build_release_record(
        existing_tags=["release-20260618-01"],
        today="20260618",
        sha="abc1234",
        branch="main",
        created_at="2026-06-18T12:00:00Z",
        features=["F1", "F2"],
    )
    assert rec.tag == "release-20260618-02"
    assert rec.sha == "abc1234"
    d = rec.as_dict()
    assert d["features"] == ["F1", "F2"]
    assert d["branch"] == "main"


def test_build_release_record_rejects_non_prod_branch():
    with pytest.raises(dr.ProdDeployError):
        dr.build_release_record(
            existing_tags=[],
            today="20260618",
            sha="abc1234",
            branch="develop",
            created_at="2026-06-18T12:00:00Z",
        )
