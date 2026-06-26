"""
Tests F1 — Contratos estructurados (mecanismo de validación + reintento).

Cubre:
  • extract_json_block: bloque ```json fenced, objeto balanceado suelto, y ausencia.
  • request_validated: válido al primer intento, artefacto CORRUPTO que se reintenta hasta
    validar (aceptación F1), y caso que nunca valida → ok=False sin lanzar.
  • Nuevos schemas FileChange y SecurityReport.
"""
from schemas.agent_outputs import validate_output, FileChange, SecurityReport
from tools import structured_artifacts as sa


# ── extract_json_block ───────────────────────────────────────────────────────

def test_extract_fenced_json():
    text = "bla bla\n```json\n{\"agent_id\": \"a1\", \"risk_level\": \"LOW\"}\n```\nfin"
    obj = sa.extract_json_block(text)
    assert obj == {"agent_id": "a1", "risk_level": "LOW"}


def test_extract_balanced_object_without_fence():
    text = 'prefijo {"agent_id": "a2", "needs_migrations": true} sufijo'
    assert sa.extract_json_block(text) == {"agent_id": "a2", "needs_migrations": True}


def test_extract_returns_none_when_no_json():
    assert sa.extract_json_block("sin json aqui") is None
    assert sa.extract_json_block("") is None


# ── request_validated: válido / reintento / nunca valida ─────────────────────

def test_valid_on_first_attempt():
    def call_fn(task):
        return ('```json\n{"agent_id":"a1","risk_level":"LOW","tasks":[]}\n```', {"c": 1})
    text, vr, costs = sa.request_validated(
        call_fn, schema_name="MasterPlan", base_task="haz un plan", max_retries=2)
    assert vr.ok is True
    assert len(costs) == 1


def test_corrupt_artifact_is_retried_until_valid():
    """Aceptación F1: un artefacto corrupto se reintenta y al validar, ok=True."""
    calls = {"n": 0}

    def call_fn(task):
        calls["n"] += 1
        if calls["n"] == 1:
            # Corrupto: iterations debe ser int, aquí es string → falla validación.
            return ('```json\n{"agent_id":"a7","passed":true,"iterations":"dos"}\n```', {"c": 1})
        # Reintento corregido.
        return ('```json\n{"agent_id":"a7","passed":true,"iterations":2}\n```', {"c": 2})

    text, vr, costs = sa.request_validated(
        call_fn, schema_name="QAReport", base_task="corre QA", max_retries=2)
    assert calls["n"] == 2            # se reintentó exactamente una vez
    assert vr.ok is True
    assert vr.model.iterations == 2
    assert len(costs) == 2            # acumula el costo de ambos intentos


def test_never_valid_returns_not_ok_without_raising():
    def call_fn(task):
        return ("sin bloque json", {"c": 1})
    text, vr, costs = sa.request_validated(
        call_fn, schema_name="DBSchema", base_task="diseña", max_retries=1)
    assert vr.ok is False
    assert len(costs) == 2            # 1 intento + 1 reintento = 2 llamadas


def test_unknown_schema_is_tolerated():
    # validate_output trata schema desconocido como ok=False; no debe lanzar.
    def call_fn(task):
        return ('```json\n{"x":1}\n```', None)
    text, vr, costs = sa.request_validated(
        call_fn, schema_name="NoExiste", base_task="t", max_retries=0)
    assert vr.ok is False


# ── Nuevos schemas F1 ────────────────────────────────────────────────────────

def test_filechange_schema_defaults():
    fc = FileChange(path="app/models.py")
    assert fc.action == "create"
    assert fc.path == "app/models.py"


def test_security_report_in_registry():
    vr = validate_output("SecurityReport", {
        "agent_id": "a8", "verdict": "CLEARANCE", "findings": []})
    assert vr.ok is True
    assert isinstance(vr.model, SecurityReport)
