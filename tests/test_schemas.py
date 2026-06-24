"""Tests de los schemas Pydantic por salida de agente (PLAN_PLATAFORMA_V2 M1)."""
from schemas import SCHEMA_REGISTRY, get_schema, validate_output


def test_valid_backend_code():
    res = validate_output("BackendCode", {
        "agent_id": "A4", "files": ["apps/core/models.py"], "summary": "ok",
    })
    assert res.ok
    assert res.model.files == ["apps/core/models.py"]


def test_invalid_type_reports_error():
    res = validate_output("QAReport", {"agent_id": "A7", "iterations": "no-soy-int"})
    assert not res.ok
    assert any("iterations" in e for e in res.errors)


def test_unknown_schema_is_not_ok():
    res = validate_output("NoExiste", {"agent_id": "A1"})
    assert not res.ok
    assert "desconocido" in res.errors[0]


def test_none_schema_is_ok():
    # Agente sin contrato declarado → validación pasa (tolerante).
    res = validate_output(None, {"cualquier": "cosa"})
    assert res.ok


def test_missing_required_field_fails():
    # agent_id es obligatorio en AgentOutput.
    res = validate_output("SecOpsReport", {"verdict": "BLOCK"})
    assert not res.ok


def test_all_registered_schemas_have_defaults():
    # Cada schema debe instanciar con solo agent_id (defaults sanos).
    for name in SCHEMA_REGISTRY:
        res = validate_output(name, {"agent_id": "AX"})
        assert res.ok, f"{name} falló con defaults: {res.errors}"


def test_get_schema_returns_class_or_none():
    assert get_schema("BackendCode") is not None
    assert get_schema("nope") is None
