"""
tools/promotion_policy.py — Maduración por riesgo (PLAN_BLINDAJE_TOTAL D2.3).

Decide si un feature que vive en el entorno `dev` ya es PROMOVIBLE a `main`, según su tier
de riesgo (risk_classifier): tiempo mínimo madurando + ausencia de errores de runtime + (en
HIGH) uso real verificado.

NÚCLEO PURO Y OFFLINE-VERIFICABLE: esta es solo la POLÍTICA de decisión. La señal que la
alimenta (días reales en dev, errores de runtime observados, uso real) la producen D2.1/D2.2
contra el entorno Railway vivo — fuera de este módulo. Aquí solo se decide dado ese input.
"""
from __future__ import annotations

from dataclasses import dataclass, field

# Tiempo mínimo madurando en dev antes de ser promovible, por tier (días).
MATURATION_DAYS: dict[str, int] = {"LOW": 1, "MEDIUM": 3, "HIGH": 7}

# Tiers que además exigen uso real verificado en dev (no solo tiempo transcurrido).
_REQUIRE_REAL_USAGE = ("HIGH",)


@dataclass
class PromotionDecision:
    promotable: bool
    tier: str
    required_days: int
    elapsed_days: float
    reasons: list[str] = field(default_factory=list)


def required_maturation_days(tier: str) -> int:
    """Días mínimos en dev para el tier dado. Tier desconocido → trata como HIGH (conservador)."""
    return MATURATION_DAYS.get((tier or "").upper(), MATURATION_DAYS["HIGH"])


def is_promotable(
    tier: str,
    days_in_dev: float,
    runtime_errors_clean: bool,
    real_usage_verified: bool = False,
) -> PromotionDecision:
    """
    ¿El feature puede promoverse de dev a main?

    Reglas (todas deben cumplirse):
      1. days_in_dev >= maduración del tier.
      2. runtime_errors_clean (sin errores de runtime observados en dev).
      3. Para tiers en _REQUIRE_REAL_USAGE (HIGH): real_usage_verified.

    Default conservador: tier desconocido se trata como HIGH; ante duda, NO promueve.
    """
    norm = (tier or "").upper()
    # Tier desconocido → se trata como HIGH en TODA la política (días + uso real), no solo
    # en el conteo de días. Conservador: ante duda, la barra más alta.
    if norm not in MATURATION_DAYS:
        norm = "HIGH"
    required = required_maturation_days(norm)
    reasons: list[str] = []

    if days_in_dev < required:
        reasons.append(
            f"maduración insuficiente: {days_in_dev:g}d en dev < {required}d requeridos para {norm or 'desconocido'}"
        )
    if not runtime_errors_clean:
        reasons.append("hay errores de runtime observados en dev")
    if norm in _REQUIRE_REAL_USAGE and not real_usage_verified:
        reasons.append(f"tier {norm} exige uso real verificado en dev")

    promotable = not reasons
    if promotable:
        reasons.append(f"OK: {days_in_dev:g}d >= {required}d, sin errores de runtime"
                       + (", uso real verificado" if norm in _REQUIRE_REAL_USAGE else ""))

    return PromotionDecision(
        promotable=promotable,
        tier=norm or "HIGH",
        required_days=required,
        elapsed_days=days_in_dev,
        reasons=reasons,
    )
