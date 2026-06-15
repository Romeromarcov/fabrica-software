"""
Evals deterministas del pipeline mismo (E4 del PLAN_BLINDAJE_TOTAL).

Harness OFFLINE y determinista — NO llama a ningún LLM ni a la red. Su objetivo es
validar que los GATES deterministas de la fábrica atrapan problemas SEMBRADOS:

  • secret-scan      → tools.code_sandbox.scan_secrets
  • tenant-scan      → tools.code_sandbox.scan_unfiltered_views
  • test-quality     → tools.code_sandbox.scan_trivial_tests
  • clasificador     → tools.risk_classifier.classify_change_risk

Cada caso de referencia se materializa en un directorio temporal, se corre el scanner
relevante y se compara con el resultado ESPERADO. `passed` significa "el gate se comportó
como debía" (atrapó lo que tenía que atrapar, o quedó limpio cuando debía).

Tendencia: `record_eval_run` apila resultados en data/runs/evals/evals.jsonl y
`eval_trend` los lee para reportar si la suite mejora o regresa. I/O defensiva: archivos
ausentes → estructura vacía/cero, sin crash; se capturan OSError/JSONDecodeError.
"""
from __future__ import annotations

import json
import logging
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable, Optional

from tools.code_sandbox import (
    scan_secrets,
    scan_trivial_tests,
    scan_unfiltered_views,
)
from tools.risk_classifier import classify_change_risk

logger = logging.getLogger(__name__)


# ── Resolución del directorio de almacenamiento (RUNS_DIR/evals) ───────────────

def _get_runs_dir() -> Path:
    """RUNS_DIR de la fábrica; degrada a data/runs si config no es importable."""
    try:
        from tools.file_tools import RUNS_DIR
        return RUNS_DIR
    except ImportError:
        return Path("data/runs")


def _evals_path(runs_dir: Optional[Path] = None) -> Path:
    base = Path(runs_dir) if runs_dir is not None else _get_runs_dir()
    return base / "evals" / "evals.jsonl"


# ── E4.1 — Suite de features de referencia (offline, determinista) ─────────────
# Cada caso: materializa un fixture en `root`, corre el scanner relevante y devuelve
# (actual, passed). `actual` resume el comportamiento observado del gate; `passed`
# indica si coincide con lo esperado (el gate hizo lo correcto).

def _case_crud_simple(root: Path) -> tuple[str, bool]:
    """Archivo benigno → secret-scan limpio, tenant-scan limpio, test-quality ok."""
    (root / "ventas").mkdir(parents=True, exist_ok=True)
    (root / "ventas" / "services.py").write_text(
        "def total(items):\n"
        "    \"\"\"Suma de subtotales — lógica benigna sin secretos ni fugas.\"\"\"\n"
        "    return sum(i.subtotal for i in items)\n",
        encoding="utf-8",
    )
    secrets = scan_secrets(str(root))
    views = scan_unfiltered_views(str(root))
    trivial = scan_trivial_tests(str(root))
    clean = (len(secrets) == 0 and len(views) == 0 and len(trivial) == 0)
    actual = (f"secrets={len(secrets)} views={len(views)} trivial_tests={len(trivial)}"
              if not clean else "todos los escaneos limpios")
    return actual, clean


def _case_seeded_secret(root: Path) -> tuple[str, bool]:
    """Archivo con una API key real → scan_secrets DEBE marcarlo."""
    (root / "settings_leak.py").write_text(
        'API_KEY = "sk-ant-api03-REAL0Secret0Value0123456789abcdef"\n',
        encoding="utf-8",
    )
    findings = scan_secrets(str(root))
    caught = len(findings) > 0
    actual = (f"scan_secrets marcó {len(findings)} ({findings[0]['kind']})"
              if caught else "scan_secrets NO marcó el secreto sembrado")
    return actual, caught


