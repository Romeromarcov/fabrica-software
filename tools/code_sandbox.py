"""
Sandbox de ejecución de código.

Corre tests reales, linting, type-checking y gates de seguridad en el repositorio destino.
Auto-detecta herramientas disponibles.

ENDURECIMIENTO (Fase 1 del PLAN_HARDENING_FABRICA):
  • F1.1 — Sin soft-fail silencioso: si el stack del repo DECLARA una capacidad
    (Django, TypeScript, tests) y la herramienta requerida está ausente, el gate
    **FALLA** en lugar de saltarse (cuando STRICT_GATES=true, por defecto).
    Se distingue un skip legítimo (N/A: el stack no aplica) de un skip peligroso
    (tool_missing: el stack aplica pero falta la herramienta).
  • F1.2 — Gate de aislamiento multi-tenant (R-CODE-1): detecta ViewSets/Views que
    exponen `queryset = Model.objects.all()` sin `get_queryset` ni base tenant-aware,
    y corre los tests de aislamiento si existen. Gate DURO.
  • F1.3 — Gate de drift de migraciones: `makemigrations --check --dry-run`. Gate DURO.
"""
from __future__ import annotations

import ast
import json
import os
import shutil
import subprocess
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

# ── Banderas de endurecimiento (espejo en config.py / INVENTARIO_FLAGS.md) ─────
# Se leen de entorno para que code_sandbox sea importable sin acoplar a config.py.
STRICT_GATES = os.getenv("STRICT_GATES", "true").lower() == "true"
# TENANT_ISOLATION_GATE: "auto" (activo si el repo es Django y usa id_empresa),
# "true" (forzar), "false" (desactivar).
TENANT_ISOLATION_GATE = os.getenv("TENANT_ISOLATION_GATE", "auto").lower()

# Gates DUROS: bloquean el PR aunque sean el único gate ejecutado.
HARD_GATES = {"tsc", "npm-build", "migrate-check", "makemigrations-check", "tenant-isolation"}

# Bases de DRF que NO garantizan aislamiento por sí solas (heredar de ellas y
# exponer un queryset sin get_queryset es la firma del bug CRIT-1..3).
_DRF_VIEW_BASES = (
    "ViewSet", "ModelViewSet", "ReadOnlyModelViewSet", "GenericViewSet",
    "APIView", "GenericAPIView",
    "ListAPIView", "RetrieveAPIView", "ListCreateAPIView",
    "RetrieveUpdateAPIView", "RetrieveUpdateDestroyAPIView", "RetrieveDestroyAPIView",
    "ListView", "DetailView",
)
# Bases propias del proyecto que SÍ aplican filtro de tenant (convención §7.1 del plan).
# Heredar de una de estas exime del hallazgo.
_TENANT_SAFE_BASES = {
    "BaseModelViewSet", "TenantModelViewSet", "TenantViewSet",
    "EmpresaScopedViewSet", "BaseTenantViewSet",
}


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
    try:
        resolved = Path(repo_path).resolve()
        ws_root  = Path(os.getenv("WORKSPACES_ROOT", "/workspace")).resolve()
        resolved.relative_to(ws_root)   # ValueError si no es subdirectorio
    except ValueError:
        logger.warning("Sandbox: repo_path '%s' fuera de WORKSPACES_ROOT — instalación omitida", repo_path)
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


# ── Helpers de skip tipado (F1.1) ──────────────────────────────────────────────
# skip_reason ∈ {"n/a", "tool_missing", "no_tests", "no_config", "no_build_script", "disabled"}

def _skip(gate: str, reason: str, msg: str, layer: str = "backend") -> dict:
    return {"tool": gate, "gate": gate, "passed": None, "output": msg,
            "skipped": True, "skip_reason": reason, "layer": layer}


def _result(gate: str, tool: str, passed: bool, output: str, layer: str = "backend") -> dict:
    return {"tool": tool, "gate": gate, "passed": passed, "output": output,
            "skipped": False, "skip_reason": None, "layer": layer}


def _check_pytest(repo_path: str, stack: dict) -> dict:
    gate = "pytest"
    if not stack["python"]:
        return _skip(gate, "n/a", "No es proyecto Python.")
    if not stack["has_pytest"]:
        return _skip(gate, "no_tests", "Sin tests pytest detectados.")
    if not stack["django"] and not _has("pytest"):
        return _skip(gate, "tool_missing", "pytest no instalado.")
    cmd = (["python", "manage.py", "test", "--verbosity=1"]
           if stack["django"] else ["pytest", "--tb=short", "-q", "--no-header"])
    ok, out = _run(cmd, repo_path)
    return _result(gate, "pytest", ok, out[:3000])


