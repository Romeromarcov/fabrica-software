"""Tests del Bloque B (PLAN_BLINDAJE_TOTAL).

B1.2 — A8.5 usa el tier efectivo = máx(tier de TEXTO, tier por RUTAS reales) ANTES de
       decidir si corre el análisis adversarial LLM (`do_llm`). Antes solo miraba
       `risk_level` (señal de planificación), dejando ciego un cambio cuyo plan parecía
       LOW pero que tocaba `apps/core/`.

B1.1 — Lightning salta todos los gates. Un "hotfix" lightning que toca rutas sensibles
       (p. ej. `apps/core/`) debe ASCENDER a "lite" para pasar por el sandbox/gates.

Herméticos: se parchea `call_agent` y `_gather_repo_context` para no tocar red ni disco.
Se prefieren las funciones puras (`_effective_tier`, `_maybe_upgrade_lightning`).
"""
from unittest.mock import Mock

import tools.file_tools as ft
import nodes.a85_adversarial as adv
import nodes.a10_code_writer as cw
from config import ADVERSARIAL_MIN_TIER


def _patch_runs(tmp_path, monkeypatch):
    monkeypatch.setattr(ft, "RUNS_DIR", tmp_path)
    monkeypatch.setattr(adv, "RUNS_DIR", tmp_path)


# ── B1.2: tier efectivo = máx(texto, rutas) ───────────────────────────────────

def test_b12_effective_tier_eleva_por_rutas():
    """risk_level=MEDIUM pero apps/core/ → el piso de rutas eleva a HIGH."""
    state = {
        "risk_level": "MEDIUM",
        "files_written": ["apps/core/models.py"],
        "repo_path": "",
        "feature_id": "t",
        "master_plan": "",
    }
    tier = adv._effective_tier(state)
    assert tier == "HIGH"
    # Con ADVERSARIAL_MIN_TIER por defecto (MEDIUM), HIGH dispara el LLM.
    assert adv._tier_at_least(tier, ADVERSARIAL_MIN_TIER) is True


def test_b12_effective_tier_low_cuando_todo_low():
    """risk_level=LOW + solo docs → tier efectivo LOW (no eleva)."""
    state = {
        "risk_level": "LOW",
        "files_written": ["docs/x.md"],
        "repo_path": "",
        "feature_id": "t",
        "master_plan": "",
    }
    tier = adv._effective_tier(state)
    assert tier == "LOW"
    assert adv._tier_at_least(tier, ADVERSARIAL_MIN_TIER) is False


def test_b12_node_corre_llm_cuando_rutas_sensibles(tmp_path, monkeypatch):
    """A8.5: apps/core/ con risk_level=MEDIUM → do_llm True → call_agent invocado."""
    _patch_runs(tmp_path, monkeypatch)
    mock_agent = Mock(return_value=("Todo OK.\nADVERSARIAL CLEAR", None))
    monkeypatch.setattr(adv, "call_agent", mock_agent)
    # Aislar del disco: contexto de repo no vacío para que llegue a call_agent.
    monkeypatch.setattr(adv, "_gather_repo_context", lambda *a, **k: "## CTX\n```python\n# x\n```")

    state = {
        "feature_id": "t",
        "repo_path": str(tmp_path),
        "files_written": ["apps/core/models.py"],
        "risk_level": "MEDIUM",
        "master_plan": "",
    }
    result = adv.a85_adversarial(state)

    assert mock_agent.called is True
    assert result["adversarial_clear"] is True


def test_b12_node_no_corre_llm_cuando_todo_low(tmp_path, monkeypatch):
    """A8.5: docs + risk_level=LOW → tier efectivo LOW → LLM NO invocado."""
    _patch_runs(tmp_path, monkeypatch)
    mock_agent = Mock(return_value=("ADVERSARIAL CLEAR", None))
    monkeypatch.setattr(adv, "call_agent", mock_agent)

    state = {
        "feature_id": "t",
        "repo_path": str(tmp_path),
        "files_written": ["docs/x.md"],
        "risk_level": "LOW",
        "master_plan": "",
    }
    result = adv.a85_adversarial(state)

    assert mock_agent.called is False
    assert result["adversarial_clear"] is True


# ── B1.1: lightning restringido por rutas reales ──────────────────────────────

def test_b11_lightning_eleva_a_lite_en_ruta_sensible():
    """lightning + apps/core/ → asciende a "lite" (pasará por el sandbox)."""
    assert cw._maybe_upgrade_lightning("lightning", ["apps/core/models.py"]) == "lite"


def test_b11_lightning_se_mantiene_si_todo_low():
    """lightning + solo docs (LOW) → se mantiene "lightning"."""
    assert cw._maybe_upgrade_lightning("lightning", ["docs/readme.md"]) == "lightning"


def test_b11_no_afecta_otros_modos():
    """El ascenso solo aplica a lightning; otros modos se devuelven sin cambios."""
    assert cw._maybe_upgrade_lightning("lite", ["apps/core/models.py"]) == "lite"
    assert cw._maybe_upgrade_lightning("completo", ["apps/core/models.py"]) == "completo"
    assert cw._maybe_upgrade_lightning("lightning", []) == "lightning"
