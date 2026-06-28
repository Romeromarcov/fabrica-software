"""
tools/repo_scanner.py — Snapshot del código real del repositorio para A0.

Cuando OpenClaw no está disponible y el modo es is_new=False (continuar proyecto),
este módulo da a A0 un snapshot de los archivos más relevantes del repo para
que pueda planificar con información real en lugar de solo los docs estáticos.

Estrategia de selección:
  1. Siempre incluir: README.md, ARCHITECTURE.md, DECISION_LOG.md,
     requirements.txt, package.json, STACK.md
  2. Por stack detectado: models.py, urls.py, settings.py, routes.ts, etc.
  3. Archivos modificados recientemente (git log --since=30 days)
  4. Limitar a `max_files` y `max_chars` para no exceder el token budget
"""
from __future__ import annotations

import logging
import subprocess
from pathlib import Path

from tools.degradation import best_effort_log

logger = logging.getLogger(__name__)

# ── Archivos siempre incluidos si existen ─────────────────────────────────────
ALWAYS_INCLUDE = [
    "README.md",
    "ARCHITECTURE.md",
    "STACK.md",
    "agents/PROJECT_CONTEXT.md",
    "agents/DECISION_LOG.md",
    "agents/CODING_STANDARDS.md",
    "agents/CODEBASE_FINGERPRINT.md",  # II-1: fingerprint generado por build_fingerprint()
    "requirements.txt",
    "pyproject.toml",
    "package.json",
    "manage.py",
]

# ── Glob patterns por stack ───────────────────────────────────────────────────
STACK_PATTERNS = {
    "django": [
        "*/models.py",
        "*/serializers.py",
        "*/urls.py",
        "*/admin.py",
        "**/settings*.py",
    ],
    "fastapi": [
        "app/main.py",
        "app/models/*.py",
        "app/schemas/*.py",
        "app/routers/*.py",
        "app/core/config.py",
    ],
    "express": [
        "src/app.ts",
        "src/app.js",
        "src/routes/*.ts",
        "src/routes/*.js",
        "src/models/*.ts",
        "src/models/*.js",
    ],
    "react": [
        "src/types/*.ts",
        "src/services/*.ts",
        "src/hooks/use*.ts",
        "src/router*.tsx",
        "src/App.tsx",
        "src/main.tsx",
    ],
    "vue": [
        "src/router/index.ts",
        "src/stores/*.ts",
        "src/composables/*.ts",
        "src/App.vue",
    ],
    "nextjs": [
        "app/layout.tsx",
        "app/page.tsx",
        "lib/*.ts",
        "components/*.tsx",
    ],
}

# ── Archivos nunca incluidos ──────────────────────────────────────────────────
NEVER_INCLUDE_RE_PARTS = [
    r"\.env",
    r"\.key$",
    r"\.pem$",
    r"node_modules/",
    r"__pycache__/",
    r"\.git/",
    r"dist/",
    r"build/",
    r"\.venv/",
    r"venv/",
    r"migrations/",       # demasiado verboso
    r"static/",
    r"media/",
    r"\.lock$",           # yarn.lock, package-lock.json, etc.
]

import re as _re
_NEVER_RE = _re.compile("|".join(NEVER_INCLUDE_RE_PARTS), _re.IGNORECASE)


def _git_recent_files(repo: Path, days: int = 30) -> list[str]:
    """Devuelve los archivos modificados en los últimos N días (git log)."""
    try:
        result = subprocess.run(
            ["git", "log", f"--since={days} days ago", "--name-only",
             "--pretty=format:", "--diff-filter=AM"],
            cwd=str(repo),
            capture_output=True, text=True, timeout=10,
        )
        files = []
        for line in result.stdout.splitlines():
            line = line.strip()
            if line and not _NEVER_RE.search(line):
                p = repo / line
                if p.exists() and p.is_file():
                    files.append(line)
        return list(dict.fromkeys(files))  # dedup preservando orden
    except Exception:
        return []


def _collect_by_patterns(repo: Path, patterns: list[str], max_per_pattern: int = 5) -> list[str]:
    """Recopila archivos por glob patterns, hasta max_per_pattern por patrón."""
    files = []
    for pattern in patterns:
        for p in sorted(repo.glob(pattern))[:max_per_pattern]:
            rel = str(p.relative_to(repo)).replace("\\", "/")
            if not _NEVER_RE.search(rel):
                files.append(rel)
    return files


