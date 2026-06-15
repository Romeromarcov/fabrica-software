"""Tests de calidad de tests generados + cobertura de código nuevo
(Bloque B — PLAN_BLINDAJE_TOTAL).

Verifica:
  B2.3 — scan_trivial_tests:
    1. Flagea tests triviales (assert True) y vacíos (pass) pero NO un test real.
    2. Un archivo que no es de test (models.py) no se escanea/flagea.
    3. Un archivo de test sintácticamente roto no rompe (devuelve [] para él).
    4. Gate test-quality saltado cuando config.TEST_QUALITY_GATE=False (monkeypatch).
  B2.2 — coverage_shortfall:
    5. Devuelve solo los archivos por debajo del umbral.
"""
import config
from tools.code_sandbox import scan_trivial_tests, coverage_shortfall, run_all_checks


def test_scan_flags_trivial_and_empty_but_not_real(tmp_path):
    f = tmp_path / "test_sample.py"
    f.write_text(
        "def test_x():\n"
        "    assert True\n"
        "\n"
        "def test_y():\n"
        "    pass\n"
        "\n"
        "def test_z():\n"
        "    assert foo() == 3\n"
    )

    findings = scan_trivial_tests(str(tmp_path))

    by_name = {fd["name"]: fd for fd in findings}
    # test_x → solo asserts triviales.
    assert "test_x" in by_name
    assert by_name["test_x"]["kind"] == "trivial-assert"
    assert by_name["test_x"]["file"] == "test_sample.py"
    # test_y → cuerpo vacío (solo pass).
    assert "test_y" in by_name
    assert by_name["test_y"]["kind"] == "empty-test"
    # test_z → test real con assert significativo, NO debe flagearse.
    assert "test_z" not in by_name


def test_non_test_file_not_scanned(tmp_path):
    f = tmp_path / "models.py"
    f.write_text(
        "def test_helper():\n"
        "    pass\n"   # parece test, pero el archivo no es de test
    )

    findings = scan_trivial_tests(str(tmp_path))

    assert findings == []


def test_broken_test_file_does_not_crash(tmp_path):
    broken = tmp_path / "test_broken.py"
    broken.write_text("def test_oops(:\n    assert True\n")  # SyntaxError

    findings = scan_trivial_tests(str(tmp_path))

    # No se recolecta nada para el archivo roto y no se propaga la excepción.
    assert findings == []


def test_coverage_shortfall_returns_only_below_threshold():
    short = coverage_shortfall(
        {"a.py": 90.0, "b.py": 50.0}, ["a.py", "b.py"], 80
    )

    assert len(short) == 1
    assert short[0]["file"] == "b.py"
    assert short[0]["pct"] == 50.0
    assert short[0]["minimum"] == 80


def test_gate_fails_on_trivial_test(tmp_path):
    # Repo sin stack ejecutable: el gate test-quality es el que falla.
    (tmp_path / "test_thing.py").write_text(
        "def test_x():\n    assert True\n"
    )

    result = run_all_checks(str(tmp_path), install_deps=False,
                            files=["test_thing.py"])

    assert result["passed"] is False
    gf = next(gf for gf in result["gate_failures"] if gf["gate"] == "test-quality")
    assert gf["layer"] == "tests"
    assert gf["hard"] is True


def test_gate_skipped_when_flag_disabled(tmp_path, monkeypatch):
    (tmp_path / "test_thing.py").write_text(
        "def test_x():\n    assert True\n"
    )
    # Referencia dinámica: config.TEST_QUALITY_GATE leído dentro del gate.
    monkeypatch.setattr(config, "TEST_QUALITY_GATE", False)

    result = run_all_checks(str(tmp_path), install_deps=False,
                            files=["test_thing.py"])

    gates = [gf["gate"] for gf in result["gate_failures"]]
    assert "test-quality" not in gates
    tq = result["results"]["test_quality"]
    assert tq["skipped"] is True
    assert tq["skip_reason"] == "disabled"
