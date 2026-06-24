"""
nodes/marketing.py — Funciones-nodo del pipeline `marketing` (PLAN_PIPELINE_MARKETING).

Runtime del segundo dominio de la Plataforma V2. Cada nodo recibe y retorna un dict de
estado (contrato LangGraph), calcando el patrón del pipeline `software` (nodos en `nodes/`):
  - los nodos LLM llaman a `call_agent` (mismo router multi-proveedor; mockeable en tests
    vía `monkeypatch.setattr(nodes.marketing, "call_agent", ...)`),
  - los nodos deterministas (M7 preview, M8 publisher) no usan LLM: lógica pura y testeable,
  - sin side effects al importar.

Orden del grafo (lineal, definido en pipelines/marketing/pipeline.yaml):
  M0 Brief → M1 Estratega → M2 Copy → M3 Arte → M4 Ensamble → M5 QA Marca →
  M6 Compliance → M6_5 Adversarial → M7 Preview/specs → M8 Publisher.

Honestidad de alcance: M8 NO hace la llamada real a la API del canal (Instagram, etc.) —
esa es la arista de infra (credenciales vivas), igual que las señales vivas del Bloque D.
Produce la DECISIÓN de publicación y un `publish_ref`; el push real queda gated por
`MARKETING_PUBLISH_ENABLED` (default false → dry-run).
"""
from __future__ import annotations

import logging
import re

from nodes.base import call_agent

logger = logging.getLogger(__name__)


# ── Helpers deterministas ─────────────────────────────────────────────────────

def _parse_bool(text: str, token: str, default: bool) -> bool:
    """Lee 'TOKEN: true|false' del output del agente. `default` si no aparece."""
    m = re.search(rf"{token}:\s*(true|false)", text or "", re.IGNORECASE)
    return (m.group(1).lower() == "true") if m else default


def _parse_int(text: str, token: str, default: int) -> int:
    m = re.search(rf"{token}:\s*(\d+)", text or "", re.IGNORECASE)
    return int(m.group(1)) if m else default


def _cost_list(cost) -> list:
    """Normaliza el segundo retorno de call_agent a la lista de cost_entries del state."""
    return [cost] if cost else []


def _emit(agent_key: str, label: str, task: str, model: str) -> tuple[str, list]:
    """Llama al LLM del agente y devuelve (output, cost_entries)."""
    output, cost = call_agent(agent_key=agent_key, agent_label=label, task_content=task, model=model)
    return output or "", _cost_list(cost)


# ── M0 — Brief & Research ──────────────────────────────────────────────────────

def m0_brief(state: dict, model: str = "") -> dict:
    task = (
        "Eres M0 (Brief & Research) de un pipeline de marketing. A partir del brief crudo, "
        "produce un brief ESTRUCTURADO: objetivo claro, audiencia, mensaje clave, tono de marca "
        "y restricciones del canal. Sé conciso.\n\n"
        f"Marca: {state.get('marca', '')}\nCanal: {state.get('canal', '')}\n"
        f"Pieza: {state.get('pieza_nombre', '')}\nBrief crudo: {state.get('brief', '')}\n"
        f"Objetivo: {state.get('objetivo', '')}"
    )
    output, costs = _emit("m0_brief", "M0 Brief & Research", task, model)
    return {"brief": output or state.get("brief", ""), "current_agent": "m0_brief", "cost_entries": costs}


# ── M1 — Estratega ─────────────────────────────────────────────────────────────