def _read_truncated(path: Path, max_chars: int = 2000) -> str:
    """Lee un archivo truncando si es muy grande."""
    try:
        content = path.read_text(encoding="utf-8", errors="replace")
        if len(content) > max_chars:
            return content[:max_chars] + f"\n... [truncado — {len(content)} chars totales]"
        return content
    except Exception as e:
        return f"[Error leyendo {path}: {e}]"


def scan_repo(
    repo_path: str,
    stack: dict | None = None,
    max_files: int = 30,
    max_chars_per_file: int = 2000,
    max_total_chars: int = 40_000,
) -> str:
    """
    Genera un snapshot legible del repositorio para inyectar en A0.

    Args:
        repo_path: ruta absoluta del repositorio
        stack: dict del stack (de stack_reader.read_stack) — puede ser None
        max_files: máximo de archivos a incluir
        max_chars_per_file: máximo de chars por archivo (truncado)
        max_total_chars: límite total del snapshot

    Returns:
        Texto Markdown con el snapshot del repo, listo para inyectar en el prompt
    """
    repo = Path(repo_path)
    if not repo.exists():
        return f"[repo_scanner] Repositorio no encontrado: {repo_path}"

    # ── Construir lista de candidatos ─────────────────────────────────────────
    candidates: list[str] = []

    # 1. Archivos de alta prioridad siempre incluidos
    for rel in ALWAYS_INCLUDE:
        p = repo / rel
        if p.exists():
            candidates.append(rel)

    # 2. Archivos por stack detectado
    if stack:
        for stack_name in (stack.get("backend"), stack.get("frontend")):
            if stack_name and stack_name in STACK_PATTERNS:
                candidates.extend(
                    _collect_by_patterns(repo, STACK_PATTERNS[stack_name])
                )

    # 3. Archivos modificados recientemente
    candidates.extend(_git_recent_files(repo))

    # Deduplicar preservando orden de prioridad
    seen: set[str] = set()
    unique: list[str] = []
    for f in candidates:
        if f not in seen:
            seen.add(f)
            unique.append(f)

    # Limitar al max_files
    selected = unique[:max_files]

    # ── Construir el snapshot ─────────────────────────────────────────────────
    total_chars = 0
    blocks: list[str] = []

    for rel in selected:
        if total_chars >= max_total_chars:
            remaining = len(selected) - len(blocks)
            blocks.append(f"\n... [{remaining} archivo(s) más omitidos por límite de tokens]")
            break

        p = repo / rel
        if not p.exists() or not p.is_file():
            continue

        content = _read_truncated(p, max_chars_per_file)
        ext = p.suffix.lstrip(".")
        block = f"\n### `{rel}`\n```{ext}\n{content}\n```"
        blocks.append(block)
        total_chars += len(block)

    if not blocks:
        return "[repo_scanner] No se encontraron archivos relevantes en el repositorio."

    header = (
        f"## SNAPSHOT DEL REPOSITORIO — `{repo.name}`\n"
        f"*{len(blocks)} archivo(s) indexado(s) de {len(selected)} seleccionados*\n"
        f"*(Archivos más recientes y relevantes para el stack detectado)*\n"
    )

    return header + "\n".join(blocks)


def get_repo_context_for_a0(repo_path: str, stack: dict | None = None) -> str:
    """
    Wrapper de alto nivel para A0.
    Devuelve el snapshot con una instrucción de uso para el agente.
    """
    snapshot = scan_repo(repo_path=repo_path, stack=stack)

    intro = (
        "## CÓDIGO ACTUAL DEL REPOSITORIO\n\n"
        "Los archivos más relevantes del proyecto están adjuntos abajo.\n"
        "Úsalos para entender el estado actual antes de planificar nuevos features.\n"
        "Presta especial atención a los modelos, rutas y servicios existentes.\n\n"
    )

    return intro + snapshot


# ── II-1: Agente Indexador de Codebase ───────────────────────────────────────

FINGERPRINT_FILE = Path("agents") / "CODEBASE_FINGERPRINT.md"


