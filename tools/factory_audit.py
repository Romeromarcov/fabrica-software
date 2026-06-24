"""
tools/factory_audit.py — auditoría PROGRAMADA del código de la propia fábrica.

A diferencia de `codebase_auditor` (que audita los repos de los proyectos), este módulo audita
la fábrica y propone MEJORAS concretas como cambios del Factory Modifier (prompt / registry_field).
Las propuestas se persisten (factory_proposals) y el fundador las aprueba desde la UI; las de
bajo riesgo pueden auto-aplicarse a una rama (sin mergear).

Cadencia: por tiempo (lo dispara el scheduler de la UI, como el auditor de código) o por nº de
features ejecutados (`feature_cadence_due`). El LLM es INYECTABLE (mockeable en tests); sin JSON
válido no se inventan propuestas.

Sin side effects al importar.
"""
from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Optional

logger = logging.getLogger(__name__)

_AUDIT_SYSTEM = (
    "Eres un auditor de la FÁBRICA (un sistema multi-agente). Revisa el código y propón mejoras "
    "ACOTADAS y seguras como cambios del Factory Modifier. SOLO dos tipos:\n"
    '  - {"kind":"prompt","target":"agents/<...>.md","mode":"append","content":"...","rationale":"..."}\n'
    '  - {"kind":"registry_field","agent_id":"A4","field":"model","value":"...","rationale":"..."}\n'
    "Devuelve SOLO un array JSON de propuestas (máximo 5). Prioriza mejoras de prompt por append y "
    "ajustes de modelo; evita cambios estructurales. Nada de texto fuera del JSON."
)

_JSON_ARRAY = re.compile(r"\[.*\]", re.DOTALL)


def feature_cadence_due(every_n: int, count_since_last: int) -> bool:
    """True si toca auditar por nº de features (every_n>0 y ya se ejecutaron al menos every_n)."""
    return every_n > 0 and count_since_last >= every_n


def _counter_path(path: Optional[Path] = None) -> Path:
    if path is not None:
        return Path(path)
    vol = Path("/data")
    base = vol if vol.is_dir() else Path(__file__).parent.parent / "data"
    return base / "factory_audit_counter.json"


def _bump_counter(path: Optional[Path] = None) -> int:
    p = _counter_path(path)
    try:
        n = int(json.loads(p.read_text(encoding="utf-8")).get("count", 0))
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        logger.debug("factory_audit: contador ilegible (%s); se reinicia a 0", exc)
        n = 0
    n += 1
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"count": n}), encoding="utf-8")
    return n


def _reset_counter(path: Optional[Path] = None) -> None:
    p = _counter_path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({"count": 0}), encoding="utf-8")


def on_feature_started(*, enabled: bool, mode: str, every_n: int,
                       runner: Optional[Callable] = None,
                       counter_path: Optional[Path] = None, **run_kwargs) -> bool:
    """
    Llamar al iniciar una feature. Si la cadencia es por features y toca (cada N), dispara la
    auditoría y reinicia el contador. Devuelve True si la auditoría se disparó. `runner` es
    inyectable (tests); por defecto run_factory_audit.
    """
    if not enabled or mode != "features":
        return False
    count = _bump_counter(counter_path)
    if not feature_cadence_due(every_n, count):
        return False
    _reset_counter(counter_path)
    (runner or run_factory_audit)(**run_kwargs)
    return True


def _parse_proposals(text: str) -> list[dict]:
    """Extrae el array JSON de propuestas del texto del LLM. [] si no hay JSON válido."""
    if not isinstance(text, str):
        return []
    m = _JSON_ARRAY.search(text)
    if not m:
        return []
    try:
        data = json.loads(m.group(0))
    except json.JSONDecodeError as exc:
        logger.warning("factory_audit: JSON de propuestas inválido (%s)", exc)
        return []
    return [d for d in data if isinstance(d, dict)] if isinstance(data, list) else []


def _default_llm(snapshot: str) -> str:
    """LLM real por defecto (no se usa en tests; se inyecta mock)."""
    from nodes.base import _openai_client
    from config import GLOBAL_DEFAULT_MODEL
    client = _openai_client("google")
    resp = client.chat.completions.create(
        model=GLOBAL_DEFAULT_MODEL,
        messages=[{"role": "system", "content": _AUDIT_SYSTEM},
                  {"role": "user", "content": snapshot}],
        max_tokens=1500,
    )
    return resp.choices[0].message.content or ""


def run_factory_audit(
    *,
    llm: Optional[Callable[[str], object]] = None,
    repo_root: Optional[Path] = None,
    max_files: int = 40,
    auto_apply_low: bool = True,
    approved: bool = True,
    store_path: Optional[Path] = None,
    apply_fn: Optional[Callable] = None,
) -> dict:
    """
    Ejecuta una auditoría de la fábrica: arma un snapshot del código, pide propuestas al LLM,
    valida+clasifica cada una y la persiste como propuesta `pending`. Las de riesgo `low` se
    auto-aplican a una rama de trabajo (si `auto_apply_low`), quedando en estado `applied`.

    Devuelve un resumen {generated, auto_applied, pending, errors}. No abre PRs (eso es de la
    capa de UI/git). `llm`, `apply_fn` y `store_path` son inyectables (tests).
    """
    from tools import factory_proposals as fp
    from tools.factory_modifier import normalize_factory_change, validate_factory_change, risk_level

    root = Path(repo_root) if repo_root else Path.cwd()
    # Snapshot del código (reutiliza el colector del auditor de código).
    try:
        from tools.codebase_auditor import _build_source_snapshot
        snapshot = _build_source_snapshot(str(root), max_files)
    except Exception as exc:  # noqa: BLE001
        logger.warning("factory_audit: no se pudo construir snapshot (%s); se usa vacío", exc)
        snapshot = ""

    raw = (llm or _default_llm)(snapshot)
    proposals = _parse_proposals(raw if isinstance(raw, str) else str(raw))

    summary = {"generated": 0, "auto_applied": 0, "pending": 0, "errors": []}
    for raw_change in proposals:
        change = normalize_factory_change(raw_change)
        errors = validate_factory_change(change)
        if errors:
            summary["errors"].append("; ".join(errors))
            continue
        risk = risk_level(change)
        item = fp.add_proposal(change, rationale=change.get("rationale", ""), risk=risk,
                               source="audit", path=store_path)
        summary["generated"] += 1

        if auto_apply_low and risk == "low":
            branch = f"factory/audit-{datetime.now(timezone.utc):%Y%m%d}-{item['id']}"
            try:
                _apply = apply_fn or _default_apply
                _apply(change, branch=branch, repo_root=root, approved=approved)
                fp.set_status(item["id"], "applied", branch=branch, path=store_path)
                summary["auto_applied"] += 1
            except Exception as exc:  # noqa: BLE001
                logger.warning("factory_audit: auto-apply falló para %s (%s)", item["id"], exc)
                summary["pending"] += 1
        else:
            summary["pending"] += 1

    logger.info("factory_audit: %s", summary)
    return summary


def _default_apply(change: dict, *, branch: str, repo_root: Path, approved: bool) -> dict:
    """Aplica el cambio a una rama vía factory_modifier (gates incluidos)."""
    from tools.factory_modifier import apply_factory_change
    return apply_factory_change(change, approved=approved, branch=branch, repo_root=repo_root)
