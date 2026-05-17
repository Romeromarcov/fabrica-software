"""Operaciones git para el PR Final. El Agente 1 las usa al cerrar el ciclo."""
import subprocess
from pathlib import Path
import logging

logger = logging.getLogger(__name__)


def _run(cmd: list[str], cwd: str | Path) -> tuple[str, str, int]:
    result = subprocess.run(cmd, cwd=str(cwd), capture_output=True, text=True)
    return result.stdout.strip(), result.stderr.strip(), result.returncode


def current_branch(repo_path: str) -> str:
    out, _, _ = _run(["git", "rev-parse", "--abbrev-ref", "HEAD"], repo_path)
    return out


def create_branch(branch_name: str, repo_path: str) -> bool:
    _, err, code = _run(["git", "checkout", "-b", branch_name], repo_path)
    if code != 0:
        logger.error("No se pudo crear la rama: %s", err)
    return code == 0


def stage_all(repo_path: str) -> bool:
    _, err, code = _run(["git", "add", "."], repo_path)
    if code != 0:
        logger.error("git add falló: %s", err)
    return code == 0


def commit(message: str, repo_path: str) -> bool:
    _, err, code = _run(["git", "commit", "-m", message], repo_path)
    if code != 0:
        logger.error("git commit falló: %s", err)
    return code == 0


def create_pr(title: str, body: str, repo_path: str) -> str:
    """Crea el PR en GitHub vía `gh`. Devuelve la URL del PR o mensaje de error."""
    out, err, code = _run(["gh", "pr", "create", "--title", title, "--body", body], repo_path)
    if code != 0:
        logger.error("gh pr create falló: %s", err)
        return f"ERROR: {err}"
    return out  # URL del PR
