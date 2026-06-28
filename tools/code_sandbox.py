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
import re
import shutil
import subprocess
import sys
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
HARD_GATES = {"tsc", "npm-build", "migrate-check", "makemigrations-check",
              "tenant-isolation", "secret-scan", "test-quality"}

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


def _has_pytest() -> bool:
    """True si pytest es ejecutable, sea como CLI en PATH o como módulo (`python -m pytest`).
    En muchos entornos (Windows Store Python, venvs sin Scripts en PATH) el binario `pytest`
    no está en PATH pero el módulo sí — exigir el CLI hacía que el gate REQUERIDO fallara por
    STRICT_GATES aunque pytest estuviese instalado."""
    if _has("pytest"):
        return True
    try:
        import importlib.util
        return importlib.util.find_spec("pytest") is not None
    except Exception as exc:
        logger.debug("_has_pytest: find_spec falló (%s)", exc)
        return False


def _pytest_base() -> list[str]:
    """Comando base para invocar pytest, prefiriendo el CLI si está en PATH y cayendo a
    `python -m pytest` (mismo intérprete que corre la fábrica)."""
    if _has("pytest"):
        return ["pytest"]
    return [sys.executable, "-m", "pytest"]


def _run(cmd: list[str], cwd: str, timeout: int = 120,
         env: dict | None = None) -> tuple[bool, str]:
    try:
        merged_env = {**os.environ, **(env or {})}
        r = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True,
                           timeout=timeout, env=merged_env)
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


def _pytest_env(repo_path: str, stack: dict) -> dict:
    """
    F6 — PYTHONPATH para que pytest importe el código del repo cuando vive en un subdir
    (p. ej. `backend/main.py` con imports planos `from main import ...`). Django gestiona
    su propio path vía manage.py, así que solo aplica al runner pytest puro.
    """
    if stack.get("django"):
        return {}
    try:
        from tools.repo_scanner import detect_pythonpath_roots
        roots = detect_pythonpath_roots(repo_path)
    except Exception as exc:
        logger.debug("_pytest_env: detect_pythonpath_roots falló (%s)", exc)
        roots = [repo_path]
    if not roots:
        return {}
    existing = os.environ.get("PYTHONPATH", "")
    parts = roots + ([existing] if existing else [])
    return {"PYTHONPATH": os.pathsep.join(parts)}


