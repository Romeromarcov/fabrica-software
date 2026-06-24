"""
Tests B3.3 — Aprendizaje preventivo.

Verifica que `recurring_error_patterns` detecte patrones que fallaron ≥2 veces
(desde quality_metrics.jsonl y/o LESSONS_LEARNED.md) y que `hard_instruction_block`
los renderice como instrucción OBLIGATORIA. También verifica que A4 inyecte el
bloque duro en el prompt que recibe call_agent.
"""
import json
from pathlib import Path


from tools.learning_memory import (
    recurring_error_patterns,
    hard_instruction_block,
    LESSONS_FILE,
)
import tools.quality_tracker as qt


# ── Helpers de seed ───────────────────────────────────────────────────────────

def _seed_metrics(runs_dir: Path, project_id: str, records: list[dict]) -> None:
    """Escribe quality_metrics.jsonl en el formato real (una línea JSON por feature)."""
    path = runs_dir / project_id / "quality_metrics.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


# ── recurring_error_patterns desde quality_metrics.jsonl ─────────────────────

def test_recurring_from_metrics(tmp_path, monkeypatch):
    runs_dir = tmp_path / "runs"
    project_id = "proj-1"
    # "missing-fk" aparece 3 veces, "typo" una sola vez
    _seed_metrics(runs_dir, project_id, [
        {"feature_id": "f1", "bug_categories": ["missing-fk", "typo"]},
        {"feature_id": "f2", "bug_categories": ["missing-fk"]},
        {"feature_id": "f3", "bug_categories": ["missing-fk"]},
    ])
    # Forzar que _metrics_path use nuestro runs_dir
    monkeypatch.setattr(qt, "_RUNS_DIR", runs_dir)

    result = recurring_error_patterns(str(tmp_path / "repo"), project_id, min_occurrences=2)
    assert result == ["missing-fk"]
    assert "typo" not in result


def test_recurring_from_lessons(tmp_path, monkeypatch):
    """Las lecciones agrupadas por categoría también cuentan como ocurrencias."""
    monkeypatch.setattr(qt, "_RUNS_DIR", tmp_path / "runs")
    repo = tmp_path / "repo"
    lessons = repo / LESSONS_FILE
    lessons.parent.mkdir(parents=True, exist_ok=True)
    lessons.write_text(
        "# Lessons Learned\n\n"
        "### Base de Datos\n"
        "- [2026-01-01 | feat-a | QA | ALTA] olvidó la FK\n"
        "- [2026-01-02 | feat-b | QA | ALTA] otra FK faltante\n"
        "\n### Tests\n"
        "- [2026-01-03 | feat-c | QA | MEDIA] sin assert\n",
        encoding="utf-8",
    )
    result = recurring_error_patterns(str(repo), "", min_occurrences=2)
    assert result == ["Base de Datos"]  # Tests aparece solo 1 vez


def test_min_occurrences_threshold(tmp_path, monkeypatch):
    runs_dir = tmp_path / "runs"
    monkeypatch.setattr(qt, "_RUNS_DIR", runs_dir)
    _seed_metrics(runs_dir, "p", [
        {"bug_categories": ["x"]},
        {"bug_categories": ["x"]},
    ])
    # Con min=2 → "x" pasa; con min=3 → vacío
    assert recurring_error_patterns(str(tmp_path), "p", min_occurrences=2) == ["x"]
    assert recurring_error_patterns(str(tmp_path), "p", min_occurrences=3) == []


def test_missing_files_returns_empty(tmp_path, monkeypatch):
    """Sin archivos → [] sin lanzar excepción."""
    monkeypatch.setattr(qt, "_RUNS_DIR", tmp_path / "nope")
    result = recurring_error_patterns(str(tmp_path / "no-repo"), "no-project", min_occurrences=2)
    assert result == []


def test_corrupt_jsonl_is_defensive(tmp_path, monkeypatch):
    """JSON corrupto → [] sin error (no bare except, captura JSONDecodeError)."""
    runs_dir = tmp_path / "runs"
    path = runs_dir / "p" / "quality_metrics.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{not valid json\n", encoding="utf-8")
    monkeypatch.setattr(qt, "_RUNS_DIR", runs_dir)
    assert recurring_error_patterns(str(tmp_path), "p", min_occurrences=2) == []


# ── hard_instruction_block ────────────────────────────────────────────────────

def test_hard_block_empty():
    assert hard_instruction_block([]) == ""


def test_hard_block_renders_patterns():
    block = hard_instruction_block(["missing-fk"])
    assert "OBLIGATORIA" in block
    assert "missing-fk" in block
    assert block.startswith("\n")


# ── Test a nivel de nodo A4: el bloque duro entra al prompt ──────────────────

def test_a4_injects_hard_block_into_prompt(tmp_path, monkeypatch):
    import nodes.a4_backend as a4

    runs_dir = tmp_path / "runs"
    project_id = "proj-node"
    _seed_metrics(runs_dir, project_id, [
        {"bug_categories": ["missing-fk"]},
        {"bug_categories": ["missing-fk"]},
    ])
    monkeypatch.setattr(qt, "_RUNS_DIR", runs_dir)

    repo_path = str(tmp_path / "repo")
    (tmp_path / "repo").mkdir(parents=True, exist_ok=True)

    # Neutralizar dependencias externas de contexto para aislar el test
    monkeypatch.setattr(a4, "lessons_for_context", lambda *a, **k: "")
    monkeypatch.setattr(a4, "build_fewshots", lambda *a, **k: "")

    captured = {}

    def fake_call_agent(*, task_content, **kwargs):
        captured["task"] = task_content
        return ("output backend", {"agent": "a4", "model": "m",
                                    "input_tokens": 0, "output_tokens": 0,
                                    "cache_read_tokens": 0, "cost_usd": 0.0})

    monkeypatch.setattr(a4, "call_agent", fake_call_agent)
    monkeypatch.setattr(a4, "save_agent_output", lambda *a, **k: None)

    state = {
        "repo_path": repo_path,
        "project_id": project_id,
        "feature_id": "F1",
        "master_plan": "plan",
        "db_schema": "schema",
        "qa_report": None,
        "qa_iterations": 0,
    }
    result = a4.a4_backend(state)

    assert result["backend_code"] == "output backend"
    assert "OBLIGATORIA" in captured["task"]
    assert "missing-fk" in captured["task"]