def _detect_stack_info(repo: Path) -> dict:
    """Detecta el stack tecnológico a partir de los archivos de dependencias."""
    info: dict = {"backend": None, "frontend": None, "extras": [], "db": None}

    # ── Python / backend ──────────────────────────────────────────────────────
    py_content = ""
    for dep_file in ("requirements.txt", "pyproject.toml", "setup.py"):
        p = repo / dep_file
        if p.exists():
            py_content += p.read_text(encoding="utf-8", errors="replace")

    if py_content:
        cl = py_content.lower()
        if "django" in cl:
            info["backend"] = "Django"
            if "djangorestframework" in cl or "rest_framework" in cl:
                info["backend"] += " + DRF"
            if "graphene" in cl:
                info["backend"] += " + GraphQL"
        elif "fastapi" in cl:
            info["backend"] = "FastAPI"
        elif "flask" in cl:
            info["backend"] = "Flask"

        if "psycopg" in cl or "postgresql" in cl:
            info["db"] = "PostgreSQL"
        elif "mysqlclient" in cl or "pymysql" in cl:
            info["db"] = "MySQL"
        elif "sqlite" in cl:
            info["db"] = "SQLite"

        for pkg in ("celery", "redis", "elasticsearch", "boto3", "stripe"):
            if pkg in cl:
                info["extras"].append(pkg.capitalize())

    # ── JavaScript / frontend ─────────────────────────────────────────────────
    pkg_json = repo / "package.json"
    if pkg_json.exists():
        try:
            import json as _json
            pkg = _json.loads(pkg_json.read_text(encoding="utf-8"))
            all_deps = {**pkg.get("dependencies", {}), **pkg.get("devDependencies", {})}
            dl = {k.lower() for k in all_deps}

            if "react" in dl:
                info["frontend"] = "React"
                if "typescript" in dl or any("@types/" in d for d in dl):
                    info["frontend"] += " + TypeScript"
            elif "vue" in dl:
                info["frontend"] = "Vue"
            elif "next" in dl:
                info["frontend"] = "Next.js"
            elif "svelte" in dl:
                info["frontend"] = "Svelte"

            for lib, label in (
                ("@tanstack/react-query", "TanStack Query"),
                ("react-query", "TanStack Query"),
                ("@mui/material", "MUI"),
                ("tailwindcss", "Tailwind"),
                ("zustand", "Zustand"),
                ("pinia", "Pinia"),
            ):
                if lib in all_deps or lib.lower() in dl:
                    info["extras"].append(label)
        except Exception:
            pass

    return info


def _find_django_modules(repo: Path) -> list[dict]:
    """Encuentra módulos Django y su estado de implementación."""
    modules: list[dict] = []

    for models_file in sorted(repo.glob("*/models.py")):
        app_dir = models_file.parent
        rel = str(app_dir.relative_to(repo)).replace("\\", "/")
        if _NEVER_RE.search(rel):
            continue

        modules.append({
            "name":         app_dir.name,
            "path":         rel,
            "has_models":   True,
            "has_services": (app_dir / "services.py").exists() or any(app_dir.glob("services/")),
            "has_tests":    (app_dir / "tests.py").exists() or any(app_dir.glob("tests/")) or any(app_dir.glob("test_*.py")),
            "has_api":      (app_dir / "serializers.py").exists() or (app_dir / "views.py").exists(),
            "has_urls":     (app_dir / "urls.py").exists(),
        })

    return modules


