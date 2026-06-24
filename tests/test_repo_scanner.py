"""Tests de `tools/repo_scanner.py` (PLAN.md §4 — contexto del repo para A0).

Cubre el snapshot del repo, el respeto del token budget (max_files / max_total_chars)
y el manejo de repos inexistentes.
"""
from tools import repo_scanner as rs


def test_scan_repo_missing_path():
    out = rs.scan_repo("/no/existe/jamas")
    assert "no encontrado" in out.lower()


def test_scan_repo_includes_relevant_files(tmp_path):
    (tmp_path / "requirements.txt").write_text("django\n", encoding="utf-8")
    apps = tmp_path / "apps" / "core"
    apps.mkdir(parents=True)
    (apps / "models.py").write_text("class Empresa: pass\n", encoding="utf-8")

    out = rs.scan_repo(str(tmp_path), stack={"backend": "django", "frontend": "unknown"})
    assert "SNAPSHOT DEL REPOSITORIO" in out
    assert "requirements.txt" in out


def test_scan_repo_respects_max_files(tmp_path):
    # Crear muchos archivos .py de alto y bajo nivel
    pkg = tmp_path / "pkg"
    pkg.mkdir()
    for i in range(50):
        (pkg / f"mod{i}.py").write_text(f"x = {i}\n", encoding="utf-8")

    out = rs.scan_repo(str(tmp_path), max_files=5)
    # Cada archivo incluido se renderiza con un encabezado "### `...`"
    assert out.count("### `") <= 5


def test_scan_repo_respects_total_char_budget(tmp_path):
    big = "A" * 5000
    for i in range(10):
        (tmp_path / f"f{i}.py").write_text(big, encoding="utf-8")
    out = rs.scan_repo(str(tmp_path), max_files=30, max_total_chars=8000)
    # El presupuesto total no debe excederse de forma desbocada
    assert len(out) < 8000 + 6000  # header + un bloque de margen


def test_get_repo_context_for_a0_wraps_snapshot(tmp_path):
    (tmp_path / "requirements.txt").write_text("django\n", encoding="utf-8")
    out = rs.get_repo_context_for_a0(str(tmp_path))
    assert "CÓDIGO ACTUAL DEL REPOSITORIO" in out
