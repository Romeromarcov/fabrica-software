"""Operaciones git para el PR Final. El Agente 1 las usa al cerrar el ciclo."""
import os
import subprocess
from pathlib import Path
import logging

logger = logging.getLogger(__name__)


def _run(cmd: list[str], cwd: str | Path, env: dict | None = None) -> tuple[str, str, int]:
    merged_env = {**os.environ, **(env or {})}
    result = subprocess.run(cmd, cwd=str(cwd), capture_output=True, text=True, env=merged_env)
    return result.stdout.strip(), result.stderr.strip(), result.returncode


def _github_env() -> dict[str, str]:
    """
    Construye el entorno con GITHUB_TOKEN para que git y gh CLI
    se autentiquen sin intervención manual.
    Lee GITHUB_TOKEN y GITHUB_ACTOR del entorno (configurados vía UI).
    """
    token = os.getenv("GITHUB_TOKEN", "")
    actor = os.getenv("GITHUB_ACTOR", "")
    extra: dict[str, str] = {}
    if token:
        # gh CLI usa GH_TOKEN; git usa la URL con token embebido
        extra["GH_TOKEN"] = token
        extra["GITHUB_TOKEN"] = token
    if actor and token:
        # Configurar credencial HTTP inline para git push
        # git usará https://<actor>:<token>@github.com automáticamente
        extra["GIT_ASKPASS"] = "echo"
        extra["GIT_USERNAME"] = actor
        extra["GIT_PASSWORD"] = token
    return extra


def _configure_remote_auth(repo_path: str) -> None:
    """
    Si GITHUB_TOKEN está definido, reescribe la URL del remote 'origin'
    para incluir el token. Idempotente — si ya tiene token no hace nada.
    """
    token = os.getenv("GITHUB_TOKEN", "")
    actor = os.getenv("GITHUB_ACTOR", "")
    if not token:
        return

    out, _, code = _run(["git", "remote", "get-url", "origin"], repo_path)
    if code != 0 or not out:
        return

    # Sólo reescribir si es HTTPS y no tiene credenciales todavía
    if out.startswith("https://") and "@" not in out:
        # https://github.com/org/repo → https://actor:token@github.com/org/repo
        creds = f"{actor}:{token}@" if actor else f"{token}@"
        new_url = out.replace("https://", f"https://{creds}", 1)
        _run(["git", "remote", "set-url", "origin", new_url], repo_path)
        logger.debug("git_tools: remote 'origin' reescrito con credenciales")


def current_branch(repo_path: str) -> str:
    out, _, _ = _run(["git", "rev-parse", "--abbrev-ref", "HEAD"], repo_path)
    return out


def create_branch(branch_name: str, repo_path: str) -> bool:
    _, err, code = _run(["git", "checkout", "-b", branch_name], repo_path)
    if code != 0:
        logger.error("No se pudo crear la rama: %s", err)
    return code == 0


def stage_all(repo_path: str) -> bool:
    """
    A-05: usa git add con verificación previa.
    Respeta .gitignore; nunca commitea .env, *.key ni archivos de secretos.
    """
    _ensure_gitignore(repo_path)
    _, err, code = _run(["git", "add", "."], repo_path)
    if code != 0:
        logger.error("git add falló: %s", err)
    return code == 0


_SENSITIVE_PATTERNS = [".env", "*.env", ".env.*", "*.key", "*.pem", "secrets/", "*.secret"]


def _ensure_gitignore(repo_path: str) -> None:
    """Garantiza que patrones sensibles estén en .gitignore antes del commit."""
    gitignore = Path(repo_path) / ".gitignore"
    try:
        existing = gitignore.read_text(encoding="utf-8") if gitignore.exists() else ""
        missing = [p for p in _SENSITIVE_PATTERNS if p not in existing]
        if missing:
            with gitignore.open("a", encoding="utf-8") as f:
                f.write("\n# Añadido por Fábrica de Software — archivos sensibles\n")
                f.write("\n".join(missing) + "\n")
            logger.info("git_tools: añadidos %d patrones sensibles a .gitignore", len(missing))
    except Exception as e:
        logger.warning("git_tools: no se pudo actualizar .gitignore: %s", e)


def commit(message: str, repo_path: str) -> bool:
    _, err, code = _run(["git", "commit", "-m", message], repo_path)
    if code != 0:
        logger.error("git commit falló: %s", err)
    return code == 0


def push_branch(branch: str, repo_path: str) -> bool:
    """
    Hace push de la rama al remote 'origin'.
    Usa GITHUB_TOKEN si está configurado.
    """
    _configure_remote_auth(repo_path)
    gh_env = _github_env()
    _, err, code = _run(
        ["git", "push", "--set-upstream", "origin", branch],
        repo_path,
        env=gh_env,
    )
    if code != 0:
        logger.error("git push falló: %s", err)
    return code == 0


def create_pr(title: str, body: str, repo_path: str, base: str = "main") -> str:
    """
    Crea el PR en GitHub vía `gh`.
    Usa GITHUB_TOKEN (GH_TOKEN) para autenticarse sin configuración previa.
    Devuelve la URL del PR o mensaje de error.
    """
    gh_env = _github_env()

    # Intentar push primero si hay token (el PR no se puede crear sin push)
    branch = current_branch(repo_path)
    if os.getenv("GITHUB_TOKEN") and branch not in ("main", "master", ""):
        push_branch(branch, repo_path)

    out, err, code = _run(
        ["gh", "pr", "create",
         "--title", title,
         "--body",  body,
         "--base",  base],
        repo_path,
        env=gh_env,
    )
    if code != 0:
        logger.error("gh pr create falló: %s", err)
        return f"ERROR: {err}"
    return out  # URL del PR