def _check_jest(repo_path: str, stack: dict) -> dict:
    gate = "js-tests"
    if not stack["node"]:
        return _skip(gate, "n/a", "No es proyecto Node.", layer="frontend")
    if not stack["has_jest"]:
        return _skip(gate, "no_tests", "Sin jest/vitest declarado.", layer="frontend")
    if not _has("npx"):
        return _skip(gate, "tool_missing", "npx no disponible para correr tests JS.", layer="frontend")
    is_vitest = _has_pkg(Path(repo_path), "vitest")
    cmd = (["npx", "vitest", "run"] if is_vitest
           else ["npx", "jest", "--passWithNoTests"])
    ok, out = _run(cmd, repo_path, timeout=180)
    return _result(gate, "vitest" if is_vitest else "jest", ok, out[:3000], layer="frontend")


def _check_lint_py(repo_path: str, stack: dict) -> dict:
    gate = "lint-py"
    if not stack["python"]:
        return _skip(gate, "n/a", "No es proyecto Python.")
    if _has("ruff"):
        ok, out = _run(
            ["ruff", "check", ".", "--select=E,W,F",
             "--exclude=migrations,node_modules,dist,build,__pycache__,.venv,venv"],
            repo_path,
        )
        return _result(gate, "ruff", ok, out[:2000])
    if _has("flake8"):
        ok, out = _run(["flake8", ".", "--max-line-length=120", "--count"], repo_path)
        return _result(gate, "flake8", ok, out[:2000])
    return _skip(gate, "tool_missing", "Ningun linter Python (flake8/ruff).")


def _check_mypy(repo_path: str, stack: dict) -> dict:
    gate = "mypy"
    if not stack["python"]:
        return _skip(gate, "n/a", "No es proyecto Python.")
    if not _has("mypy"):
        return _skip(gate, "tool_missing", "mypy no instalado.")
    ok, out = _run(["mypy", ".", "--ignore-missing-imports", "--no-error-summary"], repo_path)
    return _result(gate, "mypy", ok, out[:2000])


def _check_tsc(repo_path: str, stack: dict) -> dict:
    gate = "tsc"
    if not stack["typescript"]:
        return _skip(gate, "n/a", "Sin tsconfig.json.", layer="frontend")
    if not _has("npx"):
        return _skip(gate, "tool_missing", "npx no disponible para tsc.", layer="frontend")
    ok, out = _run(["npx", "tsc", "--noEmit"], repo_path, timeout=60)
    return _result(gate, "tsc", ok, out[:2000], layer="frontend")


def _check_migrations(repo_path: str, stack: dict) -> dict:
    """Verifica que no haya migraciones sin aplicar (migrate --check)."""
    gate = "migrate-check"
    if not stack["django"]:
        return _skip(gate, "n/a", "No es proyecto Django.")
    ok, out = _run(["python", "manage.py", "migrate", "--check"], repo_path, timeout=30)
    return _result(gate, "migrate-check", ok, out[:1500])


def _check_makemigrations(repo_path: str, stack: dict) -> dict:
    """F1.3: drift de migraciones — modelos cambiados sin migración generada.

    Espejo del CI de OmniERP (`makemigrations --check --dry-run`). Gate DURO.
    """
    gate = "makemigrations-check"
    if not stack["django"]:
        return _skip(gate, "n/a", "No es proyecto Django.")
    ok, out = _run(["python", "manage.py", "makemigrations", "--check", "--dry-run"],
                   repo_path, timeout=60)
    return _result(gate, "makemigrations-check", ok, out[:1500])


def _check_coverage(repo_path: str, stack: dict, min_pct: int = 70) -> dict:
    """Cobertura mínima de tests backend."""
    gate = "coverage"
    if not stack["python"] or not stack["has_pytest"]:
        return _skip(gate, "no_tests", "Sin tests pytest.")
    if not _has("pytest"):
        return _skip(gate, "tool_missing", "pytest no instalado.")
    ok, out = _run(
        ["pytest", "--cov=.", f"--cov-fail-under={min_pct}", "--cov-report=term-missing",
         "--tb=no", "-q", "--no-header"],
        repo_path, timeout=120,
    )
    return _result(gate, "coverage", ok, out[:2000])


