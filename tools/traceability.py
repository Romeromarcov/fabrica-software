"""
tools/traceability.py — Trazabilidad objetivo→backlog→código (PLAN_PLATAFORMA_V2 Fase 9, R5).

Valida que un backlog **cubre** un objetivo: descompone el objetivo en requisitos y mide,
de forma DETERMINISTA (solapamiento de términos significativos), qué requisitos están
cubiertos por al menos un ítem del backlog y cuáles son huecos (gaps). 100% verificable sin
LLM: la descomposición del objetivo es opcional/inyectable (`extract_requirements(llm=)`).

Sin side effects al importar.
"""
from __future__ import annotations

import re
from typing import Callable, Optional

# Términos demasiado genéricos para contar como evidencia de cobertura.
_STOPWORDS = {
    "para", "como", "este", "esta", "esto", "debe", "puede", "todos", "todas", "cada",
    "with", "that", "this", "from", "into", "the", "and", "los", "las", "del", "una", "uno",
    "que", "con", "por", "sus", "sistema", "usuario", "usuarios", "feature", "soporte",
}
_TOKEN_RE = re.compile(r"[a-záéíóúñü0-9]+", re.IGNORECASE)


def _tokens(text: str) -> set[str]:
    toks = {t.lower() for t in _TOKEN_RE.findall(text or "")}
    return {t for t in toks if len(t) >= 4 and t not in _STOPWORDS}


def extract_requirements(objective: str, llm: Optional[Callable[[str], object]] = None) -> list[str]:
    """
    Descompone un objetivo en requisitos. Si se pasa `llm`, se usa su salida (lista o JSON
    string de strings); si no, fallback determinista: una frase por línea / por ';' / '.'.
    """
    if llm is not None:
        import json
        raw = llm(objective)
        if isinstance(raw, str):
            try:
                raw = json.loads(raw)
            except json.JSONDecodeError as exc:
                raise ValueError(f"el LLM no devolvió JSON válido de requisitos: {exc}") from exc
        if not isinstance(raw, list):
            raise ValueError("se esperaba una lista de requisitos del LLM")
        return [str(r).strip() for r in raw if str(r).strip()]
    parts = re.split(r"[\n;.]+", objective or "")
    return [p.strip() for p in parts if p.strip()]


def _covered_by(requirement: str, item_text: str, min_ratio: float) -> bool:
    req = _tokens(requirement)
    if not req:
        return False
    shared = req & _tokens(item_text)
    return len(shared) >= max(1, round(min_ratio * len(req)))


def coverage(requirements: list[str], backlog: list, min_ratio: float = 0.5) -> dict:
    """
    Mide cobertura del backlog sobre los requisitos. `backlog` es una lista de strings o de
    dicts con 'description'/'title'/'id'. Devuelve:
      {covered: [req...], gaps: [req...], mapping: {req: [item_id...]}, coverage_pct: float}
    """
    def _text(item) -> str:
        if isinstance(item, dict):
            return " ".join(str(item.get(k, "")) for k in ("title", "description", "name"))
        return str(item)

    def _id(item, idx) -> str:
        if isinstance(item, dict):
            return str(item.get("id") or item.get("title") or f"item{idx}")
        return f"item{idx}"

    covered, gaps, mapping = [], [], {}
    for req in requirements:
        hits = [_id(it, i) for i, it in enumerate(backlog) if _covered_by(req, _text(it), min_ratio)]
        mapping[req] = hits
        (covered if hits else gaps).append(req)

    total = len(requirements)
    pct = round(100.0 * len(covered) / total, 1) if total else 100.0
    return {"covered": covered, "gaps": gaps, "mapping": mapping, "coverage_pct": pct}


def is_complete(requirements: list[str], backlog: list, min_ratio: float = 0.5) -> bool:
    """True si el backlog cubre TODOS los requisitos (sin gaps)."""
    return not coverage(requirements, backlog, min_ratio)["gaps"]


def format_traceability_report(objective: str, backlog: list,
                               llm: Optional[Callable[[str], object]] = None,
                               min_ratio: float = 0.5) -> str:
    reqs = extract_requirements(objective, llm=llm)
    cov = coverage(reqs, backlog, min_ratio)
    lines = [
        "=== Trazabilidad objetivo→backlog (R5) ===",
        f"Requisitos: {len(reqs)}  Cubiertos: {len(cov['covered'])}  "
        f"Gaps: {len(cov['gaps'])}  Cobertura: {cov['coverage_pct']}%",
    ]
    for g in cov["gaps"]:
        lines.append(f"  ❌ GAP (sin ítem de backlog): {g}")
    if not cov["gaps"]:
        lines.append("  ✅ El backlog cubre el objetivo completo.")
    return "\n".join(lines)
