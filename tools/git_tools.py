"""Operaciones git para el PR Final. El Agente 1 las usa al cerrar el ciclo."""
import os
import re
import time
import subprocess
from pathlib import Path
import logging

from tools.log_sanitizer import install_redaction_filter, redact

logger = logging.getLogger(__name__)
# Defensa en profundidad: aunque envolvamos cada valor con redact() abajo,
# instalamos el filtro en el logger del módulo para scrubbing de logs crudos.
install_redaction_filter(logger)


def _run(cmd: list[str], cwd: str | Path, env: dict | None = None) -> tuple[str, str, int]:
    merged_env = {**os.environ, **(env or {})}
    result = subprocess.run(cmd, cwd=str(cwd), capture_output=True, text=True, env=merged_env)
    return result.stdout.strip(), result.stderr.strip(), result.returncode


def _is_tracked(rel_path: str, repo_path: str | Path) -> bool:
    """B3.2: True si `rel_path` está versionado en HEAD (git lo conoce).

    Usa `git ls-files --error-unmatch` que devuelve código 0 sólo si el archivo
    está rastreado. Sirve para decidir entre `git restore` (rastreado) y borrado
    de archivo generado nuevo (no rastreado).
    """
    _, _, code = _run(["git", "ls-files", "--error-unmatch", "--", rel_path], repo_path)
    return code == 0


def restore_paths(
    files: list[str],
    repo_path: str,
    attempts: int = 3,
) -> bool:
    """B3.2: Rollback confiable basado en git para los archivos indicados.

    Para cada archivo:
      • Rastreado en HEAD → `git restore --source=HEAD --staged --worktree -- <f>`
        (revierte staging + working tree al estado del último commit).
      • No rastreado (archivo generado nuevo) → se elimina del working tree.
        Se intenta `git clean -f -- <f>`; si no aplica, se borra el archivo en disco.

    SEGURIDAD: sólo se tocan los archivos explícitamente pasados. Nunca se hace
    `git reset --hard` del árbol completo ni `git clean` de todo el repo.

    Reintentos con backoff exponencial (1s, 2s, 4s…) ante fallos transitorios.

    Devuelve True si TODOS los archivos se restauraron/eliminaron con éxito.
    """
    if not files:
        return True

    # Particionar en rastreados (restore) vs no rastreados (eliminar).
    tracked: list[str] = []
    untracked: list[str] = []
    for f in files:
        rel = f.replace("\\", "/").lstrip("/")
        if not rel:
            continue
        if _is_tracked(rel, repo_path):
            tracked.append(rel)
        else:
            untracked.append(rel)

    last_err = ""
    for attempt in range(1, attempts + 1):
        ok = True

        # 1) Restaurar archivos rastreados al estado de HEAD.
        if tracked:
            _, err, code = _run(
                ["git", "restore", "--source=HEAD", "--staged", "--worktree", "--"]
                + tracked,
                repo_path,
            )
            if code != 0:
                ok = False
                last_err = err or "git restore devolvió código != 0"

        # 2) Eliminar archivos generados nuevos (no rastreados).
        for rel in untracked:
            # `git clean -f` sólo elimina archivos no rastreados; acotado a este path.
            _, cerr, ccode = _run(["git", "clean", "-f", "--", rel], repo_path)
            full = Path(repo_path) / rel
            if full.exists():
                # Fallback: borrar directamente si git clean no lo removió
                # (p. ej. el path está ignorado por .gitignore → clean lo respeta).
                try:
                    full.unlink()
                except OSError as exc:
                    ok = False
                    last_err = f"no se pudo eliminar {rel}: {exc}"
                else:
                    if ccode != 0:
                        logger.debug(
                            "restore_paths: %s eliminado en disco (git clean: %s)",
                            rel, redact(cerr),
                        )

        if ok:
            logger.info(
                "restore_paths: rollback git OK — %d restaurado(s), %d eliminado(s)",
                len(tracked), len(untracked),
            )
            return True

        # Fallo: backoff exponencial salvo en el último intento.
        if attempt < attempts:
            sleep_s = 2 ** (attempt - 1)  # 1s, 2s, 4s…
            logger.warning(
                "restore_paths: intento %d/%d falló (%s) — reintentando en %ds",
                attempt, attempts, redact(last_err), sleep_s,
            )
            time.sleep(sleep_s)

    logger.error(
        "restore_paths: rollback git FALLÓ tras %d intento(s): %s",
        attempts, redact(last_err),
    )
    return False


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


