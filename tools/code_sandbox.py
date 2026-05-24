"""
Sandbox de ejecución de código.

Corre tests reales, linting y type-checking en el repositorio destino.
Auto-detecta herramientas disponibles.
Si no hay herramientas instaladas, reporta warning pero NO falla el pipeline.
"""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path


def _has(tool: str) -> bool:
    return shutil.which(tool) is not None


def _run(cmd: list[str], cwd: str, timeout: int = 120) -> tuple[bool, str]:
    try:
        r = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout)
        return r.returncode == 0, (r.stdout + r.stderr).strip()
    except subprocess.TimeoutExpired:
        return False, f"Timeout ({timeout}s): {' '.join(cmd)}"
    except FileNotFoundError:
        return False, f"Herramienta no encontrada: {cmd[0]}"
    except Exception as e:
        return False, str(e)


def _has_pkg(repo: Path, pkg: str) -> bool:
    pj = repo / "package.json"
    if not pj.exists():
        return False
    try:
        data = json.loads(pj.read_text())
        return pkg in {**data.get("dependencies", {}), **data.get("devDependencies", {})}
    except Exception:
        return False


def _has_tests(repo: Path, ext: str) -> bool:
    for d in ("tests", "test", "spec"):
        if (repo / d).is_dir() and any((repo / d).glob(f"*.{ext}")):
            return True
    return bool(next(repo.rglob(f"test_*.{ext}"), None))


def _maybe_install_deps(repo_path: str) -> None:
    """
    Intenta instalar las dependencias del repo destino en modo silencioso.
    Solo actúa si hay requirements.txt o package.json. Falla silenciosamente.
    C-04: valida que repo_path sea subdirectorio real de WORKSPACES_ROOT.
    """
    import os as _os, logging as _log
    _logger = _log.getLogger(__name__)
    try:
        resolved = Path(repo_path).resolve()
        ws_root  = Path(_os.getenv("WORKSPACES_ROOT", "/workspace")).resolve()
        resolved.relative_to(ws_root)   # ValueError si no es subdirectorio
    except ValueError:
        _logger.warning("Sandbox: repo_path '%s' fuera de WORKSPACES_ROOT — instalación omitida", repo_path)
        return
    except Exception:
        return

    p = Path(repo_path)
    req = p / "requirements.txt"
    pkg = p / "package.json"
    if req.exists():
        _run(["pip", "install", "-r", str(req), "-q", "--no-warn-script-location"],
             repo_path, timeout=90)
    if pkg.exists() and not (p / "node_modules").exists():
        # C-04: --ignore-scripts evita postinstall maliciosos en repos destino
        _run(["npm", "install", "--silent", "--legacy-peer-deps", "--ignore-scripts"],
             repo_path, timeout=120)


def _detect_stack(repo_path: str) -> dict:
    p = Path(repo_path)
    return {
        "python":     any((p / f).exists() for f in ["requirements.txt", "pyproject.toml", "setup.py"]),
        "django":     (p / "manage.py").exists(),
        "node":       (p / "package.json").exists(),
        "typescript": (p / "tsconfig.json").exists(),
        "has_pytest": _has_tests(p, "py"),
        "has_jest":   _has_pkg(p, "jest") or _has_pkg(p, "vitest"),
    }


def _check_pytest(repo_path: str, stack: dict) -> dict:
    r = {"tool": "pytest", "passed": None, "output": "", "skipped": False}
    if not stack["python"]:
        return {**r, "skipped": True, "output": "No es proyecto Python."}
    if not _has("pytest"):
        return {**r, "skipped": True, "output": "pytest no instalado."}
    if not stack["has_pytest"]:
        return {**r, "skipped": True, "output": "Sin tests pytest detectados."}
    cmd = (["python", "manage.py", "test", "--verbosity=1"]
           if stack["django"] else ["pytest", "--tb=short", "-q", "--no-header"])
    ok, out = _run(cmd, repo_path)
    return {**r, "passed": ok, "output": out[:3000]}


def _check_jest(repo_path: str, stack: dict) -> dict:
    r = {"tool": "jest/vitest", "passed": None, "output": "", "skipped": False}
    if not stack["node"] or not stack["has_jest"]:
        return {**r, "skipped": True, "output": "Sin jest/vitest."}
    is_vitest = _has_pkg(Path(repo_path), "vitest")
    cmd = (["npx", "vitest", "run"] if is_vitest
           else ["npx", "jest", "--passWithNoTests"])
    ok, out = _run(cmd, repo_path, timeout=180)
    return {**r, "tool": "vitest" if is_vitest else "jest", "passed": ok, "output": out[:3000]}


