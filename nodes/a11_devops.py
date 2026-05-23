"""
Agente 11 — DevOps / Infrastructure.

Posición en el pipeline:
  A10 Code Writer → A11 DevOps [condicional] → A1 PR Final

Se activa únicamente cuando needs_devops=True (detectado por A10).

Responsabilidades:
  1. Actualizar requirements.txt / package.json con dependencias nuevas
  2. Documentar nuevas variables de entorno en .env.example
  3. Para proyectos nuevos (sin Dockerfile): generar Dockerfile, docker-compose.yml
     y pipeline CI/CD básico (.github/workflows/ci.yml)
  4. Añadir nota de migraciones al estado si hay nuevos modelos Django

El output usa el mismo formato de marcadores de archivo que A4/A5 para que
el mismo parser de code_writer pueda aplicar los cambios al filesystem.
"""
from __future__ import annotations

import logging
from pathlib import Path

from state import FabricaState
from nodes.base import call_agent
from tools.code_writer import write_files
from tools.file_tools import save_agent_output
from config import MODEL_A11

logger = logging.getLogger(__name__)


def _read_file(repo: Path, rel_path: str) -> str:
    """Lee un archivo del repo; devuelve '' si no existe."""
    p = repo / rel_path
    try:
        return p.read_text(encoding="utf-8") if p.exists() else ""
    except Exception:
        return ""


def a11_devops(state: FabricaState) -> dict:
    repo_path  = state["repo_path"]
    feature_id = state["feature_id"]
    repo       = Path(repo_path)

    # ── Leer archivos de infraestructura actuales del repo ────────────────────
    requirements_txt = _read_file(repo, "requirements.txt")
    package_json     = _read_file(repo, "package.json")
    env_example      = _read_file(repo, ".env.example")
    dockerfile       = _read_file(repo, "Dockerfile")
    ci_yml           = _read_file(repo, ".github/workflows/ci.yml")

    is_new_project   = not requirements_txt and not package_json
    has_docker       = bool(dockerfile)
    has_ci           = bool(ci_yml)

    # ── Construir prompt ──────────────────────────────────────────────────────
    new_project_section = ""
    if is_new_project:
        new_project_section = """
## PROYECTO NUEVO — sin infraestructura existente

El repositorio no tiene requirements.txt ni package.json.
Debes CREAR desde cero:
1. requirements.txt con las dependencias detectadas en el código
2. package.json si hay código frontend
3. Dockerfile multi-stage (backend + frontend si aplica)
4. docker-compose.yml básico
5. .github/workflows/ci.yml con linting y tests
"""
    elif not has_docker:
        new_project_section = """
## SIN DOCKERFILE

El proyecto existe pero no tiene Dockerfile.
Genera uno basándote en el stack detectado en requirements.txt / package.json.
"""

    task = f"""
Eres el Agente 11 — DevOps / Infrastructure.

Tu tarea: revisar el código nuevo generado por el pipeline y actualizar
los archivos de infraestructura del proyecto para que todo funcione correctamente.
{new_project_section}

## CÓDIGO GENERADO EN ESTE CICLO

### Backend (Agente 4):
```
{(state.get("backend_code") or "")[:4000]}
```

### Frontend (Agente 5):
```
{(state.get("frontend_code") or "")[:3000]}
```

### MCP Tools (Agente 3):
```
{(state.get("mcp_tools") or "")[:2000]}
```

## INFRAESTRUCTURA ACTUAL DEL REPO

### requirements.txt (actual):
```
{requirements_txt or "(no existe)"}
```

### package.json (actual):
```
{package_json[:2000] if package_json else "(no existe)"}
```

### .env.example (actual):
```
{env_example[:1500] if env_example else "(no existe)"}
```

## TU TAREA

**PASO 1 — Detectar nuevas dependencias Python**
Analiza el backend_code y busca:
- `import X` o `from X import` que no estén en requirements.txt actual
- Solo dependencias de terceros (no stdlib, no Django built-ins)
- Pinea versiones realistas (ej: `djangorestframework>=3.14,<4.0`)

**PASO 2 — Detectar nuevas dependencias JS/TS**
Analiza el frontend_code y busca:
- `import X from 'X'` que no estén en package.json
- Distingue devDependencies (testing, types, build) de dependencies (runtime)

**PASO 3 — Detectar nuevas variables de entorno**
Busca patrones como:
- Python: `os.getenv("NOMBRE_VAR")`, `settings.NOMBRE_VAR` nuevo
- TypeScript: `process.env.NOMBRE_VAR`, `import.meta.env.VITE_X`
Documenta cada variable nueva en `.env.example` con comentario explicativo.

**PASO 4 — Actualizar/crear archivos de infraestructura**

Para CADA archivo que necesite cambios, usa EXACTAMENTE este formato:

```[extensión]
# === requirements.txt ===
[contenido completo del archivo actualizado]
```

```json
# === package.json ===
[contenido completo del package.json actualizado]
```

```
# === .env.example ===
[contenido completo del .env.example actualizado]
```

Si el proyecto no tiene Dockerfile o CI:
```dockerfile
# === Dockerfile ===
[Dockerfile multi-stage completo]
```

```yaml
# === docker-compose.yml ===
[docker-compose.yml completo]
```

```yaml
# === .github/workflows/ci.yml ===
[GitHub Actions CI/CD básico: lint + tests]
```

**REGLAS:**
- Solo entrega archivos que realmente necesiten cambios
- Si requirements.txt / package.json no necesitan cambios, no los incluyas
- Cada archivo debe ser el contenido COMPLETO (no diffs, no parches)
- Si detectas que hay migraciones Django nuevas, incluye al final:

```
NOTA DE MIGRACIONES: [describe qué modelos nuevos requieren makemigrations]
```

**CRITERIO DE FINALIZACIÓN:**
La última línea de tu respuesta debe ser:
- `✅ DEVOPS COMPLETADO` — sin problemas
- `⚠️ DEVOPS PARCIAL: [razón]` — se hizo lo posible pero hay limitaciones
"""

    output, cost = call_agent(
        agent_key="a11_devops",
        agent_label="Agente 11 DevOps",
        task_content=task,
        model=MODEL_A11,
        repo_path=repo_path,
    )
    save_agent_output(feature_id, "a11_devops", output)

    # ── Aplicar archivos generados por A11 al repo ────────────────────────────
    infra_result = write_files(
        repo_path=repo_path,
        sources={"devops": output},
    )
    new_files = infra_result["files_written"]
    logger.info("A11 DevOps: %d archivos de infraestructura actualizados", len(new_files))

    # ── Extraer nota de migraciones si la hay ─────────────────────────────────
    migration_note = ""
    if "NOTA DE MIGRACIONES:" in output:
        for line in output.splitlines():
            if "NOTA DE MIGRACIONES:" in line:
                migration_note = line.replace("NOTA DE MIGRACIONES:", "").strip()
                break

    approved = "✅ DEVOPS COMPLETADO" in output or "⚠️ DEVOPS PARCIAL" in output

    return {
        "devops_output":     output,
        "files_written":     infra_result["files_written"],
        "migration_note":    migration_note,
        "current_agent":     "a11_devops",
        "cost_entries":      [cost],
        "errors":            infra_result["errors"],
    }
