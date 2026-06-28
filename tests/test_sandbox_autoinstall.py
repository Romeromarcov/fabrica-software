"""Auto-instalación de dependencias faltantes en el sandbox (a medida que surgen)."""
import tools.code_sandbox as cs


def test_missing_packages_extracts_and_maps(tmp_path):
    out = "ModuleNotFoundError: No module named 'httpx'\nNo module named 'jose'\n"
    pkgs = cs._missing_packages(out, str(tmp_path))
    assert "httpx" in pkgs
    assert "python-jose" in pkgs   # mapeo import→paquete


def test_missing_packages_skips_local_and_stdlib(tmp_path):
    # 'main' es local (existe en el repo) y 'os' es stdlib → no se instalan.
    (tmp_path / "main.py").write_text("x = 1\n", encoding="utf-8")
    out = "No module named 'main'\nNo module named 'os'\nNo module named 'requests'\n"
    pkgs = cs._missing_packages(out, str(tmp_path))
    assert "main" not in pkgs
    assert "os" not in pkgs
    assert "requests" in pkgs


def test_plugin_signatures_detected(tmp_path):
    out = "ERROR: usage: pytest [options]\npytest: error: unrecognized arguments: --cov=."
    pkgs = cs._missing_packages(out, str(tmp_path))
    assert "pytest-cov" in pkgs


def test_record_requirement_appends_and_dedupes(tmp_path):
    req = tmp_path / "requirements.txt"
    req.write_text("fastapi\nhttpx==0.27.0\n", encoding="utf-8")
    cs._record_requirement(str(tmp_path), "pytest-asyncio")
    cs._record_requirement(str(tmp_path), "httpx")   # ya presente (con versión) → no duplica
    lines = [l.strip() for l in req.read_text(encoding="utf-8").splitlines() if l.strip()]
    assert "pytest-asyncio" in lines
    assert lines.count("httpx==0.27.0") == 1
    assert sum(1 for l in lines if l.lower().startswith("httpx")) == 1


def test_autoinstall_loop_installs_then_passes(tmp_path, monkeypatch):
    """Primer run falla por módulo ausente; tras instalar (mock), el segundo pasa."""
    (tmp_path / "requirements.txt").write_text("fastapi\n", encoding="utf-8")
    calls = {"runs": 0, "installed": []}

    def fake_run(cmd, cwd, timeout=120, env=None):
        calls["runs"] += 1
        if calls["runs"] == 1:
            return False, "ModuleNotFoundError: No module named 'httpx'"
        return True, "1 passed"

    def fake_pip(pkg, repo_path):
        calls["installed"].append(pkg)
        return True

    monkeypatch.setattr(cs, "_run", fake_run)
    monkeypatch.setattr(cs, "_pip_install", fake_pip)
    monkeypatch.setattr(cs, "SANDBOX_AUTO_INSTALL", True)

    ok, out = cs._run_tests_autoinstall(["pytest"], str(tmp_path), env=None)
    assert ok is True
    assert "httpx" in calls["installed"]
    # httpx quedó registrado en requirements.txt
    assert "httpx" in (tmp_path / "requirements.txt").read_text(encoding="utf-8")


def test_autoinstall_disabled_no_install(tmp_path, monkeypatch):
    def fake_run(cmd, cwd, timeout=120, env=None):
        return False, "No module named 'httpx'"
    installed = []
    monkeypatch.setattr(cs, "_run", fake_run)
    monkeypatch.setattr(cs, "_pip_install", lambda p, r: installed.append(p) or True)
    monkeypatch.setattr(cs, "SANDBOX_AUTO_INSTALL", False)
    ok, out = cs._run_tests_autoinstall(["pytest"], str(tmp_path), env=None)
    assert ok is False
    assert installed == []


def test_autoinstall_stops_when_no_progress(tmp_path, monkeypatch):
    """Si la instalación falla, no hace loop infinito."""
    (tmp_path / "requirements.txt").write_text("fastapi\n", encoding="utf-8")
    runs = {"n": 0}

    def fake_run(cmd, cwd, timeout=120, env=None):
        runs["n"] += 1
        return False, "No module named 'brokenpkg'"

    monkeypatch.setattr(cs, "_run", fake_run)
    monkeypatch.setattr(cs, "_pip_install", lambda p, r: False)  # instalación siempre falla
    monkeypatch.setattr(cs, "SANDBOX_AUTO_INSTALL", True)
    ok, out = cs._run_tests_autoinstall(["pytest"], str(tmp_path), env=None)
    assert ok is False
    assert runs["n"] <= 2   # run inicial + (sin progreso → corta)
