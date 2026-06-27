"""
schemas/ — Contratos de interfaz Pydantic por salida de agente (PLAN_PLATAFORMA_V2 M1).

Cada agente declara en el registry un `output_schema` (nombre). Aquí viven esos
schemas y el helper de validación que `base.py` puede invocar tras cada agente para
convertir bugs silenciosos de forma de datos en errores explícitos y observables.
"""
from schemas.agent_outputs import (
    SCHEMA_REGISTRY,
    AgentOutput,
    AdversarialReport,
    BackendCode,
    DBSchema,
    FileChange,
    FrontendCode,
    MasterPlan,
    QAReport,
    SecOpsReport,
    SecurityReport,
    ValidationResult,
    get_schema,
    validate_output,
)

__all__ = [
    "SCHEMA_REGISTRY",
    "AgentOutput",
    "AdversarialReport",
    "BackendCode",
    "DBSchema",
    "FileChange",
    "FrontendCode",
    "MasterPlan",
    "QAReport",
    "SecOpsReport",
    "SecurityReport",
    "ValidationResult",
    "get_schema",
    "validate_output",
]