def _check_npm_build(repo_path: str, stack: dict) -> dict:
    """Build de producción del frontend — gate duro."""
    gate = "npm-build"
    if not stack["node"]:
        return _skip(gate, "n/a", "Sin package.json.", layer="frontend")
    pkg_scripts = {}
    try:
        pkg_scripts = json.loads((Path(repo_path) / "package.json").read_text()).get("scripts", {})
    except Exception:
        pass
    if "build" not in pkg_scripts:
        return _skip(gate, "no_build_script", "Sin script 'build' en package.json.", layer="frontend")
    if not _has("npm"):
        return _skip(gate, "tool_missing", "npm no disponible.", layer="frontend")
    ok, out = _run(["npm", "run", "build"], repo_path, timeout=180)
    return _result(gate, "npm-build", ok, out[:3000], layer="frontend")


def _check_eslint(repo_path: str, stack: dict) -> dict:
    """Linting TypeScript/JavaScript sin warnings."""
    gate = "eslint"
    if not stack["node"]:
        return _skip(gate, "n/a", "Sin package.json.", layer="frontend")
    eslint_cfg = any(
        (Path(repo_path) / f).exists()
        for f in [".eslintrc.json", ".eslintrc.js", ".eslintrc.cjs",
                  ".eslintrc.yaml", ".eslintrc.yml", "eslint.config.js",
                  "eslint.config.mjs", "eslint.config.cjs"]
    )
    if not eslint_cfg:
        return _skip(gate, "no_config", "Sin configuracion ESLint.", layer="frontend")
    if not _has("npx"):
        return _skip(gate, "tool_missing", "npx no disponible para eslint.", layer="frontend")
    ext = ".ts,.tsx,.js,.jsx" if stack["typescript"] else ".js,.jsx"
    ok, out = _run(
        ["npx", "eslint", ".", "--max-warnings", "0", "--ext", ext,
         "--ignore-path", ".gitignore"],
        repo_path, timeout=60,
    )
    return _result(gate, "eslint", ok, out[:2000], layer="frontend")


# ── F1.2 — Gate de aislamiento multi-tenant ────────────────────────────────────

def _iter_view_files(repo_path: str, cap: int = 400):
    """Itera archivos de vistas Django/DRF (views.py o paquetes views/), con tope."""
    p = Path(repo_path)
    seen = 0
    for f in p.rglob("*.py"):
        parts = {x.lower() for x in f.parts}
        name = f.name.lower()
        if "node_modules" in parts or ".venv" in parts or "venv" in parts or "migrations" in parts:
            continue
        if name == "views.py" or "views" in parts or name.startswith("view"):
            yield f
            seen += 1
            if seen >= cap:
                return


def _repo_uses_tenant(repo_path: str, cap: int = 300) -> bool:
    """Heurística: ¿el repo modela multi-tenancy por id_empresa/empresa?"""
    p = Path(repo_path)
    seen = 0
    for f in p.rglob("models.py"):
        parts = {x.lower() for x in f.parts}
        if "node_modules" in parts or ".venv" in parts:
            continue
        try:
            txt = f.read_text(encoding="utf-8", errors="ignore")
        except Exception:
            continue
        if "id_empresa" in txt or "empresa" in txt:
            return True
        seen += 1
        if seen >= cap:
            break
    return False


def _tenant_isolation_enabled(repo_path: str, stack: dict) -> bool:
    if TENANT_ISOLATION_GATE == "true":
        return True
    if TENANT_ISOLATION_GATE == "false":
        return False
    # auto
    if not stack["django"]:
        return False
    return _repo_uses_tenant(repo_path)


def _base_name(node: ast.expr) -> str:
    if isinstance(node, ast.Name):
        return node.id
    if isinstance(node, ast.Attribute):
        return node.attr
    return ""


def _assign_is_objects_all(node: ast.Assign) -> bool:
    """Detecta `queryset = <Model>.objects.all()` (o `.objects` sin filtro)."""
    for t in node.targets:
        if isinstance(t, ast.Name) and t.id == "queryset":
            v = node.value
            # ...objects.all()
            if isinstance(v, ast.Call) and isinstance(v.func, ast.Attribute) and v.func.attr == "all":
                inner = v.func.value
                if isinstance(inner, ast.Attribute) and inner.attr == "objects":
                    return True
            # ...objects  (asignación directa del manager, también sin filtro)
            if isinstance(v, ast.Attribute) and v.attr == "objects":
                return True
    return False


