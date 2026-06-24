"""Tests de la integración con issue trackers (PLAN_PLATAFORMA_V2 M12, Fase 10)."""
from tools import issue_tracker as it


def test_parse_issue_to_feature():
    issue = {"title": "Añadir export CSV", "number": 42,
             "body": "Necesitamos export.\n\n## Criterios de aceptación\n- [ ] botón export\n- [ ] genera CSV válido",
             "labels": ["feature"]}
    spec = it.parse_issue_to_feature(issue)
    assert spec["feature_name"] == "Añadir export CSV"
    assert spec["source_issue"] == 42
    assert "Necesitamos export" in spec["brief"]
    assert spec["acceptance_criteria"] == ["botón export", "genera CSV válido"]
    assert spec["labels"] == ["feature"]


def test_parse_issue_without_title_uses_number():
    spec = it.parse_issue_to_feature({"number": 7, "body": ""})
    assert spec["feature_name"] == "issue-7"


def test_extract_acceptance_criteria_section_only():
    body = ("Intro bla bla\n- esto no cuenta\n"
            "## Acceptance Criteria\n- uno\n- dos\n\n## Otra sección\n- tres")
    crit = it.extract_acceptance_criteria(body)
    assert crit == ["uno", "dos"]


def test_extract_acceptance_criteria_empty():
    assert it.extract_acceptance_criteria("sin seccion de criterios") == []


def test_close_keyword():
    assert it.close_keyword(15) == "Closes #15"
    assert it.close_keyword(None) == ""


def test_traceability_block():
    out = it.traceability_block(["req a", "req b"], pr_url="http://pr/1", issue_number=9)
    assert "Trazabilidad" in out
    assert "#9" in out
    assert "http://pr/1" in out
    assert "- [ ] req a" in out


def test_traceability_block_no_requirements():
    out = it.traceability_block([], issue_number=3)
    assert "Sin criterios" in out


def test_fetch_issue_not_configured():
    res = it.fetch_issue("github", "owner/repo#1")
    assert res["status"] == "not_configured"
    assert res["provider"] == "github"


def test_fetch_issue_unknown_provider():
    assert it.fetch_issue("telepatia", "x")["status"] == "error"


def test_create_subissues_not_configured():
    res = it.create_subissues("linear", "PARENT-1", ["A4", "A5"])
    assert res["status"] == "not_configured"
    assert res["planned_subissues"] == ["A4", "A5"]
