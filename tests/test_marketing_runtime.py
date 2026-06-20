"""Tests del runtime del pipeline `marketing` (nodes/marketing.py + graph_marketing.py).

La parte LLM se mockea (monkeypatch de call_agent en el módulo de nodos). Los nodos
deterministas (M7/M8) se prueban sin LLM. El grafo se construye/compila/ejecuta con todos
los agentes LLM mockeados.
"""
import pytest

import nodes.marketing as m
import graph_marketing as gm


# ── nodos LLM (call_agent mockeado) ────────────────────────────────────────────

def _mock_call(monkeypatch, output):
    monkeypatch.setattr(m, "call_agent", lambda **k: (output, None))


def test_m0_brief(monkeypatch):
    _mock_call(monkeypatch, "Brief estructurado")
    out = m.m0_brief({"brief": "crudo", "marca": "Acme"})
    assert out["brief"] == "Brief estructurado"
    assert out["current_agent"] == "m0_brief"


def test_m1_estratega_parses_signals(monkeypatch):
    _mock_call(monkeypatch, "Plan.\nRISK_LEVEL: HIGH\nCONFIDENCE_SCORE: 88\nNEEDS_HUMAN_ASSET: true")
    out = m.m1_estratega({"brief": "x"})
    assert out["risk_level"] == "HIGH"
    assert out["confidence_score"] == 88
    assert out["needs_human_asset"] is True


def test_m1_defaults_when_no_signals(monkeypatch):
    _mock_call(monkeypatch, "Plan sin marcadores")
    out = m.m1_estratega({"brief": "x"})
    assert out["risk_level"] == "MEDIUM"
    assert out["confidence_score"] == 70
    assert out["needs_human_asset"] is False


def test_m1_confidence_clamped(monkeypatch):
    _mock_call(monkeypatch, "RISK_LEVEL: LOW\nCONFIDENCE_SCORE: 250")
    assert m.m1_estratega({})["confidence_score"] == 100


def test_m2_copy(monkeypatch):
    _mock_call(monkeypatch, "Titular + CTA")
    assert m.m2_copy({"plan": "p"})["copy_output"] == "Titular + CTA"


def test_m3_arte(monkeypatch):
    _mock_call(monkeypatch, "Dirección de arte")
    assert m.m3_arte({"plan": "p"})["arte_output"] == "Dirección de arte"


def test_m4_ensamble(monkeypatch):
    _mock_call(monkeypatch, "Pieza final")
    assert m.m4_ensamble({"copy_output": "c", "arte_output": "a"})["pieza_ensamblada"] == "Pieza final"


def test_m5_brand_gate(monkeypatch):
    _mock_call(monkeypatch, "Coherente.\nBRAND_PASSED: true")
    assert m.m5_qa_marca({"pieza_ensamblada": "x"})["brand_passed"] is True
    _mock_call(monkeypatch, "Mal tono.\nBRAND_PASSED: false")
    assert m.m5_qa_marca({"pieza_ensamblada": "x"})["brand_passed"] is False


def test_m5_default_false_when_missing(monkeypatch):
    _mock_call(monkeypatch, "sin veredicto")
    assert m.m5_qa_marca({"pieza_ensamblada": "x"})["brand_passed"] is False


def test_m6_compliance_gate(monkeypatch):
    _mock_call(monkeypatch, "OK.\nCOMPLIANCE_CLEAR: true")
    assert m.m6_compliance({"pieza_ensamblada": "x"})["compliance_clear"] is True


# ── M6_5 adversarial: solo corre en riesgo HIGH ─────────────────────────────────

def test_m6_5_skipped_when_not_high(monkeypatch):
    # No debe llamar al LLM si el riesgo no es HIGH.
    def _boom(**k):
        raise AssertionError("no debió llamar al LLM en riesgo no-HIGH")
    monkeypatch.setattr(m, "call_agent", _boom)
    out = m.m6_5_adversarial({"risk_level": "LOW", "pieza_ensamblada": "x"})
    assert out["adversarial_clear"] is True
    assert out["cost_entries"] == []


def test_m6_5_runs_when_high(monkeypatch):
    _mock_call(monkeypatch, "Riesgoso.\nADVERSARIAL_CLEAR: false")
    out = m.m6_5_adversarial({"risk_level": "HIGH", "pieza_ensamblada": "x"})
    assert out["adversarial_clear"] is False


# ── M7 preview (determinista) ──────────────────────────────────────────────────

def test_m7_passes_when_pieza_and_gates_ok():
    out = m.m7_preview({"pieza_ensamblada": "lista", "brand_passed": True,
                        "compliance_clear": True, "adversarial_clear": True})
    assert out["preview_passed"] is True


def test_m7_fails_without_pieza():
    out = m.m7_preview({"pieza_ensamblada": "", "brand_passed": True,
                        "compliance_clear": True})
    assert out["preview_passed"] is False


def test_m7_fails_when_gate_failed():
    out = m.m7_preview({"pieza_ensamblada": "lista", "brand_passed": False,
                        "compliance_clear": True})
    assert out["preview_passed"] is False


# ── M8 publisher (determinista, gated) ──────────────────────────────────────────

def _all_clear():
    return {"brand_passed": True, "compliance_clear": True, "adversarial_clear": True,
            "preview_passed": True, "canal": "instagram", "pieza_nombre": "p1"}


def test_m8_blocked_when_gate_failed():
    out = m.m8_publisher({**_all_clear(), "brand_passed": False})
    assert out["published"] is False
    assert out["publish_ref"] is None
    assert out["errors"]


def test_m8_dryrun_by_default(monkeypatch):
    monkeypatch.setattr("config.MARKETING_PUBLISH_ENABLED", False, raising=False)
    out = m.m8_publisher(_all_clear())
    assert out["published"] is False
    assert out["publish_ref"].startswith("dryrun:")


def test_m8_publishes_when_enabled_and_clear(monkeypatch):
    monkeypatch.setattr("config.MARKETING_PUBLISH_ENABLED", True, raising=False)
    out = m.m8_publisher(_all_clear())
    assert out["published"] is True
    assert out["publish_ref"].startswith("published:")


# ── grafo: build / compile / ejecución end-to-end ──────────────────────────────

def test_build_and_compile_graph():
    g = gm.build_marketing_graph()
    assert g is not None
    app = gm.compile_marketing_graph(interrupt_publish=False)
    assert app is not None


def test_initial_state_contract():
    st = gm.initial_marketing_state(marca="Acme", canal="tiktok", brief="b")
    assert st["marca"] == "Acme" and st["canal"] == "tiktok"
    assert st["errors"] == [] and st["cost_entries"] == []


def test_end_to_end_reaches_publish_decision(monkeypatch):
    # Todos los agentes LLM aprueban; el flujo lineal llega a M8 y decide (dry-run).
    def _approve(**k):
        return ("ok\nRISK_LEVEL: LOW\nCONFIDENCE_SCORE: 90\nBRAND_PASSED: true\n"
                "COMPLIANCE_CLEAR: true\nADVERSARIAL_CLEAR: true", None)
    monkeypatch.setattr(m, "call_agent", _approve)
    monkeypatch.setattr("config.MARKETING_PUBLISH_ENABLED", False, raising=False)
    app = gm.compile_marketing_graph(interrupt_publish=False)
    final = app.invoke(gm.initial_marketing_state(marca="Acme", pieza_nombre="p1", brief="b"))
    assert final["brand_passed"] is True
    assert final["compliance_clear"] is True
    assert final["preview_passed"] is True
    assert final["publish_ref"].startswith("dryrun:")
