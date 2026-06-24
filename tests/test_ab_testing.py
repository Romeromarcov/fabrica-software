"""Tests del A/B testing de modelos (PLAN_PLATAFORMA_V2 M6, Fase 3)."""
import pytest

from tools import ab_testing as ab


@pytest.fixture
def runs_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(ab, "_runs_dir", lambda: tmp_path)
    return tmp_path


def test_bucket_is_deterministic():
    a = ab._bucket("feat-1", "A4")
    b = ab._bucket("feat-1", "A4")
    assert a == b
    assert 0.0 <= a < 1.0


def test_should_use_variant_bounds():
    assert ab.should_use_variant("feat-1", "A4", 0.0) is False
    assert ab.should_use_variant("feat-1", "A4", 1.0) is True
    assert ab.should_use_variant("", "A4", 0.5) is False  # sin feature_id


def test_should_use_variant_split_is_reasonable():
    # Con pct=0.5, ~mitad de un muestreo cae en variante (determinista pero distribuido).
    hits = sum(ab.should_use_variant(f"feat-{i}", "A4", 0.5) for i in range(200))
    assert 60 <= hits <= 140


def test_choose_model_primary_when_no_alternatives():
    model, variant = ab.choose_model("feat-1", "A4", "primary", [], pct=1.0)
    assert model == "primary"
    assert variant is False


def test_choose_model_variant_when_in_bucket():
    model, variant = ab.choose_model("feat-1", "A4", "primary", ["alt-model"], pct=1.0)
    assert model == "alt-model"
    assert variant is True


def test_record_and_recommend(runs_dir):
    # alt-model rinde mejor (score alto, menos iters) que primary.
    for i in range(3):
        ab.record_result("proj", "A4", "primary", qa_iterations=3,
                         cost_usd=0.2, quality_score=60, is_variant=False)
    for i in range(3):
        ab.record_result("proj", "A4", "alt-model", qa_iterations=1,
                         cost_usd=0.1, quality_score=95, is_variant=True)

    rec = ab.recommend_model("proj", "A4")
    assert rec is not None
    assert rec["recommended_model"] == "alt-model"
    assert len(rec["candidates"]) == 2


def test_recommend_none_without_data(runs_dir):
    assert ab.recommend_model("proj", "A4") is None


def test_recommend_respects_min_samples(runs_dir):
    ab.record_result("proj", "A4", "primary", qa_iterations=1,
                     cost_usd=0.1, quality_score=90, is_variant=False)
    # Solo 1 muestra < min_samples=3 → sin recomendación.
    assert ab.recommend_model("proj", "A4", min_samples=3) is None


def test_record_without_project_is_noop(runs_dir):
    ab.record_result("", "A4", "m", qa_iterations=1, cost_usd=0.1,
                     quality_score=90, is_variant=False)
    assert not any(runs_dir.rglob("ab_results.jsonl"))
