"""
tools/release_report.py — Reporte de PR de release develop→main (PLAN_BLINDAJE_TOTAL D3.1).

Genera, de forma PURA y OFFLINE-VERIFICABLE, el cuerpo del PR de release que la fábrica
abre de `develop` a `main` para que el Founder apruebe o rechace: features incluidos,
gobernanza de cada uno, días en dev, errores de runtime observados y hallazgos abiertos del
auditor — más el veredicto de promovibilidad por tier (reusa promotion_policy D2.3).

La CREACIÓN real del PR en GitHub (y la recolección de las señales vivas: días reales en dev,
errores de runtime, hallazgos del auditor contra el entorno) son las aristas de infra (D2.x)
que requieren acceso a GitHub/Railway — fuera de este módulo. Aquí solo se ARMA el reporte
dado ese input, y se decide si el release está listo.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from tools.promotion_policy import PromotionDecision, is_promotable


@dataclass
class FeatureRelease:
    feature_id: str
    governance: dict = field(default_factory=dict)
    days_in_dev: float = 0.0
    runtime_errors: int = 0
    open_audit_findings: int = 0
    real_usage_verified: bool = False

    def promotion(self) -> PromotionDecision:
        return is_promotable(
            tier=str(self.governance.get("risk_level", "")),
            days_in_dev=self.days_in_dev,
            runtime_errors_clean=self.runtime_errors == 0,
            real_usage_verified=self.real_usage_verified,
        )


def build_release_report(features: list[FeatureRelease]) -> dict:
    """
    Arma el reporte agregado del release. `ready` es True solo si TODOS los features son
    promovibles y no hay hallazgos abiertos del auditor en ninguno.
    """
    items = []
    blocked: list[str] = []
    for f in features:
        decision = f.promotion()
        promotable = decision.promotable and f.open_audit_findings == 0
        if not promotable:
            blocked.append(f.feature_id)
        items.append({
            "feature_id": f.feature_id,
            "tier": decision.tier,
            "days_in_dev": f.days_in_dev,
            "required_days": decision.required_days,
            "runtime_errors": f.runtime_errors,
            "open_audit_findings": f.open_audit_findings,
            "promotable": promotable,
            "reasons": decision.reasons,
            "governance": f.governance,
        })
    return {
        "feature_count": len(features),
        "ready": len(features) > 0 and not blocked,
        "blocked": blocked,
        "features": items,
    }


def format_release_md(report: dict) -> str:
    """Render del reporte como cuerpo del PR de release (markdown)."""
    ready = "✅ LISTO" if report["ready"] else "⛔ BLOQUEADO"
    lines = [
        f"# Release develop → main — {ready}",
        "",
        f"**Features:** {report['feature_count']} · **Bloqueados:** {len(report['blocked'])}",
        "",
    ]
    if report["blocked"]:
        lines.append("> Bloqueado por: " + ", ".join(report["blocked"]))
        lines.append("")
    for it in report["features"]:
        mark = "✅" if it["promotable"] else "⛔"
        lines.append(f"## {mark} {it['feature_id']} ({it['tier']})")
        lines.append(
            f"- Maduración: {it['days_in_dev']:g}d / {it['required_days']}d requeridos"
        )
        lines.append(
            f"- Errores de runtime: {it['runtime_errors']} · "
            f"Hallazgos del auditor abiertos: {it['open_audit_findings']}"
        )
        if not it["promotable"]:
            for r in it["reasons"]:
                lines.append(f"  - ⚠️ {r}")
        lines.append("")
    lines.append("---")
    lines.append("_El Founder aprueba o rechaza este release. Deploy a prod solo desde `main` (D3.2)._")
    return "\n".join(lines)