def _check_lint_py(repo_path: str, stack: dict) -> dict:
    r = {"tool": "lint-py", "passed": None, "output": "", "skipped": False}
    if not stack["python"]:
        return {**r, "skipped": True}
    if _has("ruff"):
        ok, out = _run(
            ["ruff", "check", ".", "--select=E,W,F",
             "--exclude=migrations,node_modules,dist,build,__pycache__,.venv,venv"],
            repo_path,
        )
        return {**r, "tool": "ruff", "passed": ok, "output": out[:2000]}
    if _has("flake8"):
        ok, out = _run(["flake8", ".", "--max-line-length=120", "--count"], repo_path)
        return {**r, "tool": "flake8", "passed": ok, "output": out[:2000]}
    return {**r, "skipped": True, "output": "Ningun linter Python (flake8/ruff)."}


def _check_mypy(repo_path: str, stack: dict) -> dict:
    r = {"tool": "mypy", "passed": None, "output": "", "skipped": False}
    if not stack["python"] or not _has("mypy"):
        return {**r, "skipped": True, "output": "mypy no instalado."}
    ok, out = _run(["mypy", ".", "--ignore-missing-imports", "--no-error-summary"], repo_path)
    return {**r, "passed": ok, "output": out[:2000]}


def _check_tsc(repo_path: str, stack: dict) -> dict:
    r = {"tool": "tsc", "passed": None, "output": "", "skipped": False}
    if not stack["typescript"]:
        return {**r, "skipped": True, "output": "Sin tsconfig.json."}
    ok, out = _run(["npx", "tsc", "--noEmit"], repo_path, timeout=60)
    return {**r, "passed": ok, "output": out[:2000]}


def _check_migrations(repo_path: str, stack: dict) -> dict:
    """IV-1: verifica que no haya migraciones pendientes sin aplicar."""
    r = {"tool": "migrate-check", "passed": None, "output": "", "skipped": False, "layer": "backend"}
    if not stack["django"]:
        return {**r, "skipped": True, "output": "No es proyecto Django."}
    ok, out = _run(["python", "manage.py", "migrate", "--check"], repo_path, timeout=30)
    return {**r, "passed": ok, "output": out[:1500]}


def _check_coverage(repo_path: str, stack: dict, min_pct: int = 70) -> dict:
    """IV-1: cobertura mínima de tests backend."""
    r = {"tool": "coverage", "passed": None, "output": "", "skipped": False, "layer": "backend"}
    if not stack["python"] or not stack["has_pytest"]:
        return {**r, "skipped": True, "output": "Sin tests pytest."}
    if not _has("pytest"):
        return {**r, "skipped": True, "output": "pytest no instalado."}
    ok, out = _run(
        ["pytest", "--cov=.", f"--cov-fail-under={min_pct}", "--cov-report=term-missing",
         "--tb=no", "-q", "--no-header"],
        repo_path, timeout=120,
    )
    return {**r, "passed": ok, "output": out[:2000]}


def _check_npm_build(repo_path: str, stack: dict) -> dict:
    """IV-1: build de producción del frontend — gate duro."""
    r = {"tool": "npm-build", "passed": None, "output": "", "skipped": False, "layer": "frontend"}
    if not stack["node"]:
        return {**r, "skipped": True, "output": "Sin package.json."}
    pkg_scripts = {}
    try:
        pkg_scripts = json.loads((Path(repo_path) / "package.json").read_text()).get("scripts", {})
    except Exception:
        pass
    if "build" not in pkg_scripts:
        return {**r, "skipped": True, "output": "Sin script 'build' en package.json."}
    ok, out = _run(["npm", "run", "build"], repo_path, timeout=180)
    return {**r, "passed": ok, "output": out[:3000]}


