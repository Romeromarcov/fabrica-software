"""
tools/factory_proposals.py — store persistente de propuestas del Factory Modifier.

La auditoría programada de la fábrica genera propuestas de mejora; el fundador las revisa y
aprueba desde la UI. Necesitamos persistirlas (sobreviven reinicios del proceso) con su ciclo
de vida. Estado en un JSON bajo /data (volumen persistente en la nube).

Ciclo de vida de una propuesta:
    pending   → recién generada (o validada), a la espera de decisión.
    applied   → escrita en una rama de trabajo (apply_factory_change), aún sin PR.
    pr_open   → con PR abierto (entra por CI + revisor independiente).
    merged    → PR mergeado a main.
    dismissed → descartada por el fundador.

Sin side effects al importar. La ruta del store es inyectable (tests).
"""
from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

STATUSES = ("pending", "applied", "pr_open", "merged", "dismissed")


def _store_path(path: Optional[Path] = None) -> Path:
    if path is not None:
        return Path(path)
    vol = Path("/data")
    base = vol if vol.is_dir() else Path(__file__).parent.parent / "data"
    return base / "factory_proposals.json"


def _load(path: Optional[Path] = None) -> list[dict]:
    p = _store_path(path)
    if not p.exists():
        return []
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning("factory_proposals: store ilegible (%s); se asume vacío", exc)
        return []


def _save(items: list[dict], path: Optional[Path] = None) -> None:
    p = _store_path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(items, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def add_proposal(change: dict, *, rationale: str = "", risk: str = "high",
                 source: str = "audit", path: Optional[Path] = None) -> dict:
    """Crea una propuesta `pending` y la persiste. Devuelve la propuesta con su id."""
    item = {
        "id": uuid.uuid4().hex[:12],
        "created_at": datetime.now(timezone.utc).isoformat(),
        "change": change,
        "rationale": rationale or change.get("rationale", ""),
        "risk": risk,
        "source": source,
        "status": "pending",
        "branch": None,
        "pr_url": None,
        "history": [],
    }
    items = _load(path)
    items.append(item)
    _save(items, path)
    logger.info("factory_proposals: nueva propuesta %s (risk=%s, source=%s)",
                item["id"], risk, source)
    return item


def list_proposals(status: Optional[str] = None, path: Optional[Path] = None) -> list[dict]:
    """Propuestas (todas o filtradas por estado), más recientes primero."""
    items = _load(path)
    if status:
        items = [i for i in items if i.get("status") == status]
    return sorted(items, key=lambda i: i.get("created_at", ""), reverse=True)


def get_proposal(proposal_id: str, path: Optional[Path] = None) -> Optional[dict]:
    return next((i for i in _load(path) if i.get("id") == proposal_id), None)


def set_status(proposal_id: str, status: str, *, path: Optional[Path] = None, **fields) -> dict:
    """
    Cambia el estado de una propuesta (y campos extra como branch/pr_url), registrando la
    transición en `history`. Lanza si el id no existe o el estado no es válido.
    """
    if status not in STATUSES:
        raise ValueError(f"estado inválido '{status}' (válidos: {STATUSES})")
    items = _load(path)
    item = next((i for i in items if i.get("id") == proposal_id), None)
    if item is None:
        raise KeyError(f"propuesta '{proposal_id}' no encontrada")
    item.setdefault("history", []).append({
        "at": datetime.now(timezone.utc).isoformat(),
        "from": item.get("status"), "to": status,
    })
    item["status"] = status
    for k, v in fields.items():
        item[k] = v
    _save(items, path)
    logger.info("factory_proposals: %s → %s", proposal_id, status)
    return item
