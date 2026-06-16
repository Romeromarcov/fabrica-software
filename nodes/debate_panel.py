"""
VIII-3 — Debate inter-agente para features de ALTO RIESGO.

Cuando A1 detecta RISK_LEVEL: HIGH se activa automáticamente un panel con
2 revisores (usando MODEL_FAST ≈ Haiku) que evalúan el MASTER_PLAN desde
perspectivas distintas. A1 (como árbitro) lee las objeciones y decide si
el plan requiere revisión.

Costo estimado: < $0.05 por debate.
Latencia añadida: ~15-30 seg (3 llamadas en serie con Haiku).

Flujo:
  a1_planificador → debate_panel (si HIGH + no lightning) → aprobación normal
                 ↘ aprobación normal (si LOW/MEDIUM o lightning)

El nodo setea debate_done=True para evitar re-entrar en un bucle.
"""
from __future__ import annotations

import logging
from state import FabricaState
from nodes.base import call_agent
from config import MODEL_DEBATE

logger = logging.getLogger(__name__)

# ── Prompts de los revisores ──────────────────────────────────────────────────

_REVIEWER_1_PROMPT = """\
Eres un revisor técnico senior. Evalúa el siguiente MASTER_PLAN desde la \
perspectiva de **Arquitectura y Escalabilidad**:

{plan}

Evalúa estos aspectos (sé conciso, máx. 250 palabras):
1. ¿Hay acoplamiento excesivo entre módulos que dificulte mantenimiento futuro?
2. ¿El diseño escala con el crecimiento esperado del sistema?
3. ¿Hay dependencias circulares, antipatrones o violaciones de SOLID evidentes?
4. ¿El scope está bien definido o puede producir ambigüedad de implementación?

Responde con exactamente uno de estos dos formatos:
  APROBADO — [justificación de una línea]
  OBJECIONES:
  - [objeción 1 concreta y accionable]
  - [objeción 2 ...]
"""

_REVIEWER_2_PROMPT = """\
Eres un revisor técnico senior. Evalúa el siguiente MASTER_PLAN desde la \
perspectiva de **Riesgo de Regresión y Seguridad**:

{plan}

Evalúa estos aspectos (sé conciso, máx. 250 palabras):
1. ¿Qué módulos existentes podrían verse afectados negativamente?
2. ¿Hay riesgos de seguridad evidentes (inyección, autenticación débil, exposición de datos)?
3. ¿El plan incluye un path de rollback si la implementación falla?
4. ¿Hay cambios irreversibles (migraciones, eliminación de datos) sin plan de reversión?

Responde con exactamente uno de estos dos formatos:
  APROBADO — [justificación de una línea]
  OBJECIONES:
  - [objeción 1 concreta y accionable]
  - [objeción 2 ...]
"""

_ARBITRATOR_PROMPT = """\
Eres el Agente 1 PM (Planificador). Acabas de recibir la revisión de dos \
expertos sobre tu MASTER_PLAN.

MASTER_PLAN ORIGINAL:
---
{plan}
---

REVISOR 1 (Arquitectura):
{review_1}

REVISOR 2 (Riesgos):
{review_2}
---

Tu tarea:
1. Analiza si las objeciones son válidas y relevantes para este feature.
2. Si hay objeciones válidas: produce un MASTER_PLAN REVISADO que las resuelva.
   Incluye todos los ROUTING FLAGS, CONFIDENCE_SCORE y RISK_LEVEL al final como en el original.
3. Si las objeciones son menores, incorrectas o ya están cubiertas: \
   justifica brevemente y mantén el plan original.

Termina SIEMPRE con una de estas dos líneas (sin texto después):
  DEBATE_RESOLVED: REVISED
  DEBATE_RESOLVED: UNCHANGED
"""


# ── Nodo del grafo ────────────────────────────────────────────────────────────

