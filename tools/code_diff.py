"""
tools/code_diff.py — Diff inteligente (PLAN_PLATAFORMA_V2 M4, Fase 1).

Compara el código de ENTRADA de un agente (lo que recibió) contra su SALIDA (lo que
produjo) para medir cuánto cambió. Si el ratio de cambio supera un umbral, es señal
de que el agente reescribió demasiado (posible sobre-refactor / alucinación) y conviene
escalar/avisar.

Lógica pura sobre `difflib` — sin LLM, sin side effects al importar.
"""
from __future__ import annotations

import difflib
from dataclasses import dataclass, field


@dataclass
class DiffReport:
    change_ratio: float                 # 0.0 (idéntico) … 1.0 (totalmente distinto)
    added_lines: int
    removed_lines: int
    exceeds_threshold: bool
    threshold: float
    summary: list[str] = field(default_factory=list)   # diff unificado (recortado)


def compute_change_ratio(before: str, after: str) -> float:
    """
    Ratio de cambio entre dos textos: 1 - similitud(SequenceMatcher).
    0.0 = idénticos · 1.0 = nada en común. Dos vacíos → 0.0.
    """
    before = before or ""
    after = after or ""
    if not before and not after:
        return 0.0
    ratio = difflib.SequenceMatcher(None, before, after).ratio()
    return round(1.0 - ratio, 4)


def _count_line_changes(before: str, after: str) -> tuple[int, int]:
    before_lines = (before or "").splitlines()
    after_lines = (after or "").splitlines()
    added = removed = 0
    for line in difflib.ndiff(before_lines, after_lines):
        if line.startswith("+ "):
            added += 1
        elif line.startswith("- "):
            removed += 1
    return added, removed


def summarize_diff(before: str, after: str, max_lines: int = 60) -> list[str]:
    """Diff unificado recortado a `max_lines` líneas, para inyectar en prompts/logs."""
    diff = difflib.unified_diff(
        (before or "").splitlines(),
        (after or "").splitlines(),
        fromfile="input", tofile="output", lineterm="",
    )
    out = list(diff)
    if len(out) > max_lines:
        out = out[:max_lines] + [f"... [+{len(out) - max_lines} líneas más]"]
    return out


def diff_report(before: str, after: str, threshold: float = 0.85) -> DiffReport:
    """
    Construye el reporte de diff. `exceeds_threshold` es True si el ratio de cambio
    supera `threshold` (señal de reescritura excesiva que amerita revisión humana).
    """
    ratio = compute_change_ratio(before, after)
    added, removed = _count_line_changes(before, after)
    return DiffReport(
        change_ratio=ratio,
        added_lines=added,
        removed_lines=removed,
        exceeds_threshold=ratio > threshold,
        threshold=threshold,
        summary=summarize_diff(before, after),
    )
