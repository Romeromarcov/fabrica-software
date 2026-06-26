"""
schemas/agent_outputs.py — Schemas Pydantic de salida por agente (M1).

Diseño: cada schema captura el **contrato estructurado** que un agente aporta al
state (no el markdown libre). `validate_output` es tolerante por diseño — devuelve
un `ValidationResult` en vez de lanzar — para que la validación sea un gate
observable y no rompa el pipeline existente al activarse.
"""
from __future__ import annotations

from typing import Optional, Type

from pydantic import BaseModel, Field, ValidationError


class AgentOutput(BaseModel):
    """Contrato base común a toda salida de agente."""
    agent_id: str
    model: Optional[str] = None
    raw_text: str = ""


class MasterPlan(AgentOutput):
    risk_level: str = "MEDIUM"
    tasks: list[str] = Field(default_factory=list)


class DBSchema(AgentOutput):
    models: list[str] = Field(default_factory=list)
    needs_migrations: bool = False


class BackendCode(AgentOutput):
    files: list[str] = Field(default_factory=list)
    summary: str = ""


class FrontendCode(AgentOutput):
    files: list[str] = Field(default_factory=list)
    summary: str = ""


class FileChange(BaseModel):
    """Cambio de un archivo dentro de un artefacto de código (F1)."""
    path: str
    action: str = "create"          # create | modify | delete
    language: str = ""
    summary: str = ""


class QAReport(AgentOutput):
    passed: bool = False
    iterations: int = 0
    bug_categories: list[str] = Field(default_factory=list)


class SecOpsReport(AgentOutput):
    verdict: str = "PASS"          # PASS | BLOCK
    findings: list[str] = Field(default_factory=list)


class SecurityReport(AgentOutput):
    """Contrato de seguridad (F1). Alias semántico de SecOpsReport con verdict de A8."""
    verdict: str = "CLEARANCE"      # CLEARANCE | BLOCK
    findings: list[str] = Field(default_factory=list)


class AdversarialReport(AgentOutput):
    adversarial_clear: bool = True
    findings: list[str] = Field(default_factory=list)


# Mapa nombre (declarado en registry.json) → clase Pydantic.
SCHEMA_REGISTRY: dict[str, Type[AgentOutput]] = {
    "MasterPlan":        MasterPlan,
    "DBSchema":          DBSchema,
    "BackendCode":       BackendCode,
    "FrontendCode":      FrontendCode,
    "QAReport":          QAReport,
    "SecOpsReport":      SecOpsReport,
    "SecurityReport":    SecurityReport,
    "AdversarialReport": AdversarialReport,
}


class ValidationResult(BaseModel):
    ok: bool
    schema_name: str
    errors: list[str] = Field(default_factory=list)
    model: Optional[BaseModel] = None

    model_config = {"arbitrary_types_allowed": True}


def get_schema(name: str) -> Optional[Type[AgentOutput]]:
    """Devuelve la clase Pydantic para un nombre de schema, o None si no existe."""
    return SCHEMA_REGISTRY.get(name)


def validate_output(schema_name: Optional[str], data: dict) -> ValidationResult:
    """
    Valida `data` contra el schema nombrado. Tolerante:
      - schema_name None o desconocido → ok=True (sin contrato declarado).
      - error de validación → ok=False con la lista de errores legibles.
    """
    if not schema_name:
        return ValidationResult(ok=True, schema_name="", errors=[])

    schema = get_schema(schema_name)
    if schema is None:
        return ValidationResult(
            ok=False, schema_name=schema_name,
            errors=[f"schema desconocido: {schema_name}"],
        )

    try:
        model = schema.model_validate(data)
        return ValidationResult(ok=True, schema_name=schema_name, model=model)
    except ValidationError as exc:
        errors = [f"{'.'.join(str(p) for p in e['loc'])}: {e['msg']}" for e in exc.errors()]
        return ValidationResult(ok=False, schema_name=schema_name, errors=errors)
