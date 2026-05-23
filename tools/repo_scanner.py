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

logger = logging.getLogger(__name__)

# ── Archivos siempre incluidos si existen ─────────────────────────────────────
ALWAYS_INCLUDE = [
    "README.md",
    "ARCHITECTURE.md",
    "STACK.md",
    "agents/PROJECT_CONTEXT.md",
    "agents/DECISION_LOG.md",
    "agents/CODING_STANDARDS.md",
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
