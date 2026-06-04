"""
Descubrimiento dinámico de repos de GitHub (API).

Permite que la fábrica liste los repos a los que el token tiene acceso y clone
el que el usuario elija al vuelo (en vez de mantener TARGET_REPOS a mano).
Usa el GITHUB_TOKEN ya configurado.
"""
from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

_API = "https://api.github.com"


def list_user_repos(token: str, limit: int = 200) -> list[dict]:
    """Lista los repos accesibles por el token (owner / colaborador / org)."""
    if not token:
        return []
    import httpx

    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    repos: list[dict] = []
    try:
        with httpx.Client(timeout=20) as c:
            page = 1
            while len(repos) < limit:
                r = c.get(
                    f"{_API}/user/repos",
                    params={
                        "per_page": 100,
                        "page": page,
                        "sort": "updated",
                        "affiliation": "owner,collaborator,organization_member",
                    },
                    headers=headers,
                )
                r.raise_for_status()
                batch = r.json()
                if not batch:
                    break
                for repo in batch:
                    repos.append({
                        "name":           repo["name"],
                        "full_name":      repo["full_name"],
                        "clone_url":      repo["clone_url"],
                        "private":        repo.get("private", False),
                        "default_branch": repo.get("default_branch", "main"),
                    })
                if len(batch) < 100:
                    break
                page += 1
    except Exception as exc:  # noqa: BLE001
        logger.warning("github_repos: error listando repos: %s", exc)
    return repos[:limit]
