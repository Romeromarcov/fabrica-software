"""
tools/deploy_release.py — Promoción a producción (PLAN_BLINDAJE_TOTAL D3.2).

Núcleo PURO y OFFLINE-VERIFICABLE de la promoción a prod:

  1. **Deploy solo desde `main`** — invariante duro: una promoción a producción
     nunca se dispara desde un feature/branch. `assert_prod_deployable` lo impone.
  2. **Tag/release por promoción** — cada promoción acuña un tag inmutable
     `{prefix}-YYYYMMDD-NN` (secuencia por día). `next_release_tag` lo calcula a
     partir de los tags existentes (sin tocar el reloj: la fecha entra como dato).
  3. **Rollback inmediato = redeploy del tag anterior** — `build_rollback_plan`
     identifica el tag de release previo y arma el comando exacto de un solo paso.

El DISPARO real del deploy/redeploy en Railway (mutación `serviceInstanceDeploy`)
y la lectura de los tags vivos del repo son las aristas de infra que requieren
credenciales (Railway token de deploy + acceso al repo) — fuera de este módulo.
Aquí solo se DECIDE qué taggear y a qué tag volver, dado ese input.
"""
from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger(__name__)


class ProdDeployError(RuntimeError):
    """Se intentó promover a producción desde una rama no autorizada."""


def _prod_branch() -> str:
    try:
        from config import PROD_DEPLOY_BRANCH
        return PROD_DEPLOY_BRANCH
    except ImportError:
        logger.warning("config no importable; rama de prod por defecto 'main'")
        return "main"


def _tag_prefix() -> str:
    try:
        from config import RELEASE_TAG_PREFIX
        return RELEASE_TAG_PREFIX
    except ImportError:
        logger.warning("config no importable; prefijo de release por defecto 'release'")
        return "release"


def assert_prod_deployable(branch: str) -> bool:
    """Impone el invariante D3.2: deploy a prod solo desde la rama de producción.

    Lanza `ProdDeployError` si `branch` no es la rama autorizada. Devuelve True
    cuando sí lo es, para uso en aserciones de guardas previas al deploy.
    """
    prod = _prod_branch()
    if (branch or "").strip() != prod:
        raise ProdDeployError(
            f"Deploy a producción solo permitido desde '{prod}', no desde '{branch}'."
        )
    return True


def _tag_re() -> re.Pattern:
    # {prefix}-YYYYMMDD-NN  (NN = secuencia del día, ≥ 2 dígitos).
    return re.compile(rf"^{re.escape(_tag_prefix())}-(\d{{8}})-(\d+)$")


def parse_release_tag(tag: str) -> Optional[tuple[str, int]]:
    """Extrae `(YYYYMMDD, seq)` de un tag de release; None si no encaja el patrón."""
    m = _tag_re().match((tag or "").strip())
    if not m:
        return None
    return m.group(1), int(m.group(2))


def sorted_release_tags(tags: list[str]) -> list[str]:
    """Filtra los tags que son de release y los ordena cronológicamente ascendente.

    Orden por `(fecha, secuencia)` — determinista y estable frente a tags ajenos
    (vX.Y.Z, etc.), que se descartan.
    """
    parsed = []
    for t in tags or []:
        p = parse_release_tag(t)
        if p is not None:
            parsed.append((p[0], p[1], t.strip()))
    parsed.sort(key=lambda x: (x[0], x[1]))
    return [t for _, _, t in parsed]


def next_release_tag(existing_tags: list[str], today: str) -> str:
    """Calcula el próximo tag de release para la fecha `today` (YYYYMMDD).

    La secuencia se reinicia por día: si ya hay `release-20260618-01`, el próximo
    del mismo día es `release-20260618-02`. `today` entra como dato (no se lee el
    reloj) para que la función sea pura y testeable.
    """
    today = (today or "").strip()
    if not re.fullmatch(r"\d{8}", today):
        raise ValueError(f"`today` debe ser YYYYMMDD, recibido: {today!r}")
    max_seq = 0
    for t in existing_tags or []:
        p = parse_release_tag(t)
        if p is not None and p[0] == today:
            max_seq = max(max_seq, p[1])
    return f"{_tag_prefix()}-{today}-{max_seq + 1:02d}"


def previous_release_tag(
    existing_tags: list[str], current_tag: Optional[str] = None
) -> Optional[str]:
    """Tag de release inmediatamente anterior — el objetivo de rollback.

    Sin `current_tag`: devuelve el penúltimo release (el anterior al más reciente).
    Con `current_tag`: devuelve el release que lo precede en la secuencia. None si
    no hay un tag anterior (no se puede hacer rollback hacia atrás).
    """
    ordered = sorted_release_tags(existing_tags)
    if not ordered:
        return None
    if current_tag is None:
        return ordered[-2] if len(ordered) >= 2 else None
    current_tag = current_tag.strip()
    if current_tag in ordered:
        idx = ordered.index(current_tag)
        return ordered[idx - 1] if idx >= 1 else None
    # current_tag no está en la lista (aún no acuñado): el anterior es el último.
    return ordered[-1]


def build_rollback_plan(
    existing_tags: list[str], current_tag: Optional[str] = None
) -> dict:
    """Arma el plan de rollback de un paso: redeploy del tag de release anterior.

    Returns {"can_rollback", "target_tag", "command", "reason"}.
    El `command` es el one-liner documentado del rollback (checkout del tag previo
    + redeploy en Railway); el disparo real vive en railway_client (infra).
    """
    target = previous_release_tag(existing_tags, current_tag)
    if target is None:
        return {
            "can_rollback": False,
            "target_tag": None,
            "command": None,
            "reason": "No hay un tag de release anterior al que volver.",
        }
    command = f"git checkout {target} && railway up --detach"
    return {
        "can_rollback": True,
        "target_tag": target,
        "command": command,
        "reason": f"Rollback inmediato → redeploy del tag de release anterior ({target}).",
    }


@dataclass
class ReleaseRecord:
    """Metadata inmutable de una promoción a producción."""

    tag: str
    sha: str
    branch: str
    created_at: str  # ISO-8601, provisto por el llamante (no se lee el reloj aquí)
    features: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {
            "tag": self.tag,
            "sha": self.sha,
            "branch": self.branch,
            "created_at": self.created_at,
            "features": list(self.features),
        }


def build_release_record(
    *,
    existing_tags: list[str],
    today: str,
    sha: str,
    branch: str,
    created_at: str,
    features: Optional[list[str]] = None,
) -> ReleaseRecord:
    """Construye el `ReleaseRecord` de una promoción, imponiendo el invariante de rama.

    Acuña el próximo tag para `today` y valida que `branch` sea la rama de producción.
    Lanza `ProdDeployError` si no lo es.
    """
    assert_prod_deployable(branch)
    tag = next_release_tag(existing_tags, today)
    return ReleaseRecord(
        tag=tag,
        sha=sha,
        branch=branch,
        created_at=created_at,
        features=list(features or []),
    )
