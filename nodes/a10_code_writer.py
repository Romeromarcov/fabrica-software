"""
Agente 10 — Code Writer.

No usa LLM. Toma el código generado por A4 (Backend), A5 (Frontend) y A3 (MCP)
del state, parsea los bloques de archivo y los escribe al filesystem real del repo.

Posición en el pipeline (G1 fix):
  A8 SecOps (limpio) → A10 Code Writer → A9 Sandbox → A11 DevOps [cond] → A1 PR Final
  A9 testea los archivos REALES en disco (no el código del state).

Comportamiento:
  - G9: Lee contenido original de archivos que van a sobrescribirse → files_backup
  - Extrae archivos de backend_code, frontend_code y mcp_tools del state
  - Escribe cada archivo a su ruta relativa dentro de repo_path
  - G2: Si hay modelos Django nuevos (*/models.py), corre makemigrations
  - Registra files_written en el state para que A1 pueda hacer git add + commit
  - Detecta si A11 DevOps es necesario (hay archivos escritos o proyecto nuevo)
  - Si WRITE_TO_REPO=false: dry-run (loguea sin escribir, pipeline continúa)
"""
from __future__ import annotations

import logging
import subprocess
from pathlib import Path

from state import FabricaState
from tools.code_writer import write_files
from tools.file_tools import save_agent_output

logger = logging.getLogger(__name__)


def _run_makemigrations(repo_path: str) -> tuple[list[str], str]:
    """
    G2: Corre 'python manage.py makemigrations', captura archivos nuevos generados.
    Devuelve (nuevos_archivos_migracion, stdout).
    """
    manage_py = Path(repo_path) / "manage.py"
    if not manage_py.exists():
        return [], ""

    # Snapshot de migration dirs antes
    before: set[str] = set()
    for p in Path(repo_path).rglob("migrations/*.py"):
        try:
            before.add(str(p.relative_to(repo_path)).replace("\\", "/"))
        except ValueError:
            pass

    result = subprocess.run(
        ["python", "manage.py", "makemigrations"],
        cwd=repo_path,
        capture_output=True,
        text=True,
        timeout=120,
    )

    if result.returncode != 0:
        logger.warning("makemigrations falló: %s", result.stderr[:500])
        return [], f"makemigrations error:\n{result.stderr[:500]}"

    # Snapshot después
    after: set[str] = set()
    for p in Path(repo_path).rglob("migrations/*.py"):
        try:
            after.add(str(p.relative_to(repo_path)).replace("\\", "/"))
        except ValueError:
            pass

    new_files = sorted(after - before)
    logger.info("makemigrations: %d archivos nuevos generados", len(new_files))
    return new_files, result.stdout


def a10_code_writer(state: FabricaState) -> dict:
    repo_path  = state["repo_path"]
    feature_id = state["feature_id"]

    sources = {
        "backend":  state.get("backend_code"),
        "frontend": state.get("frontend_code"),
        "mcp":      state.get("mcp_tools"),
        # DevOps output (si A10 corre en segundo pass tras A11)
        "devops":   state.get("devops_output"),
    }

    result        = write_files(repo_path=repo_path, sources=sources)
    files_written = result["files_written"]
    files_skipped = result["files_skipped"]
    errors        = result["errors"]
    files_backup  = result.get("files_backup", {})   # G9

    # ── G2: Makemigrations si hay modelos Django nuevos ───────────────────────
    migration_note = state.get("migration_note") or ""
    model_files = [f for f in files_written if f.endswith("models.py")]
    if model_files:
        logger.info("A10: detectados %d models.py → ejecutando makemigrations", len(model_files))
        new_migrations, mig_stdout = _run_makemigrations(repo_path)
        if new_migrations:
            files_written = list(files_written) + new_migrations
            migration_note = (
                f"makemigrations generó {len(new_migrations)} archivo(s):\n"
                + "\n".join(f"  - {f}" for f in new_migrations)
                + (f"\n\nStdout:\n{mig_stdout}" if mig_stdout else "")
            )
        elif mig_stdout:
            migration_note = f"makemigrations (sin archivos nuevos):\n{mig_stdout}"

    # ── Resumen legible para el panel ─────────────────────────────────────────
    lines = [
        "## Agente 10 — Code Writer",
        "",
        f"**Repositorio:** `{repo_path}`",
        f"**Archivos escritos:** {len(files_written)}",
        f"**Archivos omitidos (seguridad/extensión):** {len(files_skipped)}",
        f"**Archivos con backup (G9):** {len(files_backup)}",
        f"**Errores:** {len(errors)}",
        "",
    ]

    if files_written:
        lines.append("### ✅ Archivos escritos")
        for f in sorted(files_written):
            lines.append(f"- `{f}`")
        lines.append("")

    if migration_note:
        lines.append("### 🗄️ Migraciones Django")
        lines.append(migration_note)
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
        "A10 CodeWriter: %d escritos | %d omitidos | %d errores | %d backups",
        len(files_written), len(files_skipped), len(errors), len(files_backup),
    )

    # ── Decidir si A11 DevOps debe correr ─────────────────────────────────────
    # Activar si:
    #   • Hay archivos escritos (pueden requerir nuevas dependencias)
    #   • El feature está en modo completo (probablemente tiene modelos/deps nuevas)
    needs_devops = bool(files_written) or state.get("mode") == "completo"

    # ── II-1: Actualizar fingerprint con los archivos nuevos ──────────────────
    if files_written:
        try:
            from tools.repo_scanner import update_fingerprint
            update_fingerprint(repo_path, list(files_written))
        except Exception as _fp_exc:
            logger.warning("update_fingerprint: %s", _fp_exc)

    # ── II-3: Registrar rollbacks en session_memory si hubo backups ───────────
    if files_backup and state.get("project_id"):
        try:
            from tools.session_memory import record_rollback
            record_rollback(
                project_id=state["project_id"],
                feature_id=feature_id,
                feature_name=state.get("feature_name", feature_id),
                reason="Archivos sobreescritos con backup previo (G9)",
                files_affected=list(files_backup.keys()),
            )
        except Exception as _roll_exc:
            logger.warning("session_memory record_rollback: %s", _roll_exc)

    return {
        "files_written":  list(files_written),
        "files_backup":   files_backup,
        "migration_note": migration_note or None,
        "needs_devops":   needs_devops,
        "current_agent":  "a10_code_writer",
        "errors":         errors,
    }
