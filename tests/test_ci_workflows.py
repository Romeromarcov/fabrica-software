"""Tests del Bloque C — workflows de CI de la fábrica (C5) y revisor independiente (C1).

No ejecutan GitHub Actions (no hay runner aquí); validan que los workflows existen, son
YAML válido y declaran los gates esperados. La nota PyYAML: las claves `on:` se parsean
como el booleano True en YAML 1.1, por eso se busca tanto `"on"` como `True`.
"""
from pathlib import Path

import yaml

_WF = Path(__file__).resolve().parent.parent / ".github" / "workflows"


def _load(name: str) -> dict:
    return yaml.safe_load((_WF / name).read_text(encoding="utf-8"))


def _triggers(doc: dict) -> dict:
    # YAML 1.1 interpreta `on:` como True; PyYAML lo refleja como clave booleana.
    return doc.get("on") or doc.get(True) or {}


def test_ci_workflow_exists_and_valid():
    assert (_WF / "ci.yml").is_file()
    doc = _load("ci.yml")
    assert "tests" in doc["jobs"]
    assert "gitleaks" in doc["jobs"]


def test_ci_runs_pytest_as_blocking_gate():
    doc = _load("ci.yml")
    steps = doc["jobs"]["tests"]["steps"]
    runs = " ".join(s.get("run", "") for s in steps)
    # pytest es bloqueante (sin `|| true`); pip-audit es consultivo.
    assert "pytest tests/" in runs
    assert "pip-audit" in runs


def test_ci_triggers_on_push_and_pr():
    trig = _triggers(_load("ci.yml"))
    assert "push" in trig
    assert "pull_request" in trig


def test_pr_review_workflow_exists_and_gated_on_secret():
    assert (_WF / "pr-review.yml").is_file()
    doc = _load("pr-review.yml")
    assert "review" in doc["jobs"]
    body = (_WF / "pr-review.yml").read_text(encoding="utf-8")
    # C1: requiere el secret ANTHROPIC_API_KEY y corre en pull_request.
    assert "ANTHROPIC_API_KEY" in body
    trig = _triggers(doc)
    assert "pull_request" in trig
