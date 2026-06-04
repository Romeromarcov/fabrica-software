"""
Aislamiento por git worktree para features paralelos (Fase 4.3 del PLAN_HARDENING).

Cuando varios features corren a la vez, escribir todos al MISMO working tree provoca
carreras (un A10 pisa los archivos de otro). Un `git worktree` por feature da a cada hilo
su propio checkout, compartiendo el mismo `.git` (las ramas quedan visibles para el merge).

Diseño defensivo: si el worktree no puede crearse, se devuelve None y el llamador cae a
la conducta anterior (working tree compartido) con un warning — sin romper el pipeline.
"""
from __future__ import annotations

import logging
import shutil
import subprocess
from pathlib import Path

logger = logging.getLogger(__name__)


def _run(cmd: list[str], cwd: str, timeout: int = 60) -> tuple[bool, str]:
    try:
        r = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout)
        return r.returncode == 0, (r.stdout + r.stderr).strip()
    except Exception as e:  # noqa: BLE001
        return False, str(e)


def worktrees_root(repo_path: str) -> Path:
    """Directorio donde viven los worktrees temporales (hermano de .git, ignorado)."""
    return Path(repo_path) / ".fabrica_worktrees"


def _ensure_ignored(repo_path: str) -> None:
    """Garantiza que .fabrica_worktrees/ esté en .gitignore del repo destino."""
    gi = Path(repo_path) / ".gitignore"
    entry = ".fabrica_worktrees/"
    try:
        existing = gi.read_text(encoding="utf-8") if gi.exists() else ""
        if entry not in existing:
            with gi.open("a", encoding="utf-8") as f:
                f.write(f"\n# Fábrica de Software — worktrees temporales\n{entry}\n")
    except Exception:  # noqa: BLE001
        pass


def create_worktree(repo_path: str, branch: str, feature_id: str) -> str | None:
    """Crea un worktree nuevo con una rama `branch` para el feature.

    Devuelve la ruta absoluta del worktree, o None si git no pudo crearlo.
    """
    if not shutil.which("git"):
        logger.warning("worktree: git no disponible — sin aislamiento")
        return None

    root = worktrees_root(repo_path)
    try:
        root.mkdir(parents=True, exist_ok=True)
        _ensure_ignored(repo_path)
    except Exception as e:  # noqa: BLE001
        logger.warning("worktree: no se pudo crear %s: %s", root, e)
        return None

    wt_path = root / feature_id
    if wt_path.exists():
        # Reanudación: ya existe → reutilizar
        return str(wt_path)

    # Crear worktree con rama nueva. Si la rama existe, engancharla sin -b.
    ok, out = _run(["git", "worktree", "add", "-b", branch, str(wt_path)], repo_path)
    if not ok and "already exists" in out:
        ok, out = _run(["git", "worktree", "add", str(wt_path), branch], repo_path)
    if not ok:
        logger.warning("worktree: 'git worktree add' falló (%s) — sin aislamiento", out[:200])
        return None

    logger.info("worktree: creado %s (rama %s)", wt_path, branch)
    return str(wt_path)


def remove_worktree(repo_path: str, wt_path: str) -> bool:
    """Elimina un worktree (no borra la rama, que ya fue mergeada/queda para revisión)."""
    ok, out = _run(["git", "worktree", "remove", "--force", wt_path], repo_path)
    if not ok:
        logger.warning("worktree: no se pudo remover %s: %s", wt_path, out[:200])
    return ok


def prune_worktrees(repo_path: str) -> None:
    """Limpia referencias a worktrees borrados a mano."""
    _run(["git", "worktree", "prune"], repo_path)
