"""
Agente 10 — Code Writer.

No usa LLM. Toma el código generado por A4 (Backend), A5 (Frontend) y A3 (MCP)
del state, parsea los bloques de archivo y los escribe al filesystem real del repo.

Posición en el pipeline:
  A9 Sandbox (passed) → A10 Code Writer → A11 DevOps [condicional] → A1 PR Final

Comportamiento:
  - Extrae archivos de backend_code, frontend_code y mcp_tools del state
  - Escribe cada archivo a su ruta relativa dentro de repo_path
  - Registra files_written en el state para que A1 pueda hacer git add + commit
  - Detecta si A11 DevOps es necesario (hay archivos escritos o proyecto nuevo)
  - Si WRITE_TO_REPO=false: dry-run (loguea sin escribir, pipeline continúa)
"""
from __future__ import annotations

import logging
from state import FabricaState
from tools.code_writer import write_files
from tools.file_tools import save_agent_output

logger = logging.getLogger(__name__)


def a10_code_writer(state: FabricaState) -> dict:
    repo_path  = state["repo_path"]
    feature_id = state["feature_id"]

    sources = {
        "backend":  state.get("backend_code"),
        "frontend": state.get("frontend_code"),
        "mcp":      state.get("mcp_tools"),
    }

    result       = write_files(repo_path=repo_path, sources=sources)
    files_written = result["files_written"]
    files_skipped = result["files_skipped"]
    errors        = result["errors"]

    # ── Resumen legible para el panel ─────────────────────────────────────────
    lines = [
        "## Agente 10 — Code Writer",
        "",
        f"**Repositorio:** `{repo_path}`",
        f"**Archivos escritos:** {len(files_written)}",
        f"**Archivos omitidos (seguridad/extensión):** {len(files_skipped)}",
        f"**Errores:** {len(errors)}",
        "",
    ]

    if files_written:
        lines.append("### ✅ Archivos escritos")
        for f in sorted(files_written):
            lines.append(f"- `{f}`")
        lines.append("")

    if files_skipped:
        lines.append("### ⚠️ Omitidos")
        for f in sorted(files_skipped):
            lines.append(f"- `{f}`")
        lines.append("")

    if errors:
        lines.append("### ❌ Errores")
        for e in errors:
            lines.append(f"- {e}")

    summary = "\n".join(lines)
    save_agent_output(feature_id, "a10_code_writer", summary)

    logger.info(
        "A10 CodeWriter: %d escritos | %d omitidos | %d errores",
        len(files_written), len(files_skipped), len(errors),
    )

    # ── Decidir si A11 DevOps debe correr ─────────────────────────────────────
    # Activar si:
    #   • Hay archivos escritos (pueden requerir nuevas dependencias)
    #   • El feature está en modo completo (probablemente tiene modelos/deps nuevas)
    needs_devops = bool(files_written) or state.get("mode") == "completo"

    return {
        "files_written":   files_written,
        "needs_devops":    needs_devops,
        "current_agent":   "a10_code_writer",
        "errors":          errors,
    }