def _check_eslint(repo_path: str, stack: dict) -> dict:
    """IV-1: linting TypeScript/JavaScript sin warnings."""
    r = {"tool": "eslint", "passed": None, "output": "", "skipped": False, "layer": "frontend"}
    if not stack["node"]:
        return {**r, "skipped": True, "output": "Sin package.json."}
    eslint_cfg = any(
        (Path(repo_path) / f).exists()
        for f in [".eslintrc.json", ".eslintrc.js", ".eslintrc.cjs",
                  ".eslintrc.yaml", ".eslintrc.yml", "eslint.config.js",
                  "eslint.config.mjs", "eslint.config.cjs"]
    )
    if not eslint_cfg:
        return {**r, "skipped": True, "output": "Sin configuracion ESLint."}
    ext = ".ts,.tsx,.js,.jsx" if stack["typescript"] else ".js,.jsx"
    ok, out = _run(
        ["npx", "eslint", ".", "--max-warnings", "0", "--ext", ext,
         "--ignore-path", ".gitignore"],
        repo_path, timeout=60,
    )
    return {**r, "passed": ok, "output": out[:2000]}


def run_all_checks(repo_path: str, install_deps: bool = True) -> dict:
    """
    Ejecuta todos los gates de calidad en orden. Retorna dict con resultados,
    resumen legible y lista estructurada de fallos para A6 Refactor.

    Gates duros (IV-1): tsc, npm-build bloquean aunque no haya otras herramientas.
    Si no hay herramientas disponibles en absoluto → passed=True (no bloquear).
    """
    if install_deps:
        _maybe_install_deps(repo_path)

    stack = _detect_stack(repo_path)

    # Orden: backend primero, luego frontend (gate duro)
    checks = {
        "python_tests":  _check_pytest(repo_path, stack),
        "python_cover":  _check_coverage(repo_path, stack),
        "python_migr":   _check_migrations(repo_path, stack),
        "python_type":   _check_mypy(repo_path, stack),
        "python_lint":   _check_lint_py(repo_path, stack),
        "js_type":       _check_tsc(repo_path, stack),       # gate duro
        "js_build":      _check_npm_build(repo_path, stack), # gate duro
        "js_tests":      _check_jest(repo_path, stack),
        "js_lint":       _check_eslint(repo_path, stack),
    }

    executed   = [r for r in checks.values() if not r["skipped"] and r["passed"] is not None]
    all_passed = all(r["passed"] for r in executed)
    any_exec   = bool(executed)

    # Gates duros: tsc y npm-build fallan aunque no haya nada más ejecutado
    hard_gates = ["tsc", "npm-build"]
    for r in checks.values():
        if r["tool"] in hard_gates and not r["skipped"] and r["passed"] is False:
            all_passed = False

    lines = ["## SANDBOX — Resultados de ejecucion real\n"]
    for r in checks.values():
        if r["skipped"]:
            lines.append(f"[SKIP] {r['tool']}: omitido")
        else:
            icon = "[OK]" if r["passed"] else "[FAIL]"
            hard = " ⛔ GATE DURO" if r["tool"] in hard_gates and not r["passed"] else ""
            lines.append(f"{icon} {r['tool']}: {'PASSED' if r['passed'] else 'FAILED'}{hard}")
            if not r["passed"]:
                lines.append(f"```\n{r['output'][:800]}\n```")

    if not any_exec:
        lines += [
            "\nAVISO: No se ejecuto ningun check (herramientas no instaladas).",
            "El codigo fue revisado por A6, A7 y A8. Pipeline continua.",
        ]
        all_passed = True

    # Fallos estructurados por gate — para A6 Refactor (IV-1)
    gate_failures = [
        {
            "gate":  r["tool"],
            "layer": r.get("layer", "backend"),
            "stderr": r["output"][:2000],
            "hard":  r["tool"] in hard_gates,
        }
        for r in checks.values()
        if not r["skipped"] and r["passed"] is False
    ]

    return {
        "passed":       all_passed,
        "any_executed": any_exec,
        "results":      checks,
        "summary":      "\n".join(lines),
        "gate_failures": gate_failures,
    }


def format_failures_for_agent(result: dict) -> str:
    """
    Formatea fallos del sandbox para que A6 Refactor haga corrección quirúrgica.
    IV-1: cada gate tiene su stderr específico y capa (backend/frontend).
    """
    gate_failures = result.get("gate_failures", [])
    if not gate_failures:
        return ""

    lines = [
        "## FALLOS DETECTADOS POR SANDBOX — corrección quirúrgica requerida\n",
        "Cada gate falló con el error REAL de ejecución. Corrige exactamente lo que indica.\n",
    ]
    for gf in gate_failures:
        hard_tag = " ⛔ GATE DURO (bloquea el PR)" if gf.get("hard") else ""
        lines.append(f"\n### Gate `{gf['gate']}` · capa: {gf['layer']}{hard_tag}")
        lines.append(f"```\n{gf['stderr']}\n```")

    return "\n".join(lines)