def scan_unfiltered_views(repo_path: str) -> list[dict]:
    """Encuentra Views/ViewSets DRF con queryset sin filtro de tenant ni get_queryset.

    Firma del bug CRIT-1..3: hereda de una base DRF (no de una base tenant-aware del
    proyecto), define `queryset = Model.objects.all()` y NO sobreescribe get_queryset.
    """
    findings: list[dict] = []
    for f in _iter_view_files(repo_path):
        try:
            tree = ast.parse(f.read_text(encoding="utf-8", errors="ignore"))
        except Exception:
            continue
        for node in ast.walk(tree):
            if not isinstance(node, ast.ClassDef):
                continue
            bases = [_base_name(b) for b in node.bases]
            if not any(b.endswith(_DRF_VIEW_BASES) for b in bases):
                continue
            if any(b in _TENANT_SAFE_BASES for b in bases):
                continue  # base tenant-aware del proyecto → exenta
            has_get_qs = any(
                isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)) and n.name == "get_queryset"
                for n in node.body
            )
            if has_get_qs:
                continue
            for n in node.body:
                if isinstance(n, ast.Assign) and _assign_is_objects_all(n):
                    findings.append({
                        "file": str(f),
                        "class": node.name,
                        "line": n.lineno,
                        "bases": bases,
                    })
                    break
    return findings


def _check_tenant_isolation(repo_path: str, stack: dict) -> dict:
    """F1.2: gate DURO de aislamiento multi-tenant (R-CODE-1).

    (a) Escaneo estático AST: Views con queryset sin filtro de tenant.
    (b) Corre tests de aislamiento si existen (`-k isolation` / `aislamiento`).
    """
    gate = "tenant-isolation"
    if not _tenant_isolation_enabled(repo_path, stack):
        return _skip(gate, "n/a", "Aislamiento no aplica (repo no multi-tenant o gate desactivado).")

    findings = scan_unfiltered_views(repo_path)

    # (b) tests de aislamiento, si existen
    test_note = ""
    test_failed = False
    if stack["django"]:
        ok, out = _run(
            ["python", "manage.py", "test", "--verbosity=1", "--pattern", "*isolation*"],
            repo_path, timeout=120,
        )
        # manage.py test no falla si no encuentra tests con ese patrón; lo tratamos como informativo
        if "Ran 0 tests" not in out and not ok:
            test_failed = True
            test_note = f"\nTests de aislamiento FALLARON:\n{out[:800]}"
        elif "Ran 0 tests" in out:
            test_note = "\n(No se hallaron tests *isolation*; recomendado añadir por PR — R-CODE-1)."

    passed = (len(findings) == 0) and (not test_failed)

    if findings:
        lines = [f"{len(findings)} View(s) sin filtro de tenant (posible fuga cross-tenant):"]
        for fd in findings[:20]:
            rel = fd["file"]
            lines.append(f"  - {rel}:{fd['line']} · clase {fd['class']} (bases: {', '.join(fd['bases'])})")
        out = "\n".join(lines) + test_note
    else:
        out = "Sin Views con queryset sin filtro de tenant." + test_note

    return _result(gate, "tenant-isolation", passed, out)


# ── Política de gates requeridos por stack (F1.1) ──────────────────────────────

def _required_gates(repo_path: str, stack: dict) -> set[str]:
    """Gates que el stack del repo OBLIGA a ejecutar.

    Si uno de estos se salta por `tool_missing` (y STRICT_GATES), se convierte en FAIL.
    """
    req: set[str] = set()
    if stack["python"] and stack["has_pytest"]:
        req.add("pytest")
    if stack["django"]:
        req |= {"migrate-check", "makemigrations-check"}
        if _tenant_isolation_enabled(repo_path, stack):
            req.add("tenant-isolation")
    if stack["typescript"]:
        req.add("tsc")
    if stack["node"] and stack["has_jest"]:
        req.add("js-tests")
    return req


