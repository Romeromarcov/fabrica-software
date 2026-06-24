"""Tests de trazabilidad objetivo→backlog R5 (PLAN_PLATAFORMA_V2 Fase 9). Determinista."""
import json

import pytest

import tools.traceability as tr


def test_extract_requirements_fallback():
    reqs = tr.extract_requirements("Login con OAuth. Exportar reportes a PDF; panel de métricas")
    assert len(reqs) == 3
    assert any("OAuth" in r for r in reqs)


def test_extract_requirements_llm_list():
    reqs = tr.extract_requirements("x", llm=lambda _o: ["facturación recurrente", "multimoneda"])
    assert reqs == ["facturación recurrente", "multimoneda"]


def test_extract_requirements_llm_json_string():
    reqs = tr.extract_requirements("x", llm=lambda _o: json.dumps(["alpha beta", "gamma delta"]))
    assert reqs == ["alpha beta", "gamma delta"]


def test_extract_requirements_bad_json_raises():
    with pytest.raises(ValueError, match="JSON válido"):
        tr.extract_requirements("x", llm=lambda _o: "no json")


def test_full_coverage_no_gaps():
    reqs = ["autenticación oauth google", "exportar reportes pdf"]
    backlog = [
        {"id": "B1", "description": "Implementar autenticación OAuth con Google"},
        {"id": "B2", "description": "Exportar reportes financieros a PDF"},
    ]
    cov = tr.coverage(reqs, backlog)
    assert cov["gaps"] == []
    assert cov["coverage_pct"] == 100.0
    assert "B1" in cov["mapping"]["autenticación oauth google"]


def test_detects_gap():
    reqs = ["autenticación oauth google", "panel métricas tiempo real"]
    backlog = [{"id": "B1", "description": "autenticación OAuth con Google"}]
    cov = tr.coverage(reqs, backlog)
    assert "panel métricas tiempo real" in cov["gaps"]
    assert cov["coverage_pct"] == 50.0


def test_coverage_accepts_plain_strings():
    cov = tr.coverage(["exportar pdf reportes"], ["exportar reportes a pdf"])
    assert cov["gaps"] == []


def test_is_complete():
    assert tr.is_complete(["facturación recurrente multimoneda"],
                          [{"description": "facturación recurrente con multimoneda"}]) is True
    assert tr.is_complete(["notificaciones push móvil"],
                          [{"description": "envío de emails"}]) is False


def test_min_ratio_strictness():
    reqs = ["integración pasarela pagos stripe webhooks"]
    backlog = [{"description": "pasarela pagos"}]  # cubre 2/5 términos
    assert tr.coverage(reqs, backlog, min_ratio=0.3)["gaps"] == []      # laxo → cubierto
    assert tr.coverage(reqs, backlog, min_ratio=0.8)["gaps"] != []      # estricto → gap


def test_format_report_complete():
    rep = tr.format_traceability_report("exportar reportes pdf",
                                        [{"description": "exportar reportes a pdf"}])
    assert "cubre el objetivo completo" in rep


def test_format_report_with_gap():
    rep = tr.format_traceability_report("login oauth. dashboard analítica avanzada",
                                        [{"description": "login con oauth"}])
    assert "GAP" in rep
