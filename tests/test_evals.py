"""Tests del harness de evals deterministas (E4 — PLAN_BLINDAJE_TOTAL, Bloque E).

Verifica:
  E4.1 — run_evals:
    1. Corre OFFLINE (sin LLM/red) y los casos sembrados (secret/tenant/trivial)
       son DETECTADOS por sus gates → passed=True para cada uno; score == 100.
    2. La estructura devuelta tiene las claves esperadas por caso.
  E4.2 — record_eval_run + eval_trend:
    3. Dos corridas (80 luego 100) en un dir tmp → eval_trend reporta "mejorando"
       y lee bien los scores en orden.
    4. Archivo de evals ausente → eval_trend devuelve estructura vacía segura (sin crash).
    5. format_eval_report produce un resumen no vacío.
"""
import config
from tools.evals import (
    run_evals,
    record_eval_run,
    eval_trend,
    format_eval_report,
)


# ── E4.1 — run_evals ───────────────────────────────────────────────────────────

def test_run_evals_all_reference_gates_behave(tmp_path):
    result = run_evals(str(tmp_path))

    # Estructura.
    assert set(result.keys()) >= {"cases", "passed", "failed", "score"}
    by_name = {c["name"]: c for c in result["cases"]}
    for c in result["cases"]:
        assert set(c.keys()) >= {"name", "expected", "actual", "passed"}

    # Los casos sembrados deben ser ATRAPADOS por sus gates deterministas.
    assert by_name["seeded_secret"]["passed"] is True
    assert by_name["seeded_tenant_leak"]["passed"] is True
    assert by_name["seeded_trivial_test"]["passed"] is True
    # El caso benigno debe quedar limpio y el de ruta debe clasificar HIGH.
    assert by_name["crud_simple"]["passed"] is True
    assert by_name["high_risk_path"]["passed"] is True

    # Todos los gates de referencia se comportan como esperado → score perfecto.
    assert result["score"] == 100
    assert result["passed"] == len(result["cases"])
    assert result["failed"] == 0


def test_run_evals_no_tmp_root_runs_offline():
    # Sin tmp_root usa un TemporaryDirectory del sistema; sigue siendo determinista.
    result = run_evals()
    assert result["score"] == 100
    assert result["failed"] == 0


# ── E4.2 — record_eval_run + eval_trend ─────────────────────────────────────────

def test_record_and_trend_improving(tmp_path):
    evals_dir = tmp_path / "runs"

    # Corrida 1: score 80.
    p1 = record_eval_run({"score": 80.0, "passed": 4, "failed": 1, "cases": [1, 2, 3, 4, 5]},
                         runs_dir=evals_dir)
    # Corrida 2: score 100.
    p2 = record_eval_run({"score": 100.0, "passed": 5, "failed": 0, "cases": [1, 2, 3, 4, 5]},
                         runs_dir=evals_dir)
    assert p1 and p2

    trend = eval_trend(runs_dir=evals_dir, last_n=10)
    assert trend["runs"] == 2
    assert trend["scores"] == [80.0, 100.0]
    assert trend["latest"] == 100.0
    assert trend["previous"] == 80.0
    assert trend["direction"] == "mejorando"
    assert trend["avg"] == 90.0

    report = format_eval_report(trend)
    assert "mejorando" in report
    assert report.strip() != ""


def test_eval_trend_missing_file_safe(tmp_path):
    # Directorio sin evals.jsonl → estructura vacía segura, sin excepción.
    trend = eval_trend(runs_dir=tmp_path / "nope", last_n=10)
    assert trend["runs"] == 0
    assert trend["scores"] == []
    assert trend["latest"] == 0.0
    assert trend["previous"] is None
    assert trend["direction"] == "sin datos"

    # format_eval_report sobre vacío no crashea.
    assert format_eval_report(trend)


def test_record_eval_run_roundtrip_reads_back(tmp_path):
    evals_dir = tmp_path / "r"
    record_eval_run({"score": 100.0, "passed": 5, "failed": 0, "cases": [0] * 5},
                    runs_dir=evals_dir)
    trend = eval_trend(runs_dir=evals_dir)
    assert trend["runs"] == 1
    assert trend["latest"] == 100.0
    assert trend["previous"] is None
    assert trend["direction"] == "sin datos"


def test_config_evals_flag_exists():
    # La flag de gate de auto-ejecución existe (las funciones funcionan igual).
    assert isinstance(config.EVALS_ENABLED, bool)
