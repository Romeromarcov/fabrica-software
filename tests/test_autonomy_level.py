"""
Tests F4.1 — HITL dial (AUTONOMY_LEVEL) modula las pausas del pipeline.

apply_autonomy_level es puro (override de la acción de aprobación). Se verifica que cada nivel
mapea correctamente y que _route_after_plan honra el dial → cambia el nodo humano destino.
Aceptación: cambiar el nivel (config/`/config`) altera las pausas sin tocar código.
"""
from tools.risk_classifier import apply_autonomy_level


# ── apply_autonomy_level (puro) ──────────────────────────────────────────────

def test_empty_level_keeps_action():
    for a in ("auto", "veto", "human"):
        assert apply_autonomy_level(a, level="") == a


def test_unknown_level_keeps_action():
    assert apply_autonomy_level("auto", level="loquesea") == "auto"


def test_auto_forces_auto():
    for a in ("auto", "veto", "human"):
        assert apply_autonomy_level(a, level="AUTO") == "auto"


def test_veto_caps_auto_but_respects_human():
    assert apply_autonomy_level("auto", level="VETO") == "veto"   # degrada auto→veto
    assert apply_autonomy_level("veto", level="VETO") == "veto"
    assert apply_autonomy_level("human", level="VETO") == "human"  # HIGH sigue humano


def test_manual_and_checkpoints_force_human():
    for lvl in ("MANUAL", "CHECKPOINTS"):
        for a in ("auto", "veto", "human"):
            assert apply_autonomy_level(a, level=lvl) == "human"


def test_level_is_case_insensitive():
    assert apply_autonomy_level("human", level="auto") == "auto"


def test_reads_config_when_level_none(monkeypatch):
    monkeypatch.setattr("config.AUTONOMY_LEVEL", "AUTO", raising=False)
    assert apply_autonomy_level("human") == "auto"
    monkeypatch.setattr("config.AUTONOMY_LEVEL", "", raising=False)
    assert apply_autonomy_level("human") == "human"


# ── _route_after_plan honra el dial ──────────────────────────────────────────

def _project_low_conf_state():
    # confianza alta + LOW + project_mode → normalmente "auto" (confidence_auto_approve).
    return {"risk_level": "LOW", "confidence_score": 95, "mode": "completo", "project_mode": True}


def test_route_auto_by_default(monkeypatch):
    import graph
    monkeypatch.setattr("config.AUTONOMY_LEVEL", "", raising=False)
    assert graph._route_after_plan(_project_low_conf_state()) == "confidence_auto_approve"


def test_route_manual_forces_stop_protocol(monkeypatch):
    import graph
    monkeypatch.setattr("config.AUTONOMY_LEVEL", "MANUAL", raising=False)
    # Aunque la confianza permita auto, MANUAL fuerza la aprobación manual.
    assert graph._route_after_plan(_project_low_conf_state()) == "stop_protocol"


def test_route_veto_downgrades_auto(monkeypatch):
    import graph
    monkeypatch.setattr("config.AUTONOMY_LEVEL", "VETO", raising=False)
    assert graph._route_after_plan(_project_low_conf_state()) == "veto_window"


def test_autonomy_level_exposed_in_config_store():
    from ui import config_store
    assert "AUTONOMY_LEVEL" in config_store.DEFAULTS
