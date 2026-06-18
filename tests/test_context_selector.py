"""Tests del selector de contexto dinámico (PLAN_PLATAFORMA_V2 M8, Fase 2)."""
from pathlib import Path

from tools import context_selector as cs


def test_extract_keywords_drops_stopwords():
    kws = cs.extract_keywords("Crear un endpoint de facturacion para inventario")
    assert "facturacion" in kws
    assert "inventario" in kws
    assert "crear" not in kws   # stopword
    assert "un" not in kws


def test_score_file_path_and_content():
    p = Path("apps/facturacion/models.py")
    score_hit = cs.score_file(p, "class Factura: total = 0", {"facturacion", "factura"})
    score_miss = cs.score_file(Path("apps/otros/x.py"), "nada", {"facturacion"})
    assert score_hit > score_miss
    assert score_miss == 0.0


def test_score_zero_without_keywords():
    assert cs.score_file(Path("a.py"), "contenido", set()) == 0.0


def test_select_relevant_files_picks_matching(tmp_path):
    (tmp_path / "apps" / "facturacion").mkdir(parents=True)
    (tmp_path / "apps" / "facturacion" / "models.py").write_text(
        "class Factura:\n    total = 0\n", encoding="utf-8")
    (tmp_path / "apps" / "otros").mkdir(parents=True)
    (tmp_path / "apps" / "otros" / "models.py").write_text(
        "class Cliente:\n    pass\n", encoding="utf-8")

    out = cs.select_relevant_files(str(tmp_path), "ajustar la facturacion y el total de Factura")
    assert "CONTEXTO RELEVANTE" in out
    assert "facturacion/models.py" in out
    # el archivo no relacionado no debería aparecer
    assert "otros/models.py" not in out


def test_select_empty_when_no_match(tmp_path):
    (tmp_path / "a.py").write_text("print('hola')", encoding="utf-8")
    assert cs.select_relevant_files(str(tmp_path), "facturacion inventario reportes") == ""


def test_select_missing_repo():
    assert cs.select_relevant_files("/no/existe", "x") == ""


def test_select_no_keywords_returns_empty(tmp_path):
    (tmp_path / "a.py").write_text("x = 1", encoding="utf-8")
    # Tarea solo con stopwords → sin keywords → sin contexto.
    assert cs.select_relevant_files(str(tmp_path), "crear un nuevo") == ""


def test_select_respects_max_files(tmp_path):
    for i in range(20):
        (tmp_path / f"facturacion_{i}.py").write_text(
            "factura total", encoding="utf-8")
    out = cs.select_relevant_files(str(tmp_path), "factura total", max_files=5)
    assert out.count("### `") <= 5
