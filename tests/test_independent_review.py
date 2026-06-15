"""
Tests del Bloque C (PLAN_BLINDAJE_TOTAL):

C3 — Condición de auto-merge ampliada: el revisor INDEPENDIENTE (GitHub Action
     fuera del pipeline) también debe estar verde para permitir el auto-merge.
C4 — Feedback al aprendizaje: record_missed_by_pipeline() registra los hallazgos
     que el revisor independiente detectó y los gates internos dejaron pasar.
"""
from tools.risk_classifier import is_auto_mergeable
from tools.learning_memory import (
    record_missed_by_pipeline,
    recurring_error_patterns,
    LESSONS_FILE,
)


# ── C3: condición de auto-merge ampliada ─────────────────────────────────────

def test_low_green_default_independent_passed_is_mergeable():
    # Sin pasar independent_review_passed → default True → auto-mergeable.
    assert is_auto_mergeable(["docs/x.md"], "LOW", True, True) is True


def test_independent_review_failing_blocks_low_green():
    # El revisor independiente en rojo bloquea el auto-merge aun con LOW + gate verde.
    assert is_auto_mergeable(
        ["docs/x.md"], "LOW", True, True, independent_review_passed=False
    ) is False


def test_existing_positional_4arg_call_still_works():
    # Compatibilidad: la firma posicional de 4 args (call sites/tests existentes)
    # no debe lanzar TypeError; el nuevo param es keyword-only con default.
    assert is_auto_mergeable(["apps/core/views.py"], "HIGH", False, True) is False
    assert is_auto_mergeable(["docs/guia.md"], "LOW", True, True) is True


# ── C4: feedback al aprendizaje (missed_by_pipeline) ─────────────────────────

def test_record_missed_writes_finding_and_tag(tmp_path):
    repo = str(tmp_path)
    record_missed_by_pipeline(repo, "SQL injection en view X", "feat-a")

    lessons = tmp_path / LESSONS_FILE
    assert lessons.exists()
    content = lessons.read_text(encoding="utf-8")
    assert "SQL injection en view X" in content
    assert "missed_by_pipeline" in content


def test_record_missed_twice_seen_by_recurring_patterns(tmp_path):
    repo = str(tmp_path)
    # Dos hallazgos en la misma categoría missed_by_pipeline → ≥ min_occurrences.
    record_missed_by_pipeline(repo, "SQL injection en view X", "feat-a")
    record_missed_by_pipeline(repo, "XSS en plantilla Y", "feat-b")

    patterns = recurring_error_patterns(repo, min_occurrences=2)
    assert "missed_by_pipeline" in patterns