def m1_estratega(state: dict, model: str = "") -> dict:
    task = (
        "Eres M1 (Estratega). Con el brief estructurado, define el PLAN de la pieza "
        "(concepto, formato, llamada a la acción). Al final escribe EXACTAMENTE estas líneas:\n"
        "RISK_LEVEL: LOW|MEDIUM|HIGH  (HIGH si toca salud, finanzas, política, menores o claims regulados)\n"
        "CONFIDENCE_SCORE: [0-100]\n"
        "NEEDS_HUMAN_ASSET: true|false  (true si requiere foto/video físico que no se puede generar)\n\n"
        f"Brief: {state.get('brief', '')}"
    )
    output, costs = _emit("m1_estratega", "M1 Estratega", task, model)
    risk_m = re.search(r"RISK_LEVEL:\s*(LOW|MEDIUM|HIGH)", output, re.IGNORECASE)
    risk = risk_m.group(1).upper() if risk_m else "MEDIUM"
    conf = max(0, min(100, _parse_int(output, "CONFIDENCE_SCORE", 70)))
    return {
        "plan": output,
        "risk_level": risk,
        "confidence_score": conf,
        "needs_human_asset": _parse_bool(output, "NEEDS_HUMAN_ASSET", False),
        "current_agent": "m1_estratega",
        "cost_entries": costs,
    }


# ── M2 — Copywriter ────────────────────────────────────────────────────────────

def m2_copy(state: dict, model: str = "") -> dict:
    task = (
        "Eres M2 (Copywriter). Escribe el COPY final de la pieza según el plan: titular, "
        "cuerpo y CTA, en el tono de la marca y los límites del canal. Solo el copy.\n\n"
        f"Plan: {state.get('plan', '')}\nCanal: {state.get('canal', '')}"
    )
    output, costs = _emit("m2_copy", "M2 Copywriter", task, model)
    return {"copy_output": output, "current_agent": "m2_copy", "cost_entries": costs}


# ── M3 — Director de Arte ──────────────────────────────────────────────────────

def m3_arte(state: dict, model: str = "") -> dict:
    task = (
        "Eres M3 (Director de Arte). Define la DIRECCIÓN DE ARTE de la pieza: composición, "
        "paleta, tipografía y un prompt de imagen detallado para el canal. Solo la dirección de arte.\n\n"
        f"Plan: {state.get('plan', '')}\nCanal: {state.get('canal', '')}"
    )
    output, costs = _emit("m3_arte", "M3 Director de Arte", task, model)
    return {"arte_output": output, "current_agent": "m3_arte", "cost_entries": costs}


# ── M4 — Editor / Ensamblador ──────────────────────────────────────────────────

def m4_ensamble(state: dict, model: str = "") -> dict:
    task = (
        "Eres M4 (Editor/Ensamblador). Une copy y arte en una PIEZA coherente lista para "
        "revisión: descripción final del post (texto + descripción visual + hashtags).\n\n"
        f"Copy: {state.get('copy_output', '')}\nArte: {state.get('arte_output', '')}"
    )
    output, costs = _emit("m4_ensamble", "M4 Editor/Ensamblador", task, model)
    return {"pieza_ensamblada": output, "current_agent": "m4_ensamble", "cost_entries": costs}


# ── M5 — QA de Marca (gate) ────────────────────────────────────────────────────

def m5_qa_marca(state: dict, model: str = "") -> dict:
    task = (
        "Eres M5 (QA de Marca). Verifica que la pieza respeta la identidad de marca (tono, "
        "claims, coherencia). Explica brevemente y termina con EXACTAMENTE:\n"
        "BRAND_PASSED: true|false\n\n"
        f"Marca: {state.get('marca', '')}\nPieza: {state.get('pieza_ensamblada', '')}"
    )
    output, costs = _emit("m5_qa_marca", "M5 QA de Marca", task, model)
    return {"brand_passed": _parse_bool(output, "BRAND_PASSED", False),
            "current_agent": "m5_qa_marca", "cost_entries": costs}


# ── M6 — Compliance & Brand Safety (gate) ──────────────────────────────────────

def m6_compliance(state: dict, model: str = "") -> dict:
    task = (
        "Eres M6 (Compliance & Brand Safety). Revisa la pieza por riesgos legales/regulatorios, "
        "claims no sustentados y brand safety. Explica y termina con EXACTAMENTE:\n"
        "COMPLIANCE_CLEAR: true|false\n\n"
        f"Pieza: {state.get('pieza_ensamblada', '')}"
    )
    output, costs = _emit("m6_compliance", "M6 Compliance", task, model)
    return {"compliance_clear": _parse_bool(output, "COMPLIANCE_CLEAR", False),
            "current_agent": "m6_compliance", "cost_entries": costs}


