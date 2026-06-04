"""
Reporte de gobernanza por feature (Fase 7.2 del PLAN_HARDENING — observabilidad).

Reúne, desde la metadata persistida del run, las señales que el operador necesita para
auditar una decisión de la fábrica de un vistazo: tier (LLM vs rutas vs final), veredicto
de seguridad y adversarial, modo de aprobación y si fue auto-mergeable.

Pura y testeable. La UI (`ui/server.py`) puede llamar a `feature_governance(feature_id)`
y renderizar `format_governance_md` en la vista de detalle del feature.
"""
from __future__ import annotations

from tools.file_tools import read_run_metadata


def feature_governance(feature_id: str) -> dict:
    """Resumen de gobernanza de un feature, leído de su metadata.json."""
    m = read_run_metadata(feature_id)
    return {
        "feature_id":         feature_id,
        "status":             m.get("status", "—"),
        "risk_llm":           m.get("risk_level_llm", "—"),
        "risk_path":          m.get("risk_level_path", "—"),
        "risk_level":         m.get("risk_level", "—"),
        "risk_final":         m.get("risk_level_final", "—"),
        "security_verdict":   m.get("security_verdict", "—"),
        "adversarial_verdict": m.get("adversarial_verdict", "—"),
        "approval_mode":      m.get("approval_mode", "—"),
        "auto_mergeable":     m.get("auto_mergeable", False),
        "confidence":         m.get("confidence_score", "—"),
    }


def format_governance_md(gov: dict) -> str:
    """Render compacto para la UI / Telegram."""
    am = "sí" if gov.get("auto_mergeable") else "no"
    return (
        f"**Gobernanza — {gov['feature_id']}**\n"
        f"- Estado: {gov['status']}\n"
        f"- Riesgo: LLM={gov['risk_llm']} · rutas={gov['risk_path']} · "
        f"efectivo={gov['risk_level']} · final={gov['risk_final']}\n"
        f"- Seguridad (A8): {gov['security_verdict']} · Adversarial (A8.5): {gov['adversarial_verdict']}\n"
        f"- Aprobación: {gov['approval_mode']} · Auto-merge: {am} · Confianza: {gov['confidence']}\n"
    )
