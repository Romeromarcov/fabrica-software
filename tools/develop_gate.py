"""
tools/develop_gate.py — Compuerta efímero → develop/dev (PLAN_BLINDAJE_TOTAL D2.1).

Núcleo PURO y OFFLINE-VERIFICABLE de la primera promoción del flujo multi-etapa: un
feature solo se mergea a `develop` (y se despliega al entorno Railway `dev`) si:

  1. **Pasó el gate del entorno efímero** (D1: corrió de verdad con DB real).
  2. **Los gates internos del pipeline están verdes** (A6–A8.5).
  3. **El revisor independiente con contexto limpio pasó** (Bloque C).

A diferencia de `risk_classifier.is_auto_mergeable` (compuerta a `main`, que exige
tier LOW + AUTO_MERGE), el merge a develop es **tier-agnóstico**: dev es precisamente
donde el feature MADURA su tiempo de riesgo (D2.3) antes de ser promovible a prod. Lo
único innegociable es que haya CORRIDO y revisado limpio.

El merge git real y el deploy a Railway `dev` son aristas de infra (requieren acceso al
repo + Railway token de deploy) — fuera de este módulo. Aquí solo se DECIDE si procede.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class DevelopGateDecision:
    mergeable: bool
    reasons: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        return {"mergeable": self.mergeable, "reasons": list(self.reasons)}


def is_mergeable_to_develop(
    *,
    ephemeral_passed: bool,
    internal_gates_green: bool,
    independent_review_passed: bool,
) -> DevelopGateDecision:
    """Decide si un feature puede mergearse a `develop` y desplegarse a dev.

    Conservador por diseño: cualquier señal ausente bloquea y se reporta el motivo.
    Tier-agnóstico (la maduración por riesgo vive en dev, no en esta compuerta).
    """
    reasons: list[str] = []
    if not ephemeral_passed:
        reasons.append("El feature no pasó el gate del entorno efímero (D1).")
    if not internal_gates_green:
        reasons.append("Los gates internos del pipeline no están verdes (A6–A8.5).")
    if not independent_review_passed:
        reasons.append("El revisor independiente con contexto limpio no confirmó verde (Bloque C).")
    return DevelopGateDecision(mergeable=not reasons, reasons=reasons)


def build_dev_deploy_plan(
    *,
    service_id: str,
    environment_id: str,
    feature_id: str,
) -> dict:
    """Descriptor PURO del deploy a Railway `dev` que dispararía la compuerta.

    No hace red: arma el input exacto de `railway_client.trigger_deploy` para que el
    disparo real (infra) sea un paso mecánico y auditable.
    """
    if not service_id:
        raise ValueError("service_id requerido para el deploy a dev")
    if not environment_id:
        raise ValueError("environment_id requerido para el deploy a dev")
    return {
        "service_id": service_id,
        "environment": environment_id,
        "feature_id": feature_id,
        "stage": "dev",
    }
