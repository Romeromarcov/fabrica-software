"""Tests del Bloque E (PLAN_BLINDAJE_TOTAL) — observabilidad.

Cubre:
  E1.1 — Correlation IDs (trace_id): contextvar, helpers y logging.Filter.
  E1.2 — /api/metrics: rollup de costo/tokens por agente y auto-merge vs escalado.
  E1.3 — /healthz: chequeo profundo de dependencias (DB, proveedor LLM, git).
"""
import asyncio
import json
import logging


import tools.trace as trace


# ── E1.1 — Correlation IDs ────────────────────────────────────────────────────

def test_new_trace_id_uses_feature_id():
    assert trace.new_trace_id("feat-x") == "feat-x"


def test_new_trace_id_empty_returns_12_hex():
    tid = trace.new_trace_id("")
    assert len(tid) == 12
    int(tid, 16)   # debe ser hexadecimal válido (lanza ValueError si no)


def test_set_get_trace_id_round_trip():
    trace.set_trace_id("abc123")
    try:
        assert trace.get_trace_id() == "abc123"
    finally:
        trace.set_trace_id("")   # restaura a "-"
    assert trace.get_trace_id() == "-"


def test_set_trace_id_empty_becomes_dash():
    trace.set_trace_id("")
    assert trace.get_trace_id() == "-"


def test_trace_filter_injects_attr_default_dash():
    # Sin traza activa → el filtro inyecta "-"
    trace.set_trace_id("")
    f = trace.TraceIdFilter()
    record = logging.LogRecord(
        name="t", level=logging.INFO, pathname=__file__, lineno=1,
        msg="hola", args=(), exc_info=None,
    )
    assert not hasattr(record, "trace_id")
    assert f.filter(record) is True
    assert record.trace_id == "-"


def test_trace_filter_injects_active_trace():
    trace.set_trace_id("feature-42")
    try:
        f = trace.TraceIdFilter()
        record = logging.LogRecord(
            name="t", level=logging.INFO, pathname=__file__, lineno=1,
            msg="x", args=(), exc_info=None,
        )
        f.filter(record)
        assert record.trace_id == "feature-42"
    finally:
        trace.set_trace_id("")


# ── E1.2 — /api/metrics ───────────────────────────────────────────────────────

class _FakeRequest:
    """Request mínima: _require_perm con RBAC desactivado no la inspecciona."""
    def __init__(self):
        self.session = {}


def _write_run(base, run_id, meta, entries=None):
    d = base / run_id
    d.mkdir(parents=True, exist_ok=True)
    (d / "metadata.json").write_text(json.dumps(meta), encoding="utf-8")
    if entries is not None:
        (d / "cost_entries.json").write_text(json.dumps(entries), encoding="utf-8")


def test_api_metrics_rollup(tmp_path, monkeypatch):
    import ui.server as srv

    _write_run(
        tmp_path, "run_a",
        {"status": "completado", "total_cost_usd": 1.5, "auto_mergeable": True},
        entries=[
            {"agent": "Agente 4 Backend", "input_tokens": 100,
             "output_tokens": 50, "cache_read_tokens": 10, "cost_usd": 1.0},
            {"agent": "QA", "input_tokens": 20, "output_tokens": 5,
             "cache_read_tokens": 0, "cost_usd": 0.5},
        ],
    )
    _write_run(
        tmp_path, "run_b",
        {"status": "detenido", "total_cost_usd": 0.5,
         "approval_mode": "stop_protocol", "auto_mergeable": False},
        entries=[
            {"agent": "Agente 4 Backend", "input_tokens": 200,
             "output_tokens": 80, "cache_read_tokens": 0, "cost_usd": 0.5},
        ],
    )
    # Run corrupto: debe saltarse sin crash
    bad = tmp_path / "run_bad"
    bad.mkdir()
    (bad / "metadata.json").write_text("{ no es json", encoding="utf-8")

    monkeypatch.setattr(srv, "RUNS_DIR", tmp_path)

    result = asyncio.run(srv.api_metrics(_FakeRequest()))

    assert result["features"] == 2                      # run_bad ignorado
    assert result["total_cost_usd"] == 2.0
    assert result["auto_merge"] == 1
    assert result["escalated"] == 1
    assert result["pct_auto_merge"] == 50.0
    # Rollup por agente: backend aparece en ambos runs
    backend = result["by_agent"]["Agente 4 Backend"]
    assert backend["input_tokens"] == 300
    assert backend["output_tokens"] == 130
    assert backend["cost_usd"] == 1.5
    assert backend["runs"] == 2
    assert result["status_counts"]["completado"] == 1


def test_api_metrics_empty_runs_dir(tmp_path, monkeypatch):
    import ui.server as srv
    monkeypatch.setattr(srv, "RUNS_DIR", tmp_path)
    result = asyncio.run(srv.api_metrics(_FakeRequest()))
    assert result["features"] == 0
    assert result["total_cost_usd"] == 0.0
    assert result["pct_auto_merge"] == 0.0


# ── E1.3 — /healthz ────────────────────────────────────────────────────────────

def test_healthz_ok_with_provider_key_and_git(monkeypatch, tmp_path):
    import ui.server as srv
    # Forzar presencia de una key de proveedor a nivel del módulo config
    monkeypatch.setattr("config.ANTHROPIC_API_KEY", "sk-test", raising=False)
    monkeypatch.setattr("config.OPENAI_API_KEY", "", raising=False)
    monkeypatch.setattr("config.GOOGLE_API_KEY", "", raising=False)
    monkeypatch.setattr("config.ZHIPU_API_KEY", "", raising=False)
    monkeypatch.setattr("config.KIMI_API_KEY", "", raising=False)
    monkeypatch.setattr("config.CUSTOM_PROVIDERS", [], raising=False)
    monkeypatch.setattr("shutil.which", lambda name: "/usr/bin/git")
    # Despliegue nuevo: el dir padre del DB NO existe aún → healthz debe crearlo y
    # reportar "ok" (no "degraded"). Reproduce el escenario que falló en CI.
    monkeypatch.setattr(srv, "DB_PATH", tmp_path / "data" / "fabrica_state.db")

    resp = asyncio.run(srv.healthz())
    payload = json.loads(resp.body)
    assert resp.status_code == 200
    assert payload["status"] == "ok"
    assert payload["checks"]["llm_provider"] is True
    assert payload["checks"]["git"] is True
    assert payload["checks"]["db"] is True


def test_healthz_degraded_without_provider_key(monkeypatch):
    import ui.server as srv
    monkeypatch.setattr("config.ANTHROPIC_API_KEY", "", raising=False)
    monkeypatch.setattr("config.OPENAI_API_KEY", "", raising=False)
    monkeypatch.setattr("config.GOOGLE_API_KEY", "", raising=False)
    monkeypatch.setattr("config.ZHIPU_API_KEY", "", raising=False)
    monkeypatch.setattr("config.KIMI_API_KEY", "", raising=False)
    monkeypatch.setattr("config.CUSTOM_PROVIDERS", [], raising=False)
    monkeypatch.setattr("shutil.which", lambda name: "/usr/bin/git")

    resp = asyncio.run(srv.healthz())
    payload = json.loads(resp.body)
    assert resp.status_code == 503
    assert payload["status"] == "degraded"
    assert payload["checks"]["llm_provider"] is False
