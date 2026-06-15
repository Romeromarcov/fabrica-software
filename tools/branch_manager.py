"""
VI-2 — Branch Manager: gestión de ramas paralelas y detección de conflictos.

Responsabilidades:
  - Determinar qué features están listos para ejecutar en paralelo
    (dependencias cumplidas, sin bloqueos)
  - Detectar qué archivos modifica cada rama de feature
  - Identificar conflictos potenciales (dos ramas tocan el mismo archivo)
  - Intentar merge automático cuando no hay conflictos
"""
from __future__ import annotations

import subprocess
import logging
from pathlib import Path

logger = logging.getLogger(__name__)


# ── Scheduller de dependencias ────────────────────────────────────────────────

def get_ready_indices(
    backlog: list[dict],
    dependency_graph: dict[str, list[str]],
    max_parallel: int = 2,
) -> list[int]:
    """
    Retorna hasta `max_parallel` índices de features listos para ejecutar:
      - status == "pending"
      - todas sus dependencias en `dependency_graph` están completadas o fallidas

    Un feature fallido se considera "cumplido" a efectos de desbloquear
    dependientes (el dependiente correrá igual, con contexto del fallo).
    """
    completed_names: set[str] = {
        f["name"]
        for f in backlog
        if f.get("status") in ("completed", "failed")
    }

    ready: list[int] = []
    for i, f in enumerate(backlog):
        if f.get("status") != "pending":
            continue
        # A3.4: features importados sin aprobar no entran al lote (anti prompt-injection).
        if f.get("pending_approval"):
            continue
        deps: list[str] = dependency_graph.get(f["name"], f.get("depends_on", []))
        if all(d in completed_names for d in deps):
            ready.append(i)
        if len(ready) >= max_parallel:
            break

    return ready


# ── Inspección de ramas ───────────────────────────────────────────────────────

def get_branch_modified_files(
    branch_name: str,
    repo_path: str,
    base: str = "main",
) -> list[str]:
    """
    Devuelve los archivos modificados en `branch_name` respecto a `base`.
    Usa `git diff --name-only`. Si la rama no existe o el repo no es git, retorna [].
    """
    if not Path(repo_path).exists():
        return []
    try:
        result = subprocess.run(
            ["git", "diff", "--name-only", base, branch_name],
            cwd=repo_path,
            capture_output=True,
            text=True,
            timeout=30,
        )
        if result.returncode == 0:
            return [f.strip() for f in result.stdout.splitlines() if f.strip()]
        logger.debug(
            "branch_manager: git diff salió con %d para %s: %s",
            result.returncode, branch_name, result.stderr[:200],
        )
    except Exception as exc:
        logger.debug("branch_manager: git diff falló para %s: %s", branch_name, exc)
    return []