def _check_pytest(repo_path: str, stack: dict) -> dict:
    gate = "pytest"
    if not stack["python"]:
        return _skip(gate, "n/a", "No es proyecto Python.")
    if not stack["has_pytest"]:
        return _skip(gate, "no_tests", "Sin tests pytest detectados.")
    if not stack["django"] and not _has_pytest():
        return _skip(gate, "tool_missing", "pytest no instalado.")
    cmd = (["python", "manage.py", "test", "--verbosity=1"]
           if stack["django"] else _pytest_base() + ["--tb=short", "-q", "--no-header"])
    ok, out = _run(cmd, repo_path, env=_pytest_env(repo_path, stack))
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
    if not _has_pytest():
        return _skip(gate, "tool_missing", "pytest no instalado.")
    ok, out = _run(
        _pytest_base() + ["--cov=.", f"--cov-fail-under={min_pct}", "--cov-report=term-missing",
         "--tb=no", "-q", "--no-header"],
        repo_path, timeout=120, env=_pytest_env(repo_path, stack),
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


# ── A2.2 — Escáner determinista de secretos (gate DURO) ────────────────────────
# Regexes precompiladas para tokens conocidos + asignación genérica de alta entropía.
# Espejo del scanner de A8 (LLM) pero determinista: un secreto hardcodeado FALLA el
# gate aunque el LLM no lo note.

_SECRET_PATTERNS: list[tuple[str, re.Pattern]] = [
    ("github-pat-classic", re.compile(r"ghp_[A-Za-z0-9]{30,}")),
    ("github-pat-fine",    re.compile(r"github_pat_[A-Za-z0-9_]{20,}")),
    ("github-oauth",       re.compile(r"gh[osur]_[A-Za-z0-9]{30,}")),
    ("anthropic-key",      re.compile(r"sk-ant-[A-Za-z0-9_\-]{16,}")),
    ("openai-key",         re.compile(r"sk-[A-Za-z0-9_\-]{16,}")),
    ("google-api-key",     re.compile(r"AIza[A-Za-z0-9_\-]{30,}")),
    ("telegram-bot-token", re.compile(r"\d{6,}:AA[\w-]{20,}")),
]

# Asignación genérica: api_key/secret/token/password = "<≥12 chars>".
_GENERIC_SECRET = re.compile(
    r"(?i)(api[_-]?key|secret|token|password)\s*[:=]\s*['\"][^'\"]{12,}['\"]"
)

# Marcadores que delatan un placeholder (no un secreto real). Se evalúan sobre la
# línea completa en minúsculas.
_PLACEHOLDER_MARKERS = (
    "os.getenv", "os.environ", "process.env", "getenv", "environ[",
    "...", "xxx", "your-", "your_", "<", "changeme", "change-me", "change_me",
    "example", "placeholder", "dummy", "fake", "todo", "redacted",
    # Placeholders de "cámbiame" en español/inglés (defaults de plantilla, no secretos reales).
    "cambiar", "cambiame", "cambia_", "cambia-", "changeit", "replaceme",
    "replace_me", "replace-me", "default_secret", "tu_clave", "tu_secreto", "tu-clave",
)

# Directorios que nunca se escanean.
_SECRET_SKIP_DIRS = {".git", "node_modules", "__pycache__", ".venv", "venv",
                     "dist", "build", ".mypy_cache", ".pytest_cache"}

# Extensiones binarias comunes a saltar (defensa extra; igual leemos con errors="replace").
_BINARY_EXTS = {
    ".png", ".jpg", ".jpeg", ".gif", ".ico", ".webp", ".svg",
    ".pdf", ".zip", ".gz", ".tar", ".tgz", ".7z", ".rar",
    ".pyc", ".pyo", ".so", ".dylib", ".dll", ".exe", ".bin",
    ".woff", ".woff2", ".ttf", ".eot", ".mp4", ".mp3", ".wav",
    ".lock",
}


def _mask_secret(s: str) -> str:
    """Enmascara un secreto: conserva prefijo corto + ***, nunca el valor completo."""
    s = s.strip()
    if len(s) <= 8:
        return s[:2] + "***"
    return s[:6] + "***"


def _looks_like_placeholder(line: str) -> bool:
    low = line.lower()
    return any(m in low for m in _PLACEHOLDER_MARKERS)


def _iter_scan_files(repo_path: str, cap: int = 2000):
    """Itera archivos de texto candidatos para el escaneo de secretos."""
    p = Path(repo_path)
    seen = 0
    for f in p.rglob("*"):
        if not f.is_file():
            continue
        parts = {x for x in f.parts}
        if _SECRET_SKIP_DIRS & parts:
            continue
        if f.suffix.lower() in _BINARY_EXTS:
            continue
        yield f
        seen += 1
        if seen >= cap:
            return


def scan_secrets(repo_path: str, files: list[str] | None = None) -> list[dict]:
    """Escanea archivos en busca de secretos hardcodeados (determinista).

    Si `files` es None, escanea todos los archivos de texto del repo (saltando
    dirs no-código y binarios). Si se pasa `files`, escanea solo esos (rutas
    relativas a repo_path o absolutas).

    Retorna hallazgos: {"file": rel_path, "line": n, "kind": <pattern>,
    "snippet": <excerpt enmascarado>}. El secreto SIEMPRE va enmascarado.
    """
    root = Path(repo_path)
    findings: list[dict] = []

    if files is not None:
        candidates: list[Path] = []
        for f in files:
            fp = Path(f)
            if not fp.is_absolute():
                fp = root / fp
            if fp.is_file() and fp.suffix.lower() not in _BINARY_EXTS:
                parts = {x for x in fp.parts}
                if not (_SECRET_SKIP_DIRS & parts):
                    candidates.append(fp)
    else:
        candidates = list(_iter_scan_files(repo_path))

    for fp in candidates:
        try:
            text = fp.read_text(encoding="utf-8", errors="replace")
        except (OSError, ValueError):
            continue
        try:
            rel = str(fp.relative_to(root))
        except ValueError:
            rel = str(fp)

        for lineno, line in enumerate(text.splitlines(), start=1):
            if len(line) > 4000:
                line = line[:4000]
            # 1) Tokens conocidos por patrón fijo.
            for kind, pat in _SECRET_PATTERNS:
                m = pat.search(line)
                if m:
                    findings.append({
                        "file": rel,
                        "line": lineno,
                        "kind": kind,
                        "snippet": line.replace(m.group(0), _mask_secret(m.group(0)))[:200],
                    })
                    break  # un hallazgo por línea para los patrones de token
            else:
                # 2) Asignación genérica de alta entropía (solo si no matcheó token).
                gm = _GENERIC_SECRET.search(line)
                if gm and not _looks_like_placeholder(line):
                    # Enmascara el valor entre comillas.
                    val_match = re.search(r"['\"][^'\"]{12,}['\"]", line)
                    masked = line
                    if val_match:
                        raw = val_match.group(0)
                        quote = raw[0]
                        masked = line.replace(raw, quote + _mask_secret(raw[1:-1]) + quote)
                    findings.append({
                        "file": rel,
                        "line": lineno,
                        "kind": "generic-assignment",
                        "snippet": masked[:200],
                    })

    return findings


def _check_secret_scan(repo_path: str, stack: dict, files: list[str] | None = None) -> dict:
    """A2.2: gate DURO determinista de secretos hardcodeados.

    Guardado por config.SECRET_SCAN_GATE (referencia dinámica para que monkeypatch
    funcione). Si está desactivado, se salta como `disabled`.
    """
    gate = "secret-scan"
    import config  # referencia dinámica → monkeypatch-friendly
    if not getattr(config, "SECRET_SCAN_GATE", True):
        return _skip(gate, "disabled", "Escaneo de secretos desactivado (SECRET_SCAN_GATE=false).",
                     layer="security")

    findings = scan_secrets(repo_path, files=files)
    passed = len(findings) == 0

    if findings:
        lines = [f"{len(findings)} secreto(s) hardcodeado(s) detectado(s) (enmascarados):"]
        for fd in findings[:30]:
            lines.append(f"  - {fd['file']}:{fd['line']} · {fd['kind']} · {fd['snippet']}")
        out = "\n".join(lines)
    else:
        out = "Sin secretos hardcodeados detectados."

    return _result(gate, "secret-scan", passed, out, layer="security")


# ── B2.3 — Validación AST de los tests generados (gate DURO) ───────────────────
# AST-parsea los archivos de test y marca tests débiles: sin asserts, con asserts
# triviales (assert True / 1 / "..." / not False) o vacíos (pass / solo docstring).
# Un test trivial generado FALLA el sandbox y enruta de vuelta a A7/A6.

# Sufijos/patrones que identifican un archivo de test Python.
def _is_test_file(rel: str) -> bool:
    """¿La ruta relativa corresponde a un archivo de test Python?"""
    name = Path(rel).name
    if not name.endswith(".py"):
        return False
    parts = {x.lower() for x in Path(rel).parts}
    if name.startswith("test_") or name.endswith("_test.py"):
        return True
    return "tests" in parts


def _assert_is_trivial(node: ast.Assert) -> bool:
    """¿El assert es trivialmente verdadero?  assert True / 1 / "..." / not False."""
    test = node.test
    # assert not False  →  UnaryOp(Not, Constant(False))
    if isinstance(test, ast.UnaryOp) and isinstance(test.op, ast.Not):
        inner = test.operand
        if isinstance(inner, ast.Constant) and not bool(inner.value):
            return True
        return False
    # assert <constante truthy>: True, 1, "texto no vacío", etc.
    if isinstance(test, ast.Constant):
        return bool(test.value)
    return False


def _body_is_empty(body: list[ast.stmt]) -> bool:
    """¿El cuerpo es solo `pass` y/o una docstring (sin lógica real)?"""
    for stmt in body:
        if isinstance(stmt, ast.Pass):
            continue
        # docstring: Expr envolviendo una constante str
        if (isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Constant)
                and isinstance(stmt.value.value, str)):
            continue
        return False
    return True


