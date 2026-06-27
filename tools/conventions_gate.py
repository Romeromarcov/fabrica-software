"""
tools/conventions_gate.py — Gate de convenciones del repo (PLAN_MAESTRO F3.2).

Verifica que el código generado respete las CONVENCIONES reales del repo destino (detectadas
de muestras), no solo que compile/pase tests. Complementa el gate de regresión: ese protege la
funcionalidad; este protege la consistencia con el código existente.

Diseño conservador (un gate que bloquea de más es peor que no tenerlo): solo reglas de ALTA
confianza, derivadas de patrones inequívocos del repo, y detectables por regex sobre el código
nuevo. Puro y testeable; sin side effects al importar.
"""
from __future__ import annotations

import logging
import re
from pathlib import Path

logger = logging.getLogger(__name__)

_SKIP_DIRS = {".git", "node_modules", "__pycache__", ".venv", "venv", "dist", "build", "migrations"}

# Convención: logger de módulo con __name__.
_REPO_MODULE_LOGGER_RE = re.compile(r"logger\s*=\s*logging\.getLogger\(__name__\)")
# Violación: getLogger con un string literal en vez de __name__.
_CODE_BAD_LOGGER_RE = re.compile(r"logging\.getLogger\(\s*['\"]")

# Convención: FKs con prefijo id_  (id_empresa = models.ForeignKey(...)).
_REPO_FK_PREFIX_RE = re.compile(r"\bid_\w+\s*=\s*models\.ForeignKey")
# Cualquier FK declarada (para comprobar el prefijo del nombre del campo).
_CODE_FK_RE = re.compile(r"\b(\w+)\s*=\s*models\.ForeignKey")


def _iter_py(root: Path, cap: int):
    n = 0
    for p in root.glob("**/*.py"):
        if any(part in _SKIP_DIRS for part in p.relative_to(root).parts):
            continue
        yield p
        n += 1
        if n >= cap:
            return


def detect_conventions(repo_path: str) -> dict:
    """Detecta qué convenciones de ALTA confianza sigue el repo (estructurado)."""
    conv = {"module_logger": False, "fk_id_prefix": False}
    root = Path(repo_path)
    if not root.is_dir():
        return conv
    for py in _iter_py(root, cap=60):
        try:
            content = py.read_text(encoding="utf-8", errors="ignore")
        except OSError as exc:
            logger.debug("conventions_gate: no se pudo leer %s (%s)", py, exc)
            continue
        if not conv["module_logger"] and _REPO_MODULE_LOGGER_RE.search(content):
            conv["module_logger"] = True
        if not conv["fk_id_prefix"] and _REPO_FK_PREFIX_RE.search(content):
            conv["fk_id_prefix"] = True
        if conv["module_logger"] and conv["fk_id_prefix"]:
            break
    return conv


def check_code(code_text: str, conventions: dict) -> list[dict]:
    """Devuelve las violaciones de convención en `code_text` según `conventions`."""
    violations: list[dict] = []
    if not code_text:
        return violations

    if conventions.get("module_logger") and _CODE_BAD_LOGGER_RE.search(code_text):
        violations.append({
            "rule": "module_logger",
            "message": "El repo usa `logger = logging.getLogger(__name__)`; "
                       "no uses `getLogger('string-literal')`.",
        })

    if conventions.get("fk_id_prefix"):
        for m in _CODE_FK_RE.finditer(code_text):
            field = m.group(1)
            if not field.startswith("id_"):
                violations.append({
                    "rule": "fk_id_prefix",
                    "message": f"FK `{field}` debería usar el prefijo `id_` "
                               f"(convención del repo: `id_{field} = models.ForeignKey(...)`).",
                })
    return violations


def conventions_report(repo_path: str, code_text: str) -> dict:
    """Detecta convenciones del repo y verifica el código nuevo. `ok=True` si no hay violaciones."""
    conv = detect_conventions(repo_path)
    if not any(conv.values()):
        return {"ok": True, "violations": [], "conventions": conv, "checked": False}
    violations = check_code(code_text, conv)
    return {"ok": not violations, "violations": violations, "conventions": conv, "checked": True}


def format_block_message(report: dict) -> str:
    """Mensaje para alimentar al agente corrector (A6)."""
    vs = report.get("violations", [])
    if not vs:
        return ""
    lines = ["⚠️ GATE DE CONVENCIONES: el código nuevo se desvía de las convenciones del repo:"]
    for v in vs:
        lines.append(f"  - [{v['rule']}] {v['message']}")
    lines.append("Ajústalo para seguir las convenciones existentes (no inventes un estilo nuevo).")
    return "\n".join(lines)
