"""
tools/stack_reader.py — Lee y parsea el STACK.md del repositorio destino.

STACK.md es el documento que define el stack tecnológico del proyecto.
Se genera automáticamente por A0 al crear un proyecto nuevo, y puede
editarse manualmente por el equipo.

Si STACK.md no existe, se infiere el stack desde los archivos del repo
(requirements.txt, package.json, etc.) con un nivel de confianza menor.

Formato esperado de STACK.md:
---
## Backend
framework: django
language: python
version: 3.11

## Frontend
framework: react
language: typescript
version: 18

## Testing
backend: pytest
frontend: vitest

## Database
engine: postgresql
orm: django-orm
---
"""
from __future__ import annotations

import re
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

# ── Stacks soportados y sus instrucciones específicas por agente ──────────────

# F4.2 — Reducir sesgo de stack. Las instrucciones por framework viven en archivos externos
# `pipelines/software/stacks/{framework}.md` (no incrustadas en los prompts/código), para que
# un repo FastAPI+Vue reciba instrucciones FastAPI+Vue SIN fugas de Django/React. Se cargan una
# vez al importar; cada .md tiene secciones `## Estructura`, `## Imports`, `## Testing`, `## QA`.
_STACKS_DIR = Path(__file__).resolve().parent.parent / "pipelines" / "software" / "stacks"


def _parse_stack_md(text: str) -> dict:
    """Parsea un .md de stack en {seccion_lower: contenido} (secciones `## Titulo`)."""
    sections: dict[str, str] = {}
    current = None
    buf: list[str] = []
    for line in text.splitlines():
        if line.startswith("## "):
            if current is not None:
                sections[current] = "\n".join(buf).strip()
            current = line[3:].strip().lower()
            buf = []
        elif current is not None:
            buf.append(line)
    if current is not None:
        sections[current] = "\n".join(buf).strip()
    return sections


def _load_stacks() -> dict[str, dict]:
    """Carga todas las instrucciones de stack desde los .md (framework = nombre de archivo)."""
    stacks: dict[str, dict] = {}
    if not _STACKS_DIR.is_dir():
        logger.warning("stack_reader: no existe el directorio de stacks %s", _STACKS_DIR)
        return stacks
    for md in _STACKS_DIR.glob("*.md"):
        try:
            stacks[md.stem.lower()] = _parse_stack_md(md.read_text(encoding="utf-8"))
        except OSError as exc:
            logger.warning("stack_reader: no se pudo leer %s (%s)", md, exc)
    return stacks


# Mapa framework → {estructura, imports, testing, qa}. Fuente de verdad: los .md de stacks.
STACK_INSTRUCTIONS: dict[str, dict] = _load_stacks()


def _infer_stack_from_files(repo: Path) -> dict:
    """Infiere el stack desde los archivos del repositorio."""
    stack = {
        "backend":  "unknown",
        "frontend": "unknown",
        "backend_version":  "",
        "frontend_version": "",
        "testing_backend":  "",
        "testing_frontend": "",
        "database": "",
        "inferred": True,  # Flag: fue inferido, no leído de STACK.md
    }

    # Backend detection
    req = (repo / "requirements.txt").read_text(encoding="utf-8") if (repo / "requirements.txt").exists() else ""
    if "django" in req.lower():
        stack["backend"] = "django"
    elif "fastapi" in req.lower():
        stack["backend"] = "fastapi"
    elif "flask" in req.lower():
        stack["backend"] = "flask"

    # Frontend detection
    pkg_path = repo / "package.json"
    if pkg_path.exists():
        pkg = pkg_path.read_text(encoding="utf-8").lower()
        if "next" in pkg:
            stack["frontend"] = "nextjs"
        elif "vue" in pkg:
            stack["frontend"] = "vue"
        elif "react" in pkg:
            stack["frontend"] = "react"
        else:
            stack["frontend"] = "vanilla"

    # Testing
    if "pytest" in req.lower():
        stack["testing_backend"] = "pytest"
    if stack["frontend"] != "unknown":
        if "vitest" in (pkg_path.read_text() if pkg_path.exists() else ""):
            stack["testing_frontend"] = "vitest"
        else:
            stack["testing_frontend"] = "jest"

    return stack