# ── M6_5 — Adversarial (gate, solo riesgo HIGH) ────────────────────────────────

def m6_5_adversarial(state: dict, model: str = "") -> dict:
    # Solo corre el análisis profundo en riesgo HIGH; si no, se considera despejado (skip).
    if str(state.get("risk_level", "")).upper() != "HIGH":
        return {"adversarial_clear": True, "current_agent": "m6_5_adversarial", "cost_entries": []}
    task = (
        "Eres M6.5 (Adversarial). La pieza es de riesgo ALTO. Busca activamente cómo podría "
        "malinterpretarse, ofender o violar políticas del canal. Termina con EXACTAMENTE:\n"
        "ADVERSARIAL_CLEAR: true|false\n\n"
        f"Pieza: {state.get('pieza_ensamblada', '')}"
    )
    output, costs = _emit("m6_5_adversarial", "M6.5 Adversarial", task, model)
    return {"adversarial_clear": _parse_bool(output, "ADVERSARIAL_CLEAR", False),
            "current_agent": "m6_5_adversarial", "cost_entries": costs}


# ── M7 — Preview / specs del canal (determinista, sin LLM) ──────────────────────

def m7_preview(state: dict, model: str = "") -> dict:
    """Chequeo determinista de specs: hay pieza ensamblada y los gates previos pasaron."""
    pieza = (state.get("pieza_ensamblada") or "").strip()
    gates_ok = bool(
        state.get("brand_passed") and state.get("compliance_clear")
        and state.get("adversarial_clear", True)
    )
    return {"preview_passed": bool(pieza) and gates_ok,
            "current_agent": "m7_preview", "cost_entries": []}


# ── M8 — Publisher (determinista, sin LLM; gated por flag) ──────────────────────

def m8_publisher(state: dict, model: str = "") -> dict:
    """
    Decisión de publicación. Publica solo si TODOS los gates pasaron. La llamada real al
    canal queda gated por `MARKETING_PUBLISH_ENABLED` (default false → dry-run): sin el flag
    se produce un `publish_ref` 'dryrun:' y `published=False`. El push real a la API del
    canal es la arista de infra (credenciales vivas), fuera de este núcleo.
    """
    import config
    all_clear = bool(
        state.get("brand_passed") and state.get("compliance_clear")
        and state.get("adversarial_clear", True) and state.get("preview_passed")
    )
    ref_base = f"{state.get('canal', 'canal')}:{state.get('pieza_nombre', 'pieza')}"
    if not all_clear:
        return {"published": False, "publish_ref": None, "current_agent": "m8_publisher",
                "errors": ["M8: publicación bloqueada — un gate de marketing no pasó."],
                "cost_entries": []}

    publish_enabled = getattr(config, "MARKETING_PUBLISH_ENABLED", False)
    if publish_enabled:
        # La llamada real al canal es infra-edge; aquí se registra la publicación aprobada.
        logger.info("M8: pieza aprobada y publicación habilitada → %s", ref_base)
        return {"published": True, "publish_ref": f"published:{ref_base}",
                "current_agent": "m8_publisher", "cost_entries": []}
    return {"published": False, "publish_ref": f"dryrun:{ref_base}",
            "current_agent": "m8_publisher", "cost_entries": []}


# ── Despacho id de agente → función-nodo ───────────────────────────────────────

MARKETING_NODES = {
    "M0": m0_brief,
    "M1": m1_estratega,
    "M2": m2_copy,
    "M3": m3_arte,
    "M4": m4_ensamble,
    "M5": m5_qa_marca,
    "M6": m6_compliance,
    "M6_5": m6_5_adversarial,
    "M7": m7_preview,
    "M8": m8_publisher,
}