def _detect_conventions(repo: Path) -> list[str]:
    """Detecta convenciones de código a partir de muestras reales."""
    conventions: list[str] = []

    # FK pattern (ej: id_empresa)
    fk_pattern = _re.compile(r"\b(id_\w+)\s*=\s*models\.ForeignKey")
    for models_file in list(repo.glob("*/models.py"))[:6]:
        try:
            content = models_file.read_text(encoding="utf-8", errors="replace")
            fk_matches = fk_pattern.findall(content)
            if fk_matches:
                example = fk_matches[0]
                conventions.append(
                    f"FK con prefijo `id_`: todos los modelos usan `{example} = models.ForeignKey(...)`"
                )
                break
        except Exception:
            pass

    # @transaction.atomic
    for service_file in list(repo.glob("*/services.py"))[:5]:
        try:
            content = service_file.read_text(encoding="utf-8", errors="replace")
            if "@transaction.atomic" in content:
                conventions.append("Services: `@transaction.atomic` en operaciones de escritura")
                break
        except Exception:
            pass

    # Logger estándar
    for py_file in list(repo.glob("**/*.py"))[:30]:
        if _NEVER_RE.search(str(py_file.relative_to(repo))):
            continue
        try:
            content = py_file.read_text(encoding="utf-8", errors="replace")
            if "logger = logging.getLogger(__name__)" in content:
                conventions.append("Logger: `logger = logging.getLogger(__name__)` al inicio de cada módulo")
                break
        except Exception:
            pass

    # Fixtures de conftest
    conftest = repo / "conftest.py"
    if conftest.exists():
        try:
            content = conftest.read_text(encoding="utf-8", errors="replace")
            fixtures = _re.findall(r"@pytest\.fixture[^\n]*\ndef (\w+)", content)
            if fixtures:
                flist = ", ".join(f"`{f}`" for f in fixtures[:5])
                conventions.append(f"Fixtures de conftest.py disponibles: {flist}")
        except OSError as exc:
            # E3.1: degradación observable — el fingerprint pierde las fixtures
            # de conftest como contexto, pero queda logueado.
            best_effort_log("Fingerprint: fixtures de conftest", exc, logger)

    # BaseModel / soft-delete
    for models_file in list(repo.glob("*/models.py"))[:6]:
        try:
            content = models_file.read_text(encoding="utf-8", errors="replace")
            if "BaseModel" in content and "deleted_at" in content:
                conventions.append("Modelos usan `BaseModel` con soft-delete (`deleted_at`)")
                break
        except Exception:
            pass

    return conventions


def _detect_env_vars(repo: Path) -> list[str]:
    """Detecta variables de entorno referenciadas en el proyecto."""
    env_vars: list[str] = []
    seen: set[str] = set()

    # Desde .env.example
    for env_file in (".env.example", ".env.template", ".env.sample"):
        p = repo / env_file
        if p.exists():
            try:
                for line in p.read_text(encoding="utf-8", errors="replace").splitlines():
                    line = line.strip()
                    if line and not line.startswith("#") and "=" in line:
                        key = line.split("=")[0].strip()
                        if key and key not in seen:
                            seen.add(key)
                            env_vars.append(key)
            except Exception:
                pass
            break

    # Desde settings.py
    for settings_file in list(repo.glob("**/settings*.py"))[:3]:
        if _NEVER_RE.search(str(settings_file.relative_to(repo))):
            continue
        try:
            content = settings_file.read_text(encoding="utf-8", errors="replace")
            for key in _re.findall(r'os\.environ\.get\(["\'](\w+)["\']', content):
                if key not in seen:
                    seen.add(key)
                    env_vars.append(key)
        except OSError as exc:
            # E3.1: degradación observable — el fingerprint pierde las env vars
            # de settings.py como contexto, pero queda logueado.
            best_effort_log("Fingerprint: env vars de settings.py", exc, logger)

    return env_vars[:20]


_SKIP_STRUCT_DIRS = {".git", "node_modules", "__pycache__", ".venv", "venv", "dist",
                     "build", ".next", "migrations", "tests", "test", "__tests__"}