def run_all_checks(repo_path: str, install_deps: bool = True) -> dict:
    """
    Ejecuta todos los gates de calidad y seguridad. Retorna dict con resultados,
    resumen legible y lista estructurada de fallos para A6 Refactor.

    ENDURECIDO (F1.1): un gate REQUERIDO por el stack que no pueda ejecutarse por
    herramienta ausente cuenta como FALLO (no como skip), si STRICT_GATES=true.
    Ya NO existe el atajo "sin herramientas → passed=True".
    """
    if install_deps:
        _maybe_install_deps(repo_path)

    stack    = _detect_stack(repo_path)
    required = _required_gates(repo_path, stack)

    # Orden: backend primero, luego frontend.
    checks = {
        "python_tests":  _check_pytest(repo_path, stack),
        "python_cover":  _check_coverage(repo_path, stack),
        "python_migr":   _check_migrations(repo_path, stack),
        "python_mkmigr": _check_makemigrations(repo_path, stack),   # F1.3
        "python_type":   _check_mypy(repo_path, stack),
        "python_lint":   _check_lint_py(repo_path, stack),
        "tenant_iso":    _check_tenant_isolation(repo_path, stack),  # F1.2
        "js_type":       _check_tsc(repo_path, stack),
        "js_build":      _check_npm_build(repo_path, stack),
        "js_tests":      _check_jest(repo_path, stack),
        "js_lint":       _check_eslint(repo_path, stack),
    }

    # F1.1 — convertir skip por tool_missing de un gate REQUERIDO en FALLO.
    missing_required: list[str] = []
    if STRICT_GATES:
        for r in checks.values():
            if (r["skipped"] and r.get("skip_reason") == "tool_missing"
                    and r["gate"] in required):
                missing_required.append(r["gate"])
                r["skipped"]     = False
                r["passed"]      = False
                r["skip_reason"] = None
                r["output"]      = (f"GATE REQUERIDO por el stack pero la herramienta no está "
                                    f"disponible — FALLA (STRICT_GATES). {r['output']}")

    executed = [r for r in checks.values() if not r["skipped"] and r["passed"] is not None]

    # Un gate ejecutado que falló, o cualquier gate duro fallado, bloquea.
    all_passed = all(r["passed"] for r in executed) if executed else True
    for r in checks.values():
        if r["gate"] in HARD_GATES and not r["skipped"] and r["passed"] is False:
            all_passed = False
    if missing_required:
        all_passed = False

    lines = ["## SANDBOX — Resultados de ejecucion real\n"]
    for r in checks.values():
        if r["skipped"]:
            lines.append(f"[SKIP] {r['gate']}: {r['output']} (motivo: {r.get('skip_reason')})")
        else:
            icon = "[OK]" if r["passed"] else "[FAIL]"
            hard = " ⛔ GATE DURO" if r["gate"] in HARD_GATES and not r["passed"] else ""
            lines.append(f"{icon} {r['gate']}: {'PASSED' if r['passed'] else 'FAILED'}{hard}")
            if not r["passed"]:
                lines.append(f"```\n{r['output'][:800]}\n```")

    # F1.1 — sin gates ejecutados: solo es OK si TODOS los skips fueron N/A legítimos.
    if not executed:
        if required:
            lines.append(
                f"\n⛔ El stack requiere {sorted(required)} pero ningún gate pudo ejecutarse. "
                f"FALLA (no se asume verde sin verificación)."
            )
            all_passed = False
        else:
            lines.append(
                "\nAVISO: el stack no requiere gates ejecutables (repo sin Python/Node "
                "verificables). Continúa, pero el código depende de A6/A7/A8/A8.5."
            )

    if missing_required:
        lines.append(f"\n⛔ Gates requeridos sin herramienta disponible: {sorted(set(missing_required))}")

    # Fallos estructurados por gate — para A6 Refactor.
    gate_failures = [
        {
            "gate":   r["gate"],
            "layer":  r.get("layer", "backend"),
            "stderr": r["output"][:2000],
            "hard":   r["gate"] in HARD_GATES,
        }
        for r in checks.values()
        if not r["skipped"] and r["passed"] is False
    ]

    return {
        "passed":        all_passed,
        "any_executed":  bool(executed),
        "required_gates": sorted(required),
        "missing_required": sorted(set(missing_required)),
        "results":       checks,
        "summary":       "\n".join(lines),
        "gate_failures": gate_failures,
    }


def format_failures_for_agent(result: dict) -> str:
    """
    Formatea fallos del sandbox para que A6 Refactor haga corrección quirúrgica.
    Cada gate tiene su stderr específico y capa (backend/frontend).
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
