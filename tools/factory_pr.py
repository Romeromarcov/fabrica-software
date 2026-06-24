"""
tools/factory_pr.py — capa git/PR para aprobar cambios del Factory Modifier desde la UI.

El fundador eligió: aprobar = aplicar el cambio a una rama, abrir un PR y mergearlo desde la UI
con un botón. Como `main` tiene branch protection (revisor independiente + CI), el merge pasa por
esas compuertas — el blindaje se respeta y la aprobación es un clic.

Este módulo orquesta:
    apply_and_open_pr(proposal)  → crea rama, aplica el cambio, commitea, pushea y abre PR.
    merge_pr(proposal)           → mergea el PR del proposal.

git (subprocess) y la API de GitHub son INYECTABLES (`runner`, `gh`), de modo que la
orquestación se testea con dobles y en producción usa las implementaciones reales (subprocess +
REST con GITHUB_TOKEN). Doble gate heredado: FACTORY_MODIFIER_ENABLED + approved, nunca main.
"""
from __future__ import annotations

import json
import logging
import subprocess
import urllib.request
from pathlib import Path
from typing import Callable, Optional

logger = logging.getLogger(__name__)

PROTECTED_BRANCHES = {"main", "master"}


def _default_runner(args: list[str], cwd: Optional[Path] = None) -> str:
    """Ejecuta un comando git y devuelve stdout; lanza si falla."""
    res = subprocess.run(args, cwd=str(cwd) if cwd else None, capture_output=True,
                         text=True, check=True)
    return res.stdout.strip()


def _default_gh(method: str, path: str, payload: Optional[dict] = None) -> dict:
    """Cliente REST mínimo de GitHub usando GITHUB_TOKEN. method: GET/POST/PUT."""
    import config
    token = getattr(config, "GITHUB_TOKEN", "") or ""
    if not token:
        raise PermissionError("GITHUB_TOKEN no configurado; no se puede operar el PR.")
    url = f"https://api.github.com{path}"
    data = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("Authorization", f"Bearer {token}")
    req.add_header("Accept", "application/vnd.github+json")
    with urllib.request.urlopen(req) as resp:  # noqa: S310 (host fijo de GitHub)
        return json.loads(resp.read().decode() or "{}")


def _repo_slug(runner: Callable = _default_runner, repo_root: Optional[Path] = None) -> str:
    """owner/repo desde config/env (GITHUB_REPO) o, en su defecto, el remoto `origin`."""
    import os
    import config
    slug = getattr(config, "GITHUB_REPO", "") or os.getenv("GITHUB_REPO", "")
    if slug:
        return slug
    try:
        url = runner(["git", "remote", "get-url", "origin"], cwd=repo_root)
        m = url.rstrip("/").removesuffix(".git").split("/")[-2:]
        return "/".join(m) if len(m) == 2 else ""
    except Exception as exc:  # noqa: BLE001
        logger.warning("factory_pr: no se pudo deducir el repo (%s)", exc)
        return ""


def apply_and_open_pr(
    proposal: dict, *,
    approved: bool,
    repo_root: Optional[Path] = None,
    runner: Callable = _default_runner,
    gh: Callable = _default_gh,
    apply_fn: Optional[Callable] = None,
    store_path: Optional[Path] = None,
) -> dict:
    """
    Aplica el cambio del proposal a una rama de trabajo, la pushea y abre un PR. Actualiza el
    estado del proposal a `pr_open` con la URL. Devuelve {branch, pr_url}. Doble gate incluido.
    """
    import config
    from tools import factory_proposals as fp
    from tools.factory_modifier import apply_factory_change

    if not getattr(config, "FACTORY_MODIFIER_ENABLED", False):
        raise PermissionError("FACTORY_MODIFIER_ENABLED está desactivado; aprobación bloqueada.")
    if not approved:
        raise PermissionError("la aprobación requiere approved=True (decisión del fundador).")

    change = proposal["change"]
    branch = proposal.get("branch") or f"factory/proposal-{proposal['id']}"
    if branch in PROTECTED_BRANCHES:
        raise PermissionError("el factory modifier nunca opera sobre main/master.")
    root = Path(repo_root) if repo_root else Path.cwd()

    # Rama de trabajo desde main, aplicar el cambio y commitear.
    runner(["git", "checkout", "-B", branch], cwd=root)
    (apply_fn or apply_factory_change)(
        change, approved=approved, branch=branch, repo_root=root)
    runner(["git", "add", "-A"], cwd=root)
    runner(["git", "commit", "-m",
            f"factory: {change.get('kind')} — {proposal.get('rationale', '')[:60]}"], cwd=root)
    runner(["git", "push", "-u", "origin", branch], cwd=root)

    slug = _repo_slug(runner=runner, repo_root=root)
    body = (f"Propuesta del Factory Modifier (riesgo: {proposal.get('risk')}).\n\n"
            f"{proposal.get('rationale', '')}\n\nEntra por CI + revisor independiente.")
    pr = gh("POST", f"/repos/{slug}/pulls", {
        "title": f"factory: {change.get('kind')} ({proposal['id']})",
        "head": branch, "base": "main", "body": body, "draft": False,
    })
    pr_url = pr.get("html_url") or pr.get("url", "")
    pr_number = pr.get("number")
    fp.set_status(proposal["id"], "pr_open", branch=branch, pr_url=pr_url,
                  pr_number=pr_number, path=store_path)
    logger.info("factory_pr: PR abierto para %s en %s", proposal["id"], pr_url)
    return {"branch": branch, "pr_url": pr_url, "pr_number": pr_number}


def merge_pr(
    proposal: dict, *,
    approved: bool,
    gh: Callable = _default_gh,
    store_path: Optional[Path] = None,
) -> dict:
    """Mergea el PR del proposal (respeta la branch protection de main). Estado → `merged`."""
    import config
    from tools import factory_proposals as fp
    if not getattr(config, "FACTORY_MODIFIER_ENABLED", False):
        raise PermissionError("FACTORY_MODIFIER_ENABLED está desactivado; merge bloqueado.")
    if not approved:
        raise PermissionError("el merge requiere approved=True (decisión del fundador).")
    number = proposal.get("pr_number")
    if not number:
        raise ValueError("el proposal no tiene PR abierto (pr_number ausente).")

    slug = _repo_slug()
    res = gh("PUT", f"/repos/{slug}/pulls/{number}/merge", {"merge_method": "merge"})
    if not res.get("merged"):
        raise RuntimeError(f"GitHub no mergeó el PR #{number}: {res.get('message', 'desconocido')}")
    fp.set_status(proposal["id"], "merged", path=store_path)
    logger.info("factory_pr: PR #%s mergeado (proposal %s)", number, proposal["id"])
    return {"merged": True, "pr_number": number}
