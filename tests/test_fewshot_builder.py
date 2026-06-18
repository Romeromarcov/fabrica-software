"""Tests del Sistema de Aprendizaje Nivel 3 — `tools/fewshot_builder.py`.

Cubre ROADMAP_AUTONOMIA I-3: few-shots sólo activos con ≥20 features,
selección de los mejores por quality_score, y límite de tamaño (≤2000 tokens).
Usa un `RUNS_DIR` temporal — sin side effects.
"""
import json

import pytest

from tools import fewshot_builder as fb


@pytest.fixture
def runs_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(fb, "_get_runs_dir", lambda: tmp_path)
    return tmp_path


def _seed_metrics(runs_dir, project, n, qa_iters=1):
    """Crea n features con métricas y un MASTER_PLAN de ejemplo cada uno."""
    proj_dir = runs_dir / project
    proj_dir.mkdir(parents=True, exist_ok=True)
    metrics = proj_dir / "quality_metrics.jsonl"
    with open(metrics, "w", encoding="utf-8") as f:
        for i in range(n):
            fid = f"feat-{i}"
            rec = {
                "feature_id": fid,
                "feature_name": fid,
                "qa_iterations": qa_iters,
                "quality_score": 100 - i,  # feat-0 es el mejor
            }
            f.write(json.dumps(rec) + "\n")
            run_dir = runs_dir / fid
            run_dir.mkdir(parents=True, exist_ok=True)
            (run_dir / "output_a1_planificador.md").write_text(
                f"# MASTER_PLAN {fid}\n## Criterios de aceptación\n- hace X\n",
                encoding="utf-8",
            )


def test_no_fewshot_below_threshold(runs_dir):
    _seed_metrics(runs_dir, "proj", n=fb.MIN_FEATURES_FOR_FEWSHOT - 1)
    assert fb.is_fewshot_ready("proj") is False
    assert fb.build_fewshots("proj") == ""


def test_fewshot_ready_at_threshold(runs_dir):
    _seed_metrics(runs_dir, "proj", n=fb.MIN_FEATURES_FOR_FEWSHOT)
    assert fb.is_fewshot_ready("proj") is True


def test_build_fewshots_selects_best_and_respects_size(runs_dir):
    _seed_metrics(runs_dir, "proj", n=25)
    out = fb.build_fewshots("proj", context="planning")
    assert "EJEMPLOS EXITOSOS" in out
    # El mejor feature (feat-0, score 100) debe aparecer
    assert "feat-0" in out
    # Límite de tamaño respetado
    assert len(out) <= fb.MAX_FEWSHOT_CHARS + 500


def test_no_project_id_returns_empty(runs_dir):
    assert fb.build_fewshots("") == ""
    assert fb.is_fewshot_ready("") is False


def test_compress_master_plan_keeps_headers(runs_dir):
    plan = "# Titulo\nbla bla\n## Criterios de aceptación\n- algo\n"
    compressed = fb._compress_master_plan(plan, max_chars=600)
    assert "# Titulo" in compressed
    assert "Criterios" in compressed
