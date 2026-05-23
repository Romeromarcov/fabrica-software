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

BACKEND_INSTRUCTIONS = {
    "django": {
        "structure": (
            "Usa la estructura estándar de Django: `apps/[modulo]/models.py`, "
            "`serializers.py`, `services.py`, `views.py`, `signals.py`, `urls.py`. "
            "Los ViewSets delegan toda la lógica a services. "
            "Usa Django REST Framework para las APIs."
        ),
        "testing": "pytest-django con fixtures de factory_boy. Test de aislamiento multi-tenant obligatorio.",
        "imports": "from django.db import models\nfrom rest_framework import serializers, viewsets",
    },
    "fastapi": {
        "structure": (
            "Estructura FastAPI: `app/routers/[modulo].py`, `app/models/[modulo].py` (SQLAlchemy), "
            "`app/schemas/[modulo].py` (Pydantic), `app/services/[modulo].py`. "
            "Usa dependency injection de FastAPI para DB sessions y auth."
        ),
        "testing": "pytest con httpx.AsyncClient para tests de endpoints.",
        "imports": "from fastapi import APIRouter, Depends\nfrom sqlalchemy.orm import Session",
    },
    "express": {
        "structure": (
            "Estructura Express/Node: `src/routes/[modulo].ts`, `src/controllers/[modulo].ts`, "
            "`src/services/[modulo].ts`, `src/models/[modulo].ts`. "
            "Usa middleware para autenticación JWT."
        ),
        "testing": "Jest con supertest para tests de endpoints.",
        "imports": "import express from 'express';\nimport { Request, Response } from 'express';",
    },
    "laravel": {
        "structure": (
            "Estructura Laravel: `app/Http/Controllers/[Modulo]Controller.php`, "
            "`app/Models/[Modulo].php`, `app/Services/[Modulo]Service.php`, "
            "`routes/api.php`. Usa Eloquent ORM."
        ),
        "testing": "PHPUnit con factories de Laravel.",
        "imports": "use App\\Models\\[Modulo];\nuse App\\Http\\Controllers\\Controller;",
    },
}

FRONTEND_INSTRUCTIONS = {
    "react": {
        "structure": (
            "Estructura React + TypeScript: `src/types/[modulo].ts`, "
            "`src/services/[modulo]Service.ts`, `src/hooks/use[Feature].ts` (TanStack Query), "
            "`src/components/[Feature]/`, `src/pages/[Feature]Page.tsx`. "
            "Nunca usar `any`. Nunca usar `useEffect` para fetching de datos."
        ),
        "testing": "Vitest + Testing Library para componentes.",
        "imports": "import React from 'react';\nimport { useQuery } from '@tanstack/react-query';",
    },
    "vue": {
        "structure": (
            "Estructura Vue 3 + TypeScript (Composition API): `src/types/[modulo].ts`, "
            "`src/composables/use[Feature].ts` (VueQuery o Pinia), "
            "`src/components/[Feature].vue`, `src/views/[Feature]View.vue`."
        ),
        "testing": "Vitest + @vue/test-utils.",
        "imports": "import { ref, computed } from 'vue';\nimport { useQuery } from '@tanstack/vue-query';",
    },
    "nextjs": {
        "structure": (
            "Estructura Next.js 14+ (App Router): `app/[modulo]/page.tsx`, "
            "`app/[modulo]/layout.tsx`, `components/[Feature].tsx`, "
            "`lib/[modulo].ts` para server actions y data fetching."
        ),
        "testing": "Jest + Testing Library + Playwright para E2E.",
        "imports": "import { Suspense } from 'react';\nimport type { Metadata } from 'next';",
    },
    "vanilla": {
        "structure": (
            "JavaScript/TypeScript vanilla: `src/[modulo]/index.ts`, "
            "`src/[modulo]/api.ts` para llamadas HTTP, `src/[modulo]/ui.ts` para DOM."
        ),
        "testing": "Jest o Vitest.",
        "imports": "// Vanilla TS — no framework",
    },
}