def _case_seeded_tenant_leak(root: Path) -> tuple[str, bool]:
    """View DRF con queryset = Model.objects.all() → scan_unfiltered_views DEBE marcarlo."""
    (root / "views.py").write_text(
        "from rest_framework.viewsets import ModelViewSet\n"
        "from .models import Factura\n\n"
        "class FacturaViewSet(ModelViewSet):\n"
        "    queryset = Factura.objects.all()\n",
        encoding="utf-8",
    )
    findings = scan_unfiltered_views(str(root))
    caught = len(findings) > 0
    actual = (f"scan_unfiltered_views marcó {len(findings)} View(s) (clase "
              f"{findings[0]['class']})" if caught
              else "scan_unfiltered_views NO marcó la fuga sembrada")
    return actual, caught


def _case_seeded_trivial_test(root: Path) -> tuple[str, bool]:
    """test_x con assert True → scan_trivial_tests DEBE marcarlo."""
    (root / "tests").mkdir(parents=True, exist_ok=True)
    (root / "tests" / "test_trivial.py").write_text(
        "def test_x():\n"
        "    assert True\n",
        encoding="utf-8",
    )
    findings = scan_trivial_tests(str(root))
    caught = len(findings) > 0
    actual = (f"scan_trivial_tests marcó {len(findings)} ({findings[0]['kind']})"
              if caught else "scan_trivial_tests NO marcó el test trivial sembrado")
    return actual, caught


def _case_high_risk_path(root: Path) -> tuple[str, bool]:
    """Cambio que toca apps/core/models.py → classify_change_risk == HIGH.

    Determinista por ruta: no necesita materializar archivos.
    """
    tier = classify_change_risk(["apps/core/models.py"])
    caught = tier == "HIGH"
    actual = f"classify_change_risk = {tier}"
    return actual, caught


# Registro de casos: (name, expected_human, runner). El orden es estable y determinista.
_REFERENCE_CASES: list[tuple[str, str, Callable[[Path], tuple[str, bool]]]] = [
    ("crud_simple",         "scans limpios (secret/tenant/test-quality ok)", _case_crud_simple),
    ("seeded_secret",       "scan_secrets marca el secreto",                 _case_seeded_secret),
    ("seeded_tenant_leak",  "scan_unfiltered_views marca la View",           _case_seeded_tenant_leak),
    ("seeded_trivial_test", "scan_trivial_tests marca el test",              _case_seeded_trivial_test),
    ("high_risk_path",      "classify_change_risk == HIGH",                  _case_high_risk_path),
]


def run_evals(tmp_root: Optional[str] = None) -> dict:
    """Corre la suite de evals deterministas (offline, sin LLM ni red).

    Materializa cada caso de referencia en un subdirectorio temporal bajo `tmp_root`
    (o un temporal del sistema si es None), corre el scanner determinista relevante y
    compara con lo esperado.

    Retorna:
      {"cases": [{"name","expected","actual","passed"}...],
       "passed": N, "failed": M, "score": pct (0–100)}
    """
    base_ctx = None
    if tmp_root is not None:
        base_dir = Path(tmp_root)
        base_dir.mkdir(parents=True, exist_ok=True)
    else:
        base_ctx = tempfile.TemporaryDirectory(prefix="fabrica_evals_")
        base_dir = Path(base_ctx.name)

    cases: list[dict] = []
    try:
        for name, expected, runner in _REFERENCE_CASES:
            case_dir = base_dir / name
            case_dir.mkdir(parents=True, exist_ok=True)
            try:
                actual, passed = runner(case_dir)
            except (OSError, ValueError) as exc:
                # Un caso que no pudo materializarse/correrse offline cuenta como fallo
                # explícito, nunca como verde silencioso.
                actual, passed = f"ERROR ejecutando el caso: {exc}", False
                logger.warning("Eval '%s' no pudo correr offline: %s", name, exc)
            cases.append({
                "name": name,
                "expected": expected,
                "actual": actual,
                "passed": bool(passed),
            })
    finally:
        if base_ctx is not None:
            base_ctx.cleanup()

    n_passed = sum(1 for c in cases if c["passed"])
    n_failed = len(cases) - n_passed
    score = round(n_passed / len(cases) * 100, 1) if cases else 0.0
    return {"cases": cases, "passed": n_passed, "failed": n_failed, "score": score}


