"""Tests del escáner determinista de secretos (A2.2 — PLAN_BLINDAJE_TOTAL).

Verifica:
  1. Detección de secreto hardcodeado + enmascarado (no se filtra el valor).
  2. Exclusión de placeholders (os.getenv, your-token-here).
  3. Detección de GitHub PAT clásico.
  4. Gate saltado cuando config.SECRET_SCAN_GATE=False (monkeypatch dinámico).
"""
import config
from tools.code_sandbox import scan_secrets, run_all_checks


def test_scan_detects_hardcoded_anthropic_key_and_masks(tmp_path):
    secret = "sk-ant-api03-AAAABBBBCCCCDDDD1234"
    f = tmp_path / "app.py"
    f.write_text(f'API_KEY = "{secret}"\n')

    findings = scan_secrets(str(tmp_path))

    assert len(findings) >= 1
    fd = findings[0]
    assert fd["file"] == "app.py"
    assert fd["line"] == 1
    # El secreto completo NO debe aparecer en el dict devuelto.
    assert secret not in fd["snippet"]
    assert "***" in fd["snippet"]
    # Verifica que el valor crudo no se filtre en ningún campo.
    for v in fd.values():
        assert secret not in str(v)


def test_scan_excludes_placeholders(tmp_path):
    f = tmp_path / "settings.py"
    f.write_text(
        "import os\n"
        'API_KEY = os.getenv("API_KEY")\n'
        'TOKEN = "your-token-here"\n'
    )

    findings = scan_secrets(str(tmp_path))

    assert findings == []


def test_scan_detects_github_pat(tmp_path):
    f = tmp_path / "deploy.py"
    f.write_text('GH = "ghp_0123456789abcdefghijABCDEFGHIJ012345"\n')

    findings = scan_secrets(str(tmp_path))

    assert len(findings) >= 1
    assert any(fd["kind"] == "github-pat-classic" for fd in findings)
    # Token enmascarado.
    assert all("ghp_0123456789abcdefghijABCDEFGHIJ012345" not in fd["snippet"]
               for fd in findings)


def test_scan_targets_explicit_files(tmp_path):
    bad = tmp_path / "bad.py"
    bad.write_text('GH = "ghp_0123456789abcdefghijABCDEFGHIJ012345"\n')
    good = tmp_path / "good.py"
    good.write_text("x = 1\n")

    findings = scan_secrets(str(tmp_path), files=["good.py"])
    assert findings == []

    findings = scan_secrets(str(tmp_path), files=["bad.py"])
    assert len(findings) >= 1


def test_gate_fails_when_secret_present(tmp_path):
    # Repo sin stack ejecutable: el único gate que falla es secret-scan.
    (tmp_path / "app.py").write_text(
        'API_KEY = "sk-ant-api03-AAAABBBBCCCCDDDD1234"\n'
    )

    result = run_all_checks(str(tmp_path), install_deps=False)

    assert result["passed"] is False
    gates = [gf["gate"] for gf in result["gate_failures"]]
    assert "secret-scan" in gates
    gf = next(gf for gf in result["gate_failures"] if gf["gate"] == "secret-scan")
    assert gf["layer"] == "security"
    assert gf["hard"] is True


def test_gate_skipped_when_flag_disabled(tmp_path, monkeypatch):
    (tmp_path / "app.py").write_text(
        'API_KEY = "sk-ant-api03-AAAABBBBCCCCDDDD1234"\n'
    )
    # Referencia dinámica: config.SECRET_SCAN_GATE leído dentro del gate.
    monkeypatch.setattr(config, "SECRET_SCAN_GATE", False)

    result = run_all_checks(str(tmp_path), install_deps=False)

    gates = [gf["gate"] for gf in result["gate_failures"]]
    assert "secret-scan" not in gates
    # El gate debe figurar como saltado por 'disabled'.
    sr = result["results"]["secret_scan"]
    assert sr["skipped"] is True
    assert sr["skip_reason"] == "disabled"


def test_spanish_changeme_placeholder_not_flagged(tmp_path):
    """F6 — un default 'cambiar_en_produccion...' es un placeholder, no un secreto real."""
    from tools.code_sandbox import scan_secrets
    f = tmp_path / "config.py"
    # Placeholder de plantilla (no es un secreto real). gitleaks:allow
    placeholder = "cambiar_en_produccion_" + "clave_muy_larga_123456789"  # gitleaks:allow
    f.write_text(f"_DEFAULT_SECRET = '{placeholder}'\n", encoding="utf-8")
    assert scan_secrets(str(tmp_path)) == []


def test_real_secret_still_flagged(tmp_path):
    # Patrón obviamente falso (como el resto de este archivo) — lo detecta scan_secrets pero
    # no es un secreto real (evita disparar gitleaks en el repo).
    from tools.code_sandbox import scan_secrets
    f = tmp_path / "config.py"
    f.write_text('API_KEY = "sk-ant-api03-AAAABBBBCCCCDDDD1234"\n', encoding="utf-8")
    assert len(scan_secrets(str(tmp_path))) >= 1
