"""
Nomenclatura de ramas de feature — ÚNICA fuente de verdad (CTF-FABRICA-001).

Antes, `a1_pr_final.create_feature_branch` usaba `feature/YYYYMMDD-slug` y
`merge_coordinator._derive_branch_name` usaba `feature/<id8>-slug`: divergían, así que el
merge paralelo buscaba una rama que nunca se creó. Esta función la usan A1 PR Final, el
Merge Coordinator y el aislamiento por worktree, garantizando que todos coincidan.
"""
from __future__ import annotations

import re


def feature_slug(feature_name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", (feature_name or "").lower()).strip("-")[:30]


def feature_branch_name(feature_id: str, feature_name: str) -> str:
    """Rama determinista a partir de (feature_id, feature_name).

    `feature/<YYYYMMDD-HHMMSS>-<slug>`. F6: antes usaba `feature_id[:8]`, que es SOLO la fecha
    (`YYYYMMDD`) — dos runs del mismo feature el mismo día colisionaban en el mismo nombre de
    rama → el push del segundo era non-fast-forward y fallaba. Se usa `feature_id[:15]`
    (`YYYYMMDD_HHMMSS`), único por run hasta el segundo.
    """
    raw = (feature_id or "")[:15] or "feat"        # 20260627_212635
    prefix = raw.replace("_", "-")                  # 20260627-212635
    return f"feature/{prefix}-{feature_slug(feature_name)}"[:60]