# ── E4.2 — Reporte de tendencia ────────────────────────────────────────────────

def record_eval_run(result: dict, runs_dir: Optional[Path] = None) -> str:
    """Apila el resultado de una corrida de evals en RUNS_DIR/evals/evals.jsonl.

    Append atómico-ish: una línea JSON por corrida (timestamp, score, passed, failed).
    Crea el directorio si falta. Retorna la ruta del archivo (str). Ante OSError lo
    loguea y retorna la ruta de todos modos (sin crashear el pipeline).
    """
    path = _evals_path(runs_dir)
    record = {
        "date":   datetime.now(timezone.utc).isoformat(),
        "score":  float(result.get("score", 0.0)),
        "passed": int(result.get("passed", 0)),
        "failed": int(result.get("failed", 0)),
        "total":  len(result.get("cases", [])),
    }
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
        logger.info("Evals: corrida registrada score=%.1f (%d/%d) en %s",
                    record["score"], record["passed"], record["total"], path)
    except OSError as exc:
        logger.error("Evals: no se pudo registrar la corrida en %s: %s", path, exc)
    return str(path)


def _read_eval_records(runs_dir: Optional[Path] = None) -> list[dict]:
    """Lee evals.jsonl → lista de records. Ausente/ilegible → []. No propaga."""
    path = _evals_path(runs_dir)
    if not path.exists():
        return []
    records: list[dict] = []
    try:
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                records.append(json.loads(line))
            except json.JSONDecodeError:
                logger.warning("Evals: línea JSON inválida ignorada en %s", path)
    except OSError as exc:
        logger.error("Evals: no se pudo leer %s: %s", path, exc)
        return []
    return records


def eval_trend(runs_dir: Optional[Path] = None, last_n: int = 10) -> dict:
    """Tendencia de las últimas `last_n` corridas de evals.

    Retorna:
      {"runs": int, "scores": [..], "latest": float, "previous": float|None,
       "avg": float, "direction": "mejorando"|"estable"|"empeorando"|"sin datos"}

    Archivo ausente / sin datos → estructura vacía segura (runs=0, sin crash).
    """
    records = _read_eval_records(runs_dir)
    if not records:
        return {"runs": 0, "scores": [], "latest": 0.0, "previous": None,
                "avg": 0.0, "direction": "sin datos"}

    recent = records[-last_n:] if last_n and last_n > 0 else records
    scores = [float(r.get("score", 0.0)) for r in recent]

    latest = scores[-1]
    previous = scores[-2] if len(scores) >= 2 else None
    avg = round(sum(scores) / len(scores), 1)

    direction = "sin datos" if previous is None else "estable"
    if previous is not None:
        diff = latest - previous
        if diff > 0.001:
            direction = "mejorando"
        elif diff < -0.001:
            direction = "empeorando"

    return {
        "runs":      len(scores),
        "scores":    scores,
        "latest":    latest,
        "previous":  previous,
        "avg":       avg,
        "direction": direction,
    }


def format_eval_report(trend: dict) -> str:
    """Resumen humano corto de la tendencia de evals (para gobernanza)."""
    runs = trend.get("runs", 0)
    if not runs:
        return "**Evals del pipeline:** sin corridas registradas."

    emoji = {
        "mejorando":  "📈",
        "estable":    "➡️",
        "empeorando": "📉",
        "sin datos":  "❓",
    }.get(trend.get("direction", "sin datos"), "❓")

    prev = trend.get("previous")
    delta = ""
    if prev is not None:
        diff = trend.get("latest", 0.0) - prev
        delta = f" (Δ {diff:+.1f} vs anterior {prev:.1f})"

    return (
        f"**Evals del pipeline ({runs} corrida(s)):** {emoji} "
        f"{trend.get('direction', 'sin datos')} · "
        f"último score {trend.get('latest', 0.0):.1f}/100{delta} · "
        f"promedio {trend.get('avg', 0.0):.1f}/100"
    )
