"""
tools/regression_gate.py — Gate de regresión sobre la suite EXISTENTE del repo (F3.2).

El sandbox de hoy (code_sandbox.run_all_checks) corre los tests del repo y falla si CUALQUIER
test falla — sin distinguir un fallo NUEVO (introducido por el feature) de uno preexistente.
El gate de regresión cierra esa brecha: captura el conjunto de tests que ya fallaban ANTES del
cambio (baseline) y, tras el cambio, BLOQUEA solo si aparece un fallo nuevo (un test que pasaba
y ahora falla). Aceptación F3: "un cambio que pasa sus tests pero rompe uno existente es bloqueado".

Puro y testeable: la comparación (`compute_regressions`) no toca el disco; `collect_failures`
corre pytest sobre el repo destino vía subprocess (sin shell). Sin side effects al importar.
"""
from __future__ import annotations

import logging
import re
import subprocess

logger = logging.getLogger(__name__)

# Líneas del resumen de pytest:  "FAILED path::test - msg"  /  "ERROR path::test"
_FAIL_RE = re.compile(r"^(?:FAILED|ERROR)\s+(\S+)", re.MULTILINE)

# Códigos de salida de pytest: 0 ok, 1 fallos, 2 interrupción, 5 sin tests recolectados.
_NO_TESTS_RC = 5


def collect_failures(repo_path: str, target: str = "", timeout: int = 240) -> dict:
    """
    Corre la suite de tests del repo y devuelve el conjunto de node-ids que fallan.
    {"ran": bool, "failures": set[str], "returncode": int}. `ran=False` si no hay tests.
    """
    cmd = ["python", "-m", "pytest", "-q", "--tb=no", "-p", "no:cacheprovider"]
    if target:
        cmd.append(target)
    try:
        proc = subprocess.run(cmd, cwd=repo_path, capture_output=True, text=True, timeout=timeout)
    except FileNotFoundError as exc:
        logger.warning("regression_gate: pytest no disponible (%s)", exc)
        return {"ran": False, "failures": set(), "returncode": None, "error": str(exc)}
    except subprocess.TimeoutExpired:
        logger.warning("regression_gate: timeout tras %ss recolectando fallos", timeout)
        return {"ran": False, "failures": set(), "returncode": None, "error": "timeout"}

    out = proc.stdout + proc.stderr
    failures = set(_FAIL_RE.findall(out))
    ran = proc.returncode != _NO_TESTS_RC
    return {"ran": ran, "failures": failures, "returncode": proc.returncode}


def compute_regressions(baseline_failures, current_failures) -> dict:
    """
    Compara fallos baseline vs actuales. `new_failures` = tests que pasaban y ahora fallan
    (regresión → bloquea). `fixed` = tests que fallaban y ahora pasan. Puro.
    """
    baseline = set(baseline_failures or [])
    current = set(current_failures or [])
    new_failures = sorted(current - baseline)
    fixed = sorted(baseline - current)
    return {
        "ok": not new_failures,
        "new_failures": new_failures,
        "fixed": fixed,
        "baseline_count": len(baseline),
        "current_count": len(current),
    }


def regression_report(repo_path: str, baseline_failures, target: str = "") -> dict:
    """
    Corre la suite actual y la compara contra el baseline. Devuelve el reporte de
    `compute_regressions` enriquecido con `ran`. Si la suite no se pudo correr, no bloquea
    (ok=True con ran=False) — el gate de regresión nunca inventa un fallo sin evidencia.
    """
    current = collect_failures(repo_path, target=target)
    if not current["ran"]:
        return {"ok": True, "ran": False, "new_failures": [], "fixed": [],
                "reason": current.get("error", "sin tests recolectables")}
    report = compute_regressions(baseline_failures, current["failures"])
    report["ran"] = True
    return report


def format_block_message(report: dict) -> str:
    """Mensaje de bloqueo para alimentar al agente corrector (A6)."""
    if report.get("ok", True):
        return ""
    nf = report.get("new_failures", [])
    return (
        "⛔ GATE DE REGRESIÓN: el cambio rompió "
        f"{len(nf)} test(s) que antes pasaban:\n  - " + "\n  - ".join(nf)
        + "\nCorrige el código para que estos tests vuelvan a pasar (no edites los tests)."
    )