def _auth_url(url: str, token: str, actor: str = "") -> str:
    """Inyecta el token en una URL https de GitHub para clonar/actualizar sin prompt."""
    if token and url.startswith("https://") and "@" not in url:
        creds = f"{actor}:{token}@" if actor else f"x-access-token:{token}@"
        return url.replace("https://", f"https://{creds}", 1)
    return url


def _default_branch(repo_path: str) -> str:
    out, _, _ = _run(["git", "symbolic-ref", "--short", "refs/remotes/origin/HEAD"], repo_path)
    if out:
        return out.split("/")[-1]
    return "main"


def clone_or_update_repo(
    repo_url: str,
    dest_path: str,
    token: str = "",
    branch: str = "",
    actor: str = "",
) -> bool:
    """Clone-on-startup: clona el repo si no existe; si ya está, hace fetch + reset
    duro a `origin/<branch>` (estado limpio y reproducible para el pipeline).

    Devuelve True si el repo quedó disponible/actualizado.
    """
    dest = Path(dest_path)
    auth = _auth_url(repo_url, token, actor)

    if (dest / ".git").exists():
        # Actualizar repo existente (idempotente entre reinicios del contenedor).
        _run(["git", "remote", "set-url", "origin", auth], dest)
        _, ferr, fcode = _run(["git", "fetch", "origin", "--prune"], dest)
        if fcode != 0:
            logger.warning("clone_or_update: fetch falló en %s: %s", dest, redact(ferr))
            return False
        br = branch or _default_branch(str(dest))
        _run(["git", "checkout", br], dest)
        _, rerr, rcode = _run(["git", "reset", "--hard", f"origin/{br}"], dest)
        if rcode != 0:
            logger.warning("clone_or_update: reset --hard falló en %s: %s", dest, redact(rerr))
            return False
        # Pristine: elimina archivos NO rastreados que quedaron de corridas previas (p. ej.
        # código/tests/.coverage de un feature anterior) para que el PR del feature actual no
        # los arrastre. `-fd` respeta .gitignore → conserva .env, node_modules, .venv ignorados.
        _run(["git", "clean", "-fd"], dest)
        logger.info("clone_or_update: %s actualizado a origin/%s (pristine)", dest.name, br)
        return True

    # Clonar nuevo.
    dest.parent.mkdir(parents=True, exist_ok=True)
    args = ["git", "clone"]
    if branch:
        args += ["--branch", branch]
    args += [auth, str(dest)]
    _, cerr, ccode = _run(args, str(dest.parent))
    if ccode != 0:
        logger.error("clone_or_update: clone de %s falló: %s", redact(repo_url), redact(cerr))
        return False
    logger.info("clone_or_update: %s clonado en %s", redact(repo_url), dest)
    return True


def current_branch(repo_path: str) -> str:
    out, _, _ = _run(["git", "rev-parse", "--abbrev-ref", "HEAD"], repo_path)
    return out


def create_branch(branch_name: str, repo_path: str) -> bool:
    _, err, code = _run(["git", "checkout", "-b", branch_name], repo_path)
    if code != 0:
        logger.error("No se pudo crear la rama: %s", redact(err))
    return code == 0