def _detect_structure(repo: Path) -> list[str]:
    """
    F6 — Detecta el LAYOUT real del repo (dónde vive el código y con qué estilo de import),
    para que los agentes constructores repliquen la estructura EXISTENTE en vez de una plantilla
    genérica. Devuelve líneas markdown; vacío si el repo está vacío/no reconocible.

    Heurísticas baratas (no AST): busca el entrypoint (FastAPI/Flask/Express), el directorio de
    routers/endpoints y el de modelos, y deduce el prefijo de import (p. ej. `app.` vs plano).
    """
    lines: list[str] = []
    py_files = [p for p in repo.glob("**/*.py")
                if not any(part in _SKIP_STRUCT_DIRS for part in p.relative_to(repo).parts)][:400]

    def _rel(p: Path) -> str:
        return str(p.relative_to(repo)).replace("\\", "/")

    # Entrypoint: archivo que instancia la app.
    entry = None
    for p in py_files:
        try:
            txt = p.read_text(encoding="utf-8", errors="ignore")
        except OSError as exc:
            logger.debug("_detect_structure: no se pudo leer %s (%s)", p, exc)
            continue
        if "FastAPI(" in txt or "Flask(__name__" in txt or "= Flask(" in txt:
            entry = p
            break
    if entry is not None:
        lines.append(f"- **Entrypoint:** `{_rel(entry)}`")

    # Directorios de routers/endpoints (FastAPI APIRouter / Flask Blueprint / Express Router).
    router_dirs: dict[str, int] = {}
    model_dirs: dict[str, int] = {}
    for p in py_files:
        try:
            txt = p.read_text(encoding="utf-8", errors="ignore")
        except OSError as exc:
            logger.debug("_detect_structure: no se pudo leer %s (%s)", p, exc)
            continue
        d = str(p.parent.relative_to(repo)).replace("\\", "/") or "."
        if "APIRouter(" in txt or "Blueprint(" in txt or "@router." in txt:
            router_dirs[d] = router_dirs.get(d, 0) + 1
        if "(Base)" in txt or "declarative_base" in txt or "db.Model" in txt or "Column(" in txt:
            model_dirs[d] = model_dirs.get(d, 0) + 1

    def _top(dct: dict[str, int]) -> str | None:
        return max(dct, key=dct.get) if dct else None

    rdir, mdir = _top(router_dirs), _top(model_dirs)
    if rdir:
        lines.append(f"- **Routers/endpoints en:** `{rdir}/` (replica AHÍ los endpoints nuevos)")
    if mdir:
        lines.append(f"- **Modelos en:** `{mdir}/`")

    # Estilo de import: ¿usa un paquete raíz (`from app.`/`from src.`) o imports planos?
    if entry is not None:
        try:
            etxt = entry.read_text(encoding="utf-8", errors="ignore")
        except OSError as exc:
            logger.debug("_detect_structure: no se pudo leer entrypoint %s (%s)", entry, exc)
            etxt = ""
        import re as _r
        roots = _r.findall(r"^\s*from\s+(\w+)[\s.]", etxt, _r.MULTILINE)
        pkg_roots = [r for r in roots if r not in ("fastapi", "starlette", "pydantic",
                     "sqlalchemy", "os", "sys", "logging", "typing", "datetime", "contextlib")]
        top_dirs = {d.name for d in repo.iterdir() if d.is_dir() and d.name not in _SKIP_STRUCT_DIRS}
        local = [r for r in pkg_roots if r in top_dirs or (entry.parent / r).exists()]
        if any(r in ("app", "src") for r in local):
            lines.append(f"- **Estilo de import:** con paquete raíz `{[r for r in local if r in ('app','src')][0]}.` "
                         f"(p. ej. `from app.models...`)")
        elif local:
            lines.append("- **Estilo de import:** imports PLANOS dentro del dir del entrypoint "
                         f"(p. ej. `from {local[0]} import ...`) — NO uses un paquete `app.` inexistente")

    if lines:
        lines.insert(0, "_Replica esta estructura — NO inventes un layout `app/api/v1/...` si el repo no lo usa._")
    return lines