def scan_trivial_tests(repo_path: str, files: list[str] | None = None) -> list[dict]:
    """Encuentra tests débiles generados (sin asserts / asserts triviales / vacíos).

    AST-parsea los archivos de test entre `files` (filename `test_*.py` / `*_test.py`
    o bajo un directorio `tests/`). Si `files` es None, escanea los archivos de test
    del repo. Solo inspecciona funciones cuyo nombre empieza por `test`.

    Retorna hallazgos:
      {"file": rel, "line": n, "kind": "no-asserts"|"trivial-assert"|"empty-test",
       "name": <test_name>}.

    Salta archivos que no parsean (SyntaxError/OSError) sin recolectar nada para ellos
    y sin propagar la excepción.
    """
    root = Path(repo_path)

    if files is not None:
        candidates: list[Path] = []
        for f in files:
            fp = Path(f)
            rel_for_check = f if not fp.is_absolute() else str(fp)
            if not fp.is_absolute():
                fp = root / fp
            if not _is_test_file(rel_for_check):
                continue
            if fp.is_file():
                candidates.append(fp)
    else:
        candidates = [f for f in root.rglob("*.py")
                      if _is_test_file(str(f.relative_to(root)))
                      and not (_SECRET_SKIP_DIRS & set(f.parts))]

    findings: list[dict] = []
    for fp in candidates:
        try:
            tree = ast.parse(fp.read_text(encoding="utf-8", errors="replace"))
        except (SyntaxError, OSError):
            continue  # archivo roto / ilegible → no recolectamos nada para él
        try:
            rel = str(fp.relative_to(root))
        except ValueError:
            rel = str(fp)

        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            if not node.name.startswith("test"):
                continue

            # 1) Cuerpo vacío (solo pass / docstring).
            if _body_is_empty(node.body):
                findings.append({"file": rel, "line": node.lineno,
                                 "kind": "empty-test", "name": node.name})
                continue

            asserts = [n for n in ast.walk(node) if isinstance(n, ast.Assert)]
            # 2) Sin ningún assert.
            if not asserts:
                findings.append({"file": rel, "line": node.lineno,
                                 "kind": "no-asserts", "name": node.name})
                continue
            # 3) Todos los asserts son triviales.
            if all(_assert_is_trivial(a) for a in asserts):
                findings.append({"file": rel, "line": node.lineno,
                                 "kind": "trivial-assert", "name": node.name})

    return findings


