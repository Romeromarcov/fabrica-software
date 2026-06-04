#!/usr/bin/env python3
"""
Clone-on-startup de los repos destino (TARGET_REPOS) en WORKSPACES_ROOT.

Se invoca desde entrypoint.sh al arrancar el contenedor en Railway/VPS: el filesystem
es efímero, así que el repo (p. ej. omni-erp) se clona/actualiza en cada arranque.
El GITHUB_TOKEN se inyecta solo en runtime (nunca en código).
"""
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from config import WORKSPACES_ROOT, parse_target_repos  # noqa: E402
from tools.git_tools import clone_or_update_repo          # noqa: E402


def main() -> int:
    repos = parse_target_repos()
    if not repos:
        print("[clone_targets] TARGET_REPOS vacío — nada que clonar.")
        return 0

    token = os.getenv("GITHUB_TOKEN", "")
    actor = os.getenv("GITHUB_ACTOR", "")
    Path(WORKSPACES_ROOT).mkdir(parents=True, exist_ok=True)

    failures = 0
    for r in repos:
        dest = Path(WORKSPACES_ROOT) / r["name"]
        ok = clone_or_update_repo(
            r["url"], str(dest), token=token, branch=r.get("branch", ""), actor=actor
        )
        print(f"[clone_targets] {r['name']}: {'OK' if ok else 'FALLO'} → {dest}")
        failures += 0 if ok else 1

    # No abortar el arranque por un fallo de clonado (la UI sigue disponible);
    # se reporta para diagnóstico.
    return 0 if failures == 0 else 0


if __name__ == "__main__":
    sys.exit(main())