def create_feature_branch(feature_name: str, repo_path: str, feature_id: str = "") -> str:
    """
    G7: Crea/usa la rama de feature desde la rama actual.
    Devuelve el nombre de la rama, o cadena vacía si falla.
    Si la rama ya existe (reanudación / worktree), hace checkout sin error.

    CTF-FABRICA-001: cuando hay `feature_id`, usa la nomenclatura COMPARTIDA con el
    Merge Coordinator (`feature/<id8>-slug`) para que el merge paralelo encuentre la rama.
    Sin `feature_id`, conserva el esquema histórico `feature/YYYYMMDD-slug`.
    """
    if feature_id:
        from tools.branch_naming import feature_branch_name
        branch_name = feature_branch_name(feature_id, feature_name)
    else:
        from datetime import datetime
        date_str = datetime.utcnow().strftime("%Y%m%d")
        slug = re.sub(r"[^a-z0-9]+", "-", feature_name.lower()).strip("-")[:40]
        branch_name = f"feature/{date_str}-{slug}"

    # Intentar crear; si ya existe, hacer checkout
    _, err, code = _run(["git", "checkout", "-b", branch_name], repo_path)
    if code != 0:
        if "already exists" in err:
            _, _, code2 = _run(["git", "checkout", branch_name], repo_path)
            if code2 == 0:
                logger.info("git_tools: checkout de rama existente '%s'", branch_name)
                return branch_name
        logger.error("git_tools: no se pudo crear/checkout rama '%s': %s", branch_name, redact(err))
        return ""

    logger.info("git_tools: rama feature creada '%s'", branch_name)
    return branch_name


def stage_files(files: list[str], repo_path: str) -> bool:
    """
    G6: Hace git add de los archivos específicos en files_written.
    Más seguro que git add . — solo añade archivos generados por el pipeline.
    Devuelve True si al menos un archivo se añadió con éxito.
    """
    if not files:
        logger.warning("git_tools: stage_files llamado con lista vacía — no hay nada que commitear")
        return False

    _ensure_gitignore(repo_path)

    # Solo archivos que existen en disco
    existing = [f for f in files if (Path(repo_path) / f).exists()]
    if not existing:
        logger.warning("git_tools: ningún archivo de files_written existe en disco")
        return False

    _, err, code = _run(["git", "add", "--"] + existing, repo_path)
    if code != 0:
        logger.error("git add selectivo falló: %s", redact(err))
    return code == 0


def stage_all(repo_path: str) -> bool:
    """
    A-05: usa git add con verificación previa.
    Respeta .gitignore; nunca commitea .env, *.key ni archivos de secretos.
    """
    _ensure_gitignore(repo_path)
    _, err, code = _run(["git", "add", "."], repo_path)
    if code != 0:
        logger.error("git add falló: %s", redact(err))
    return code == 0


_SENSITIVE_PATTERNS = [".env", "*.env", ".env.*", "*.key", "*.pem", "secrets/", "*.secret"]
# Artefactos de build/test que NUNCA deben entrar al PR (los genera el sandbox al correr
# pytest/coverage). Sin esto, `stage_all` (git add .) los barría al commit (p. ej. .coverage).
_ARTIFACT_PATTERNS = [
    ".coverage", "coverage.xml", "htmlcov/", ".pytest_cache/", ".mypy_cache/",
    ".ruff_cache/", "__pycache__/", "*.pyc", ".tox/", "*.egg-info/",
]


def _ensure_gitignore(repo_path: str) -> None:
    """Garantiza que patrones sensibles y de artefactos estén en .gitignore antes del commit."""
    gitignore = Path(repo_path) / ".gitignore"
    try:
        existing = gitignore.read_text(encoding="utf-8") if gitignore.exists() else ""
        missing = [p for p in (_SENSITIVE_PATTERNS + _ARTIFACT_PATTERNS) if p not in existing]
        if missing:
            with gitignore.open("a", encoding="utf-8") as f:
                f.write("\n# Añadido por Fábrica de Software — sensibles + artefactos de build/test\n")
                f.write("\n".join(missing) + "\n")
            logger.info("git_tools: añadidos %d patrones a .gitignore", len(missing))
    except Exception as e:
        logger.warning("git_tools: no se pudo actualizar .gitignore: %s", redact(str(e)))


def commit(message: str, repo_path: str) -> bool:
    _, err, code = _run(["git", "commit", "-m", message], repo_path)
    if code != 0:
        logger.error("git commit falló: %s", redact(err))
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
        logger.error("git push falló: %s", redact(err))
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
        logger.error("gh pr create falló: %s", redact(err))
        return f"ERROR: {err}"
    return out  # URL del PR