QA_INSTRUCTIONS = {
    "django": (
        "Tests obligatorios:\n"
        "1. Aislamiento multi-tenant (if aplicable)\n"
        "2. Permisos (403 para usuarios sin acceso)\n"
        "3. Happy path de cada endpoint\n"
        "4. Casos límite (vacío, extremos)\n"
        "5. Soft-delete (si aplica)\n"
        "6. Auditoría (LogAuditoria si existe el modelo)\n"
        "Usar: pytest-django, factory_boy, APIClient de DRF"
    ),
    "fastapi": (
        "Tests obligatorios:\n"
        "1. Auth (401 sin token, 403 con permisos insuficientes)\n"
        "2. Happy path de cada endpoint\n"
        "3. Validación de schemas (422 con datos inválidos)\n"
        "4. Transacciones de DB (rollback en error)\n"
        "Usar: pytest, httpx.AsyncClient, pytest-asyncio"
    ),
    "express": (
        "Tests obligatorios:\n"
        "1. Auth middleware (401/403)\n"
        "2. Happy path de cada ruta\n"
        "3. Validación de input\n"
        "4. Manejo de errores (500 controlado)\n"
        "Usar: Jest, supertest"
    ),
    "react": (
        "Tests de frontend:\n"
        "1. Render sin crash (snapshot o RTL)\n"
        "2. Loading state\n"
        "3. Error state\n"
        "4. Interacciones de usuario (click, submit)\n"
        "5. Datos vacíos\n"
        "Usar: Vitest, @testing-library/react"
    ),
    "vue": (
        "Tests de frontend Vue:\n"
        "1. Render sin crash\n"
        "2. Props y emits correctos\n"
        "3. Estados reactivos\n"
        "Usar: Vitest, @vue/test-utils"
    ),
}


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


def get_backend_instructions(stack: dict) -> str:
    """Devuelve las instrucciones de estructura para el agente backend."""
    backend = stack.get("backend", "unknown")
    info = BACKEND_INSTRUCTIONS.get(backend, BACKEND_INSTRUCTIONS.get("django"))
    if not info:
        return ""
    return (
        f"**Stack Backend: {backend.upper()}**\n\n"
        f"Estructura de archivos:\n{info['structure']}\n\n"
        f"Imports típicos:\n```\n{info['imports']}\n```"
    )


def get_frontend_instructions(stack: dict) -> str:
    """Devuelve las instrucciones de estructura para el agente frontend."""
    frontend = stack.get("frontend", "unknown")
    info = FRONTEND_INSTRUCTIONS.get(frontend, FRONTEND_INSTRUCTIONS.get("react"))
    if not info:
        return ""
    return (
        f"**Stack Frontend: {frontend.upper()}**\n\n"
        f"Estructura de archivos:\n{info['structure']}\n\n"
        f"Imports típicos:\n```\n{info['imports']}\n```"
    )


def get_qa_instructions(stack: dict) -> str:
    """Devuelve las instrucciones de testing para el agente QA."""
    lines = []
    backend  = stack.get("backend", "unknown")
    frontend = stack.get("frontend", "unknown")

    if backend in QA_INSTRUCTIONS:
        lines.append(f"**Tests Backend ({backend}):**\n{QA_INSTRUCTIONS[backend]}")
    if frontend in QA_INSTRUCTIONS:
        lines.append(f"\n**Tests Frontend ({frontend}):**\n{QA_INSTRUCTIONS[frontend]}")

    return "\n".join(lines) if lines else ""


def generate_stack_md(
    project_name: str,
    backend: str,
    frontend: str,
    backend_version: str = "",
    frontend_version: str = "",
    database: str = "postgresql",
) -> str:
    """Genera el contenido de un STACK.md nuevo para un proyecto."""
    backend_test = BACKEND_INSTRUCTIONS.get(backend, {}).get("testing", "pytest")
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