def _check_test_quality(repo_path: str, stack: dict, files: list[str] | None = None) -> dict:
    """B2.3: gate DURO de calidad de tests generados.

    Guardado por config.TEST_QUALITY_GATE (referencia dinámica → monkeypatch-friendly).
    Si está desactivado, se salta como `disabled`.
    """
    gate = "test-quality"
    import config  # referencia dinámica → monkeypatch-friendly
    if not getattr(config, "TEST_QUALITY_GATE", True):
        return _skip(gate, "disabled", "Validación de calidad de tests desactivada (TEST_QUALITY_GATE=false).",
                     layer="tests")

    findings = scan_trivial_tests(repo_path, files=files)
    passed = len(findings) == 0

    if findings:
        _kind_desc = {
            "no-asserts":     "sin ningún assert",
            "trivial-assert": "solo asserts triviales (assert True/1/\"...\"/not False)",
            "empty-test":     "cuerpo vacío (pass / solo docstring)",
        }
        lines = [f"{len(findings)} test(s) débil(es) detectado(s) — no validan comportamiento real:"]
        for fd in findings[:30]:
            lines.append(f"  - {fd['file']}:{fd['line']} · {fd['name']} · {_kind_desc.get(fd['kind'], fd['kind'])}")
        lines.append("\nAñade asserts que verifiquen el comportamiento esperado (valores de retorno, "
                     "efectos, excepciones). Un test sin assert real no protege contra regresiones.")
        out = "\n".join(lines)
    else:
        out = "Tests generados con asserts reales (sin tests triviales/vacíos)."

    return _result(gate, "test-quality", passed, out, layer="tests")


# ── B2.2 — Cobertura sobre código nuevo (gate opcional) ────────────────────────
# Política unit-testeable: dado un mapeo archivo→% cubierto, devuelve los archivos
# nuevos por debajo del umbral. Mantiene la decisión sin depender de un run real de
# coverage (no disponible en este entorno de fábrica).