def run_debate(state: FabricaState) -> dict:
    """
    VIII-3: Panel de debate inter-agente.
    Se ejecuta solo cuando risk_level == 'HIGH' y debate_done == False.
    Retorna actualizaciones parciales del estado.
    """
    master_plan = state.get("master_plan") or ""
    feature_id  = state.get("feature_id", "")

    if not master_plan:
        logger.warning("debate_panel: no hay master_plan — omitiendo debate")
        return {"debate_done": True, "debate_summary": "Sin plan — debate omitido"}

    logger.info("🎭 Debate inter-agente activado (RISK_LEVEL=HIGH) para: %s", state.get("feature_name"))

    # Notificar en el event bus para que la UI lo muestre
    def _emit_info(msg: str) -> None:
        if feature_id:
            try:
                from tools.event_bus import emit_info
                emit_info(feature_id, "Debate Panel", msg)
            except Exception:
                pass

    _emit_info("🎭 Debate inter-agente iniciado — RISK_LEVEL=HIGH")

    # Truncar plan para no exceder el contexto del modelo económico
    plan_snippet = master_plan[:3500]

    # ── Revisor 1: Arquitectura ───────────────────────────────────────────────
    review_1, _cost_r1 = call_agent(
        agent_key="a1_pm",
        agent_label="Debate Revisor 1 (Arquitectura)",
        task_content=_REVIEWER_1_PROMPT.format(plan=plan_snippet),
        model=MODEL_DEBATE,
        include_static=[],    # sin contexto estático para mantener el costo bajo
        feature_id=feature_id,
    )
    logger.debug("debate_panel: Revisor 1 → %s…", review_1[:100])

    # ── Revisor 2: Riesgos ────────────────────────────────────────────────────
    review_2, _cost_r2 = call_agent(
        agent_key="a1_pm",
        agent_label="Debate Revisor 2 (Riesgos)",
        task_content=_REVIEWER_2_PROMPT.format(plan=plan_snippet),
        model=MODEL_DEBATE,
        include_static=[],
        feature_id=feature_id,
    )
    logger.debug("debate_panel: Revisor 2 → %s…", review_2[:100])

    # ¿Hay objeciones reales en alguno de los dos revisores?
    r1_upper = review_1.upper()
    r2_upper = review_2.upper()
    has_objections = "OBJECIONES" in r1_upper or "OBJECIONES" in r2_upper

    if not has_objections:
        logger.info("debate_panel: ambos revisores aprobaron — plan sin cambios")
        _emit_info("✅ Ambos revisores aprobaron el plan — continuando sin cambios")
        summary = (
            f"**Revisor 1 (Arquitectura):** {review_1[:200]}\n\n"
            f"**Revisor 2 (Riesgos):** {review_2[:200]}\n\n"
            "**Resultado:** Plan aprobado sin cambios"
        )
        return {
            "debate_done":    True,
            "debate_summary": summary,
        }

    # ── Árbitro: A1 decide si revisar el plan ────────────────────────────────
    _emit_info("⚖️ Objeciones detectadas — árbitro (A1) evaluando revisión del plan…")

    arbitration, _cost_arb = call_agent(
        agent_key="a1_pm",
        agent_label="Debate Árbitro A1",
        task_content=_ARBITRATOR_PROMPT.format(
            plan=plan_snippet,
            review_1=review_1,
            review_2=review_2,
        ),
        model=MODEL_DEBATE,
        include_static=[],
        feature_id=feature_id,
    )

    # Determinar si el árbitro revisó el plan
    arb_upper = arbitration.upper()
    revised   = "DEBATE_RESOLVED: REVISED" in arb_upper

    summary = (
        f"**Revisor 1 (Arquitectura):**\n{review_1[:300]}\n\n"
        f"**Revisor 2 (Riesgos):**\n{review_2[:300]}\n\n"
        f"**Árbitro A1:** {'Plan **REVISADO** — objeciones incorporadas' if revised else 'Plan **SIN CAMBIOS** — objeciones consideradas menores'}"
    )

    updates: dict = {
        "debate_done":    True,
        "debate_summary": summary,
    }

    if revised:
        # El árbitro produjo un plan revisado — reemplazar master_plan
        # El texto del árbitro incluye el plan completo, los flags y la resolución
        updates["master_plan"] = arbitration
        logger.info("debate_panel: plan REVISADO por el árbitro")
        _emit_info("🔄 Plan REVISADO tras debate — continuando con el plan actualizado")
    else:
        logger.info("debate_panel: plan SIN CAMBIOS tras debate")
        _emit_info("✅ Plan aprobado por árbitro sin cambios — objeciones desestimadas")

    return updates
