"""
tools/error_audit.py — Auditoría de manejadores `except` (PLAN_BLINDAJE_TOTAL E3.1).

Clasifica cada `except` del código vía AST en:
  - RERAISE: re-lanza (raise) → error crítico propagado. OK.
  - LOGGED:  registra (logger.*/logging.*/print) o emite al event_bus. OK (best-effort visible).
  - SILENT:  ni re-lanza ni registra → error silencioso. Es lo que E3.1 busca erradicar.

Sin side effects al importar; Python puro (solo stdlib `ast`). Pensado como GATE: el test
asegura que el nº de manejadores SILENT no crece (no se introducen nuevos errores mudos).
"""
from __future__ import annotations

import ast
from dataclasses import dataclass
from pathlib import Path

_LOG_METHODS = {"debug", "info", "warning", "warn", "error", "exception", "critical"}
# Funciones que cuentan como "registro visible" del error.
_VISIBLE_FUNCS = {"print", "emit", "log_event", "capture_exception"}


@dataclass(frozen=True)
class Finding:
    file: str
    lineno: int
    classification: str  # "RERAISE" | "LOGGED" | "SILENT"
    handler: str         # tipo capturado, p.ej. "Exception" o "*"


def _handler_type(node: ast.ExceptHandler) -> str:
    if node.type is None:
        return "*"
    if isinstance(node.type, ast.Name):
        return node.type.id
    if isinstance(node.type, ast.Tuple):
        return ",".join(e.id for e in node.type.elts if isinstance(e, ast.Name))
    return ast.dump(node.type)


def _classify(node: ast.ExceptHandler) -> str:
    has_raise = False
    has_log = False
    for sub in ast.walk(node):
        if isinstance(sub, ast.Raise):
            has_raise = True
        elif isinstance(sub, ast.Call):
            func = sub.func
            if isinstance(func, ast.Attribute) and func.attr in (_LOG_METHODS | _VISIBLE_FUNCS):
                has_log = True
            elif isinstance(func, ast.Name) and func.id in _VISIBLE_FUNCS:
                has_log = True
    if has_raise:
        return "RERAISE"
    if has_log:
        return "LOGGED"
    return "SILENT"


def audit_file(path: str | Path) -> list[Finding]:
    p = Path(path)
    try:
        tree = ast.parse(p.read_text(encoding="utf-8"), filename=str(p))
    except (SyntaxError, UnicodeDecodeError):
        return []
    out: list[Finding] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.ExceptHandler):
            out.append(Finding(str(p), node.lineno, _classify(node), _handler_type(node)))
    return out


def audit_tree(root: str | Path, subdirs: tuple[str, ...] = ("nodes", "tools")) -> list[Finding]:
    root = Path(root)
    findings: list[Finding] = []
    targets: list[Path] = []
    for sd in subdirs:
        targets.extend((root / sd).rglob("*.py"))
    for f in root.glob("*.py"):
        targets.append(f)
    for f in sorted(set(targets)):
        findings.extend(audit_file(f))
    return findings


def silent_handlers(root: str | Path, **kw) -> list[Finding]:
    return [f for f in audit_tree(root, **kw) if f.classification == "SILENT"]


def summarize(findings: list[Finding]) -> dict[str, int]:
    counts = {"RERAISE": 0, "LOGGED": 0, "SILENT": 0}
    for f in findings:
        counts[f.classification] = counts.get(f.classification, 0) + 1
    counts["TOTAL"] = len(findings)
    return counts


def format_report(root: str | Path) -> str:
    findings = audit_tree(root)
    counts = summarize(findings)
    lines = [
        "=== Auditoría except (E3.1) ===",
        f"TOTAL={counts['TOTAL']}  RERAISE={counts['RERAISE']}  "
        f"LOGGED={counts['LOGGED']}  SILENT={counts['SILENT']}",
    ]
    for f in findings:
        if f.classification == "SILENT":
            rel = Path(f.file).name
            lines.append(f"  SILENT  {rel}:{f.lineno}  (except {f.handler})")
    return "\n".join(lines)