def _parse_stack_md(content: str) -> dict:
    """Parsea el contenido de STACK.md en un dict."""
    stack = {
        "backend": "unknown", "frontend": "unknown",
        "backend_version": "", "frontend_version": "",
        "testing_backend": "", "testing_frontend": "",
        "database": "", "inferred": False,
    }

    current_section = None
    for line in content.splitlines():
        line = line.strip()
        if line.startswith("## "):
            current_section = line[3:].strip().lower()
            continue

        if ":" not in line:
            continue
        key, _, value = line.partition(":")
        key   = key.strip().lower()
        value = value.strip().lower()

        if current_section == "backend":
            if key == "framework":
                stack["backend"] = value
            elif key in ("version", "python_version", "node_version"):
                stack["backend_version"] = value
        elif current_section == "frontend":
            if key == "framework":
                stack["frontend"] = value
            elif key == "version":
                stack["frontend_version"] = value
        elif current_section == "testing":
            if key in ("backend", "python"):
                stack["testing_backend"] = value
            elif key in ("frontend", "javascript", "typescript"):
                stack["testing_frontend"] = value
        elif current_section == "database":
            if key in ("engine", "db"):
                stack["database"] = value

    return stack


def read_stack(repo_path: str) -> dict:
    """
    Lee el stack del proyecto desde STACK.md o lo infiere del repo.

    Returns dict con:
        backend, frontend, backend_version, frontend_version,
        testing_backend, testing_frontend, database, inferred
    """
    repo = Path(repo_path)
    stack_file = repo / "STACK.md"

    if stack_file.exists():
        try:
            content = stack_file.read_text(encoding="utf-8")
            stack = _parse_stack_md(content)
            logger.info("stack_reader: STACK.md leído — backend=%s frontend=%s",
                        stack["backend"], stack["frontend"])
            return stack
        except Exception as e:
            logger.warning("stack_reader: error leyendo STACK.md — %s", e)

    # Fallback: inferir
    stack = _infer_stack_from_files(repo)
    logger.info("stack_reader: stack inferido — backend=%s frontend=%s",
                stack["backend"], stack["frontend"])
    return stack


def _format_instructions(layer: str, framework: str) -> str:
    """Bloque de estructura+imports para un framework, o "" si no se reconoce (SIN fallback)."""
    info = STACK_INSTRUCTIONS.get((framework or "").lower())
    if not info or not info.get("estructura"):
        return ""   # F4.2 — sin fuga: un stack desconocido NO recibe Django/React por defecto
    block = f"**Stack {layer}: {framework.upper()}**\n\nEstructura de archivos:\n{info['estructura']}"
    if info.get("imports"):
        block += f"\n\nImports típicos:\n```\n{info['imports']}\n```"
    return block


def get_backend_instructions(stack: dict) -> str:
    """Instrucciones de estructura para el agente backend (desde stacks/{framework}.md)."""
    return _format_instructions("Backend", stack.get("backend", "unknown"))


def get_frontend_instructions(stack: dict) -> str:
    """Instrucciones de estructura para el agente frontend (desde stacks/{framework}.md)."""
    return _format_instructions("Frontend", stack.get("frontend", "unknown"))


def get_qa_instructions(stack: dict) -> str:
    """Instrucciones de testing para el agente QA (desde stacks/{framework}.md)."""
    lines = []
    for layer, key in (("Backend", "backend"), ("Frontend", "frontend")):
        fw = (stack.get(key, "unknown") or "").lower()
        info = STACK_INSTRUCTIONS.get(fw)
        if info and info.get("qa"):
            lines.append(f"**Tests {layer} ({fw}):**\n{info['qa']}")
    return "\n\n".join(lines) if lines else ""


def generate_stack_md(
    project_name: str,
    backend: str,
    frontend: str,
    backend_version: str = "",
    frontend_version: str = "",
    database: str = "postgresql",
) -> str:
    """Genera el contenido de un STACK.md nuevo para un proyecto."""
    backend_test = STACK_INSTRUCTIONS.get((backend or "").lower(), {}).get("testing", "pytest")
    frontend_test = "vitest" if frontend in ("react", "vue", "nextjs") else "jest"

    lines = [
        f"# Stack Tecnológico — {project_name}",
        "",
        "## Backend",
        f"framework: {backend}",
        f"language: {'python' if backend in ('django', 'fastapi', 'flask') else 'node'}",
    ]
    if backend_version:
        lines.append(f"version: {backend_version}")

    lines += [
        "",
        "## Frontend",
        f"framework: {frontend}",
        f"language: {'typescript' if frontend != 'vanilla' else 'javascript'}",
    ]
    if frontend_version:
        lines.append(f"version: {frontend_version}")

    lines += [
        "",
        "## Database",
        f"engine: {database}",
        f"orm: {'django-orm' if backend == 'django' else 'sqlalchemy' if backend == 'fastapi' else 'sequelize'}",
        "",
        "## Testing",
        f"backend: {backend_test.split(' ')[0]}",
        f"frontend: {frontend_test}",
        "",
        "## Notes",
        "# Edita este archivo para personalizar las instrucciones de los agentes.",
        "# Los agentes A4, A5 y A7 leen este archivo en cada ciclo.",
    ]

    return "\n".join(lines) + "\n"