def get_current_branch(repo_path: str) -> str:
    """Devuelve la rama activa del repo."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            cwd=repo_path, capture_output=True, text=True, timeout=10,
        )
        return result.stdout.strip() or "main"
    except Exception:
        return "main"


# ── Detección de conflictos ───────────────────────────────────────────────────

def detect_file_conflicts(branch_files: dict[str, list[str]]) -> list[dict]:
    """
    Detecta archivos tocados por más de una rama.

    Args:
        branch_files: {feature_name: [archivo1, archivo2, ...]}

    Returns:
        [{"file": str, "branches": [feature_name, ...]}]
    """
    file_to_branches: dict[str, list[str]] = {}
    for branch, files in branch_files.items():
        for f in files:
            file_to_branches.setdefault(f, []).append(branch)

    return [
        {"file": f, "branches": branches}
        for f, branches in file_to_branches.items()
        if len(branches) > 1
    ]


def classify_conflict_severity(conflicts: list[dict]) -> str:
    """
    Clasifica la severidad global de los conflictos.
      HIGH   — archivos de modelos/settings/migrations/schema → escalar al Founder
      MEDIUM — archivos de lógica de negocio
      LOW    — archivos de tests/docs/templates → auto-merge viable
    """
    if not conflicts:
        return "NONE"

    high_keywords = ("models", "settings", "urls", "schema", "migrations", "config")
    medium_keywords = ("views", "serializers", "services", "api", "signals")

    for c in conflicts:
        fpath = c["file"].lower()
        if any(k in fpath for k in high_keywords):
            return "HIGH"

    for c in conflicts:
        fpath = c["file"].lower()
        if any(k in fpath for k in medium_keywords):
            return "MEDIUM"

    return "LOW"


# ── Merge automático ──────────────────────────────────────────────────────────

def merge_branch(
    branch_name: str,
    repo_path: str,
    base_branch: str = "main",
) -> dict:
    """
    Intenta hacer merge de `branch_name` a `base_branch` con `--no-ff`.

    Returns:
        {
            "success": bool,
            "conflicts": [str],   # archivos en conflicto si falló
            "output":   str,      # stdout + stderr resumido
        }
    """
    info: dict = {"success": False, "conflicts": [], "output": ""}

    if not Path(repo_path).is_dir():
        info["output"] = f"Repo no encontrado: {repo_path}"
        return info

    try:
        # Asegurar que estamos en la rama base
        subprocess.run(
            ["git", "checkout", base_branch],
            cwd=repo_path, capture_output=True, timeout=30,
        )

        result = subprocess.run(
            ["git", "merge", "--no-ff", branch_name, "-m",
             f"feat: merge {branch_name} al pipeline paralelo"],
            cwd=repo_path,
            capture_output=True,
            text=True,
            timeout=60,
        )
        info["output"] = (result.stdout + result.stderr)[:2000]

        if result.returncode == 0:
            info["success"] = True
            logger.info("branch_manager: ✅ merge %s → %s", branch_name, base_branch)
        else:
            # Recopilar archivos en conflicto
            status = subprocess.run(
                ["git", "diff", "--name-only", "--diff-filter=U"],
                cwd=repo_path, capture_output=True, text=True, timeout=15,
            )
            info["conflicts"] = [
                f.strip() for f in status.stdout.splitlines() if f.strip()
            ]
            # Abortar el merge para dejar el repo limpio
            subprocess.run(
                ["git", "merge", "--abort"],
                cwd=repo_path, capture_output=True, timeout=15,
            )
            logger.warning(
                "branch_manager: ⚠️ merge %s falló — %d conflictos",
                branch_name, len(info["conflicts"]),
            )

    except subprocess.TimeoutExpired:
        info["output"] = "Timeout en git merge"
        logger.error("branch_manager: timeout en merge de %s", branch_name)
    except Exception as exc:
        info["output"] = str(exc)
        logger.exception("branch_manager: error en merge_branch(%s)", branch_name)

    return info


# ── Reporting ─────────────────────────────────────────────────────────────────

def format_conflict_report(
    conflicts: list[dict],
    branch_files: dict[str, list[str]],
    severity: str = "NONE",
) -> str:
    """Genera un reporte legible de conflictos para el LLM y Telegram."""
    if not conflicts:
        return "✅ Sin conflictos — las ramas del batch tocan archivos diferentes."

    severity_icon = {"HIGH": "🔴", "MEDIUM": "🟡", "LOW": "🟢"}.get(severity, "⚪")
    lines = [
        f"{severity_icon} **{len(conflicts)} conflicto(s) potencial(es) — Severidad: {severity}**\n",
    ]
    for c in conflicts:
        lines.append(f"- `{c['file']}` — afecta: {', '.join(c['branches'])}")

    lines.append("\n**Archivos modificados por rama:**")
    for feature_name, files in branch_files.items():
        if not files:
            continue
        sample = ", ".join(f"`{f}`" for f in files[:4])
        extra = f" (+{len(files) - 4} más)" if len(files) > 4 else ""
        lines.append(f"- **{feature_name}**: {sample}{extra}")

    return "\n".join(lines)