def build_fingerprint(repo_path: str) -> str:
    """
    Escanea el repo completo y genera `agents/CODEBASE_FINGERPRINT.md`.

    Extrae del código real:
    - Stack detectado (requirements.txt, package.json)
    - Convenciones del código (FKs, decoradores, loggers, fixtures)
    - Estado de módulos (tabla: models / services / tests / API)
    - Gaps detectados (módulos sin tests, sin servicios, etc.)
    - Variables de entorno referenciadas

    Retorna el contenido del fingerprint (también lo escribe en disco).
    """
    from datetime import datetime as _dt

    repo = Path(repo_path)
    if not repo.exists():
        logger.warning("build_fingerprint: repo no encontrado: %s", repo_path)
        return ""

    stack_info  = _detect_stack_info(repo)
    modules     = _find_django_modules(repo)
    conventions = _detect_conventions(repo)
    env_vars    = _detect_env_vars(repo)
    structure   = _detect_structure(repo)

    # ── Construir el documento ────────────────────────────────────────────────
    lines = [
        f"# Codebase Fingerprint — `{repo.name}`",
        f"> Generado: {_dt.utcnow().strftime('%Y-%m-%d %H:%M UTC')} | Auto-actualizado por A10 tras cada feature",
        "",
        "## Stack detectado",
    ]

    be = stack_info.get("backend")
    fe = stack_info.get("frontend")
    db = stack_info.get("db")
    extras = stack_info.get("extras", [])

    if be:
        be_line = f"- **Backend:** {be}"
        if db:
            be_line += f" + {db}"
        if extras:
            be_line += " + " + " + ".join(extras)
        lines.append(be_line)
    if fe:
        lines.append(f"- **Frontend:** {fe}")
    if not be and not fe:
        lines.append("- Stack no identificado (ver requirements.txt / package.json)")
    lines.append("")

    # F6 — Estructura real del repo (PROMINENTE: los constructores deben replicarla, no la
    # plantilla genérica de stack). Va justo tras el stack para máxima visibilidad en el prompt.
    if structure:
        lines.append("## Estructura del proyecto (SEGUIR ESTA, no una plantilla genérica)")
        for s in structure:
            lines.append(s)
        lines.append("")

    if conventions:
        lines.append("## Convenciones detectadas (del código real)")
        for c in conventions:
            lines.append(f"- {c}")
        lines.append("")

    if modules:
        lines.append("## Módulos y su estado")
        lines.append("| Módulo | Models | Services | Tests | API |")
        lines.append("|--------|--------|----------|-------|-----|")
        for m in modules:
            lines.append(
                f"| `{m['name']}` "
                f"| {'✅' if m['has_models']   else '❌'} "
                f"| {'✅' if m['has_services'] else '❌'} "
                f"| {'✅' if m['has_tests']    else '⚠️'} "
                f"| {'✅' if m['has_api']      else '❌'} |"
            )
        lines.append("")

    # Gaps detectados
    gaps: list[str] = []
    for m in modules:
        if not m["has_services"]:
            gaps.append(f"Capa de servicios ausente en `{m['name']}/`")
        if not m["has_tests"]:
            gaps.append(f"Tests ausentes en `{m['name']}/`")
        if not m["has_api"]:
            gaps.append(f"API (serializers/views) ausente en `{m['name']}/`")

    if gaps:
        lines.append("## Gaps detectados (por ausencia en el código)")
        for gap in gaps[:12]:
            lines.append(f"- {gap}")
        lines.append("")

    if env_vars:
        lines.append("## Variables de entorno referenciadas")
        lines.append(", ".join(f"`{v}`" for v in env_vars))
        lines.append("")

    content = "\n".join(lines)

    # ── Guardar en disco ──────────────────────────────────────────────────────
    fp_path = repo / FINGERPRINT_FILE
    fp_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        fp_path.write_text(content, encoding="utf-8")
        logger.info("build_fingerprint: %s (%d chars)", fp_path, len(content))
    except Exception as exc:
        logger.error("build_fingerprint: error al escribir: %s", exc)

    return content


def update_fingerprint(repo_path: str, files_changed: list[str]) -> None:
    """
    Actualización incremental del fingerprint tras que A10 escribe archivos.
    Para repos de hasta ~200 archivos el full-rebuild es suficientemente rápido (< 5 s).
    """
    if not repo_path or not files_changed:
        return
    try:
        build_fingerprint(repo_path)
        logger.info(
            "update_fingerprint: actualizado tras %d archivo(s): %s",
            len(files_changed), ", ".join(files_changed[:5]),
        )
    except Exception as exc:
        logger.error("update_fingerprint: error: %s", exc)


def load_fingerprint(repo_path: str) -> str:
    """
    Carga el CODEBASE_FINGERPRINT.md para inyectarlo en el prompt de un agente.
    Si no existe, genera uno. Devuelve string vacío si el repo no existe.
    """
    if not repo_path:
        return ""

    fp_path = Path(repo_path) / FINGERPRINT_FILE

    if fp_path.exists():
        try:
            content = fp_path.read_text(encoding="utf-8")
            if content.strip():
                return content
        except Exception as exc:
            logger.warning("load_fingerprint: error al leer %s: %s", fp_path, exc)

    # Primera vez — generar ahora
    return build_fingerprint(repo_path)


def fingerprint_context_block(repo_path: str) -> str:
    """
    Retorna el fingerprint formateado para inyectar en un prompt de agente.
    Prefijo de sección incluido. Devuelve string vacío si el repo no existe o está vacío.
    """
    fp = load_fingerprint(repo_path)
    if not fp:
        return ""
    return (
        "\n## 🗺️ CODEBASE FINGERPRINT (estado real del repo)\n\n"
        + fp
        + "\n"
    )