def coverage_shortfall(per_file_pct: dict[str, float], files: list[str],
                       minimum: float) -> list[dict]:
    """Archivos nuevos cuya cobertura está por debajo de `minimum`.

    `per_file_pct`: mapeo archivo→% cubierto (0–100). `files`: archivos nuevos a evaluar.
    Solo se consideran los archivos presentes en `per_file_pct` (si no hay dato de un
    archivo, no se puede afirmar que falle → se omite, no se asume verde ni rojo).

    Retorna: [{"file": f, "pct": <pct>, "minimum": minimum}] para los que incumplen.
    """
    short: list[dict] = []
    for f in files:
        if f not in per_file_pct:
            continue
        pct = per_file_pct[f]
        if pct < minimum:
            short.append({"file": f, "pct": pct, "minimum": minimum})
    return short


def _load_coverage_per_file(repo_path: str, files: list[str]) -> dict[str, float] | None:
    """Carga % de cobertura por archivo desde `coverage.py` si hay datos.

    Devuelve un mapeo {rel_path: pct} o None si no hay fuente de cobertura disponible
    (sin `.coverage`, sin la librería `coverage`, o sin datos legibles). NUNCA inventa
    cobertura: ante la duda, devuelve None para que el gate haga SKIP n/a.
    """
    root = Path(repo_path)
    if not (root / ".coverage").exists():
        return None
    try:
        import coverage  # noqa: F401  (solo disponible si el repo lo instaló)
    except ImportError:
        return None

    try:
        cov = coverage.Coverage(data_file=str(root / ".coverage"))
        cov.load()
        data = cov.get_data()
    except (OSError, ValueError):
        return None

    measured = set(data.measured_files())
    if not measured:
        return None

    per_file: dict[str, float] = {}
    for f in files:
        fp = Path(f)
        abs_path = str((root / fp).resolve()) if not fp.is_absolute() else str(fp)
        if abs_path not in measured:
            continue
        try:
            analysis = cov.analysis2(abs_path)
        except (OSError, ValueError, coverage.misc.CoverageException):
            continue
        # analysis2 → (filename, statements, excluded, missing, missing_formatted)
        statements = analysis[1]
        missing = analysis[3]
        n_stmt = len(statements)
        pct = 100.0 if n_stmt == 0 else (n_stmt - len(missing)) / n_stmt * 100.0
        per_file[f] = pct
    return per_file or None


def _check_new_code_coverage(repo_path: str, stack: dict, files: list[str] | None = None) -> dict:
    """B2.2: cobertura mínima sobre las líneas de código NUEVO (files_written).

    Guardado por config.NEW_CODE_COVERAGE_GATE (referencia dinámica). Implementación
    defensiva: si el gate está desactivado, no hay archivos nuevos, o no hay fuente de
    cobertura disponible, hace SKIP (n/a) — NUNCA falla por ausencia ni asume verde.
    """
    gate = "new-code-coverage"
    import config  # referencia dinámica → monkeypatch-friendly
    if not getattr(config, "NEW_CODE_COVERAGE_GATE", False):
        return _skip(gate, "disabled", "Cobertura de código nuevo desactivada (NEW_CODE_COVERAGE_GATE=false).")
    if not files:
        return _skip(gate, "n/a", "Sin archivos nuevos que evaluar para cobertura.")

    per_file = _load_coverage_per_file(repo_path, files)
    if not per_file:
        return _skip(gate, "n/a", "Sin datos de cobertura disponibles (.coverage / librería coverage).")

    minimum = float(getattr(config, "COVERAGE_MIN_NEW", 80))
    short = coverage_shortfall(per_file, list(per_file.keys()), minimum)
    passed = len(short) == 0

    if short:
        lines = [f"{len(short)} archivo(s) nuevo(s) por debajo del {minimum:.0f}% de cobertura:"]
        for s in short[:30]:
            lines.append(f"  - {s['file']}: {s['pct']:.1f}% (< {s['minimum']:.0f}%)")
        out = "\n".join(lines)
    else:
        out = f"Todos los archivos nuevos medidos cumplen el {minimum:.0f}% de cobertura."

    return _result(gate, "new-code-coverage", passed, out)


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


def run_all_checks(repo_path: str, install_deps: bool = True,
                   files: list[str] | None = None) -> dict:
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
        "secret_scan":   _check_secret_scan(repo_path, stack, files),  # A2.2
        "test_quality":  _check_test_quality(repo_path, stack, files),  # B2.3
        "new_cov":       _check_new_code_coverage(repo_path, stack, files),  # B2.2
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
