"""
Fase 6 — Prueba de aceptación: la fábrica se valida a sí misma.

Compone la lógica REAL de las Fases 1–3 (gates, adversarial, tier) para demostrar —no
asumir— que: un cambio peligroso se bloquea y va a humano; uno trivial fluye solo; uno
medio pasa por veto; un gate ausente falla; y la intervención humana se concentra en lo HIGH.

Herméticos (sin LLM, sin langgraph): tier LOW evita la rama LLM de A8.5.
"""
import shutil

import pytest

import tools.code_sandbox as cs
import tools.file_tools as ft
import nodes.a85_adversarial as adv
from tools.risk_classifier import approval_action, is_auto_mergeable, classify_change_risk
from nodes.a1_pr_final import _build_verifiable_guarantees


UNFILTERED_CORE = '''\
from rest_framework.generics import RetrieveAPIView
from .models import Empresa
class EmpresaDetailView(RetrieveAPIView):
    queryset = Empresa.objects.all()
'''


def _patch_runs(tmp_path, monkeypatch):
    monkeypatch.setattr(ft, "RUNS_DIR", tmp_path)
    monkeypatch.setattr(adv, "RUNS_DIR", tmp_path)


# ── 6.1 — CASO ROJO: cambio peligroso se BLOQUEA y va a humano ─────────────────

def test_red_case_blocks_and_routes_human(tmp_path, monkeypatch):
    _patch_runs(tmp_path, monkeypatch)
    # repo Django con manage.py no-op + DetailView de core sin filtro
    (tmp_path / "requirements.txt").write_text("django")
    (tmp_path / "manage.py").write_text("import sys; sys.exit(0)")
    core = tmp_path / "apps" / "core"
    core.mkdir(parents=True)
    (core / "models.py").write_text("class Empresa:\n    id_empresa=None\n")
    (core / "views.py").write_text(UNFILTERED_CORE)

    # (a) Sandbox: el gate de aislamiento bloquea
    sandbox = cs.run_all_checks(str(tmp_path), install_deps=False)
    assert sandbox["passed"] is False
    assert "tenant-isolation" in {gf["gate"] for gf in sandbox["gate_failures"]}

    # (b) A8.5 adversarial bloquea por la View vecina (escaneo estático a nivel repo).
    #     B1.2: `apps/core/` eleva el tier efectivo a HIGH → do_llm=True; se mockea
    #     `call_agent` para no tocar red. El bloqueo lo garantiza el escaneo estático
    #     (static_block) con independencia del veredicto del LLM.
    from unittest.mock import Mock
    monkeypatch.setattr(adv, "call_agent", Mock(return_value=("ADVERSARIAL CLEAR", None)))
    state = {"feature_id": "red", "repo_path": str(tmp_path),
             "files_written": ["apps/core/views.py"], "risk_level": "LOW",
             "feature_name": "x", "master_plan": ""}
    res = adv.a85_adversarial(state)
    assert res["adversarial_clear"] is False

    # (c) Tier por rutas = HIGH → gate de arranque manda a humano
    assert classify_change_risk(["apps/core/views.py"]) == "HIGH"
    assert approval_action("HIGH", 95, "completo", True) == "human"

    # (d) Nunca auto-mergeable (gate no verde)
    assert is_auto_mergeable(["apps/core/views.py"], "HIGH", False, True) is False


# ── 6.2 — CASO VERDE: cambio trivial LOW con gates verdes → auto ───────────────

def test_green_case_auto_flows(tmp_path, monkeypatch):
    _patch_runs(tmp_path, monkeypatch)
    ft.save_run_metadata("green", {"security_verdict": "CLEARANCE"})
    state = {"feature_id": "green", "sandbox_passed": True,
             "sandbox_gate_failures": [], "adversarial_clear": True}
    _md, all_green = _build_verifiable_guarantees(state)
    assert all_green is True
    assert approval_action("LOW", 90, "completo", True) == "auto"
    assert is_auto_mergeable(["docs/guia.md", "frontend/src/i18n/es.json"], "LOW", True, True) is True


# ── 6.3 — CASO AMARILLO: cambio MEDIUM → veto, no auto-merge ───────────────────

def test_yellow_case_veto():
    assert classify_change_risk(["apps/ventas/serializers.py"]) == "MEDIUM"
    assert approval_action("MEDIUM", 75, "completo", True) == "veto"
    # MEDIUM nunca es auto-mergeable aunque el gate esté verde
    assert is_auto_mergeable(["apps/ventas/serializers.py"], "MEDIUM", True, True) is False


# ── 6.4 — GATE AUSENTE: herramienta requerida ausente → FAIL (no skip) ─────────

def test_gate_absent_fails(tmp_path, monkeypatch):
    repo = tmp_path / "fe"
    repo.mkdir()
    (repo / "package.json").write_text('{"scripts":{},"devDependencies":{"vitest":"^1"}}')
    (repo / "tsconfig.json").write_text("{}")
    monkeypatch.setattr(cs, "STRICT_GATES", True)
    monkeypatch.setattr(cs, "_has", lambda tool: False)   # npx ausente
    result = cs.run_all_checks(str(repo), install_deps=False)
    assert result["passed"] is False
    assert "tsc" in result["missing_required"]


# ── 6.5 — MÉTRICA: la intervención humana se concentra en lo HIGH ──────────────

def test_human_intervention_concentrated_on_high():
    # Mezcla representativa: 6 LOW, 3 MEDIUM, 1 HIGH
    changes = (
        [(["docs/a.md"], "LOW")] * 6
        + [(["apps/ventas/serializers.py"], "MEDIUM")] * 3
        + [(["apps/core/views.py"], "HIGH")] * 1
    )
    human = 0
    for files, _ in changes:
        tier = classify_change_risk(files)
        if approval_action(tier, 90, "completo", True) == "human":
            human += 1
    # Solo el cambio HIGH toca a un humano en el arranque → 10%
    assert human == 1

    # Y TODO HIGH va a humano, sin excepción
    for conf in (50, 70, 95):
        assert approval_action("HIGH", conf, "completo", True) == "human"
    # Ningún HIGH es auto-mergeable
    assert is_auto_mergeable(["apps/core/views.py"], "HIGH", True, True) is False


@pytest.mark.skipif(shutil.which("git") is None, reason="git no disponible")
def test_red_case_path_is_recognized_high():
    """Sanidad: el archivo de CRIT-1..3 siempre es HIGH."""
    assert classify_change_risk(["backend/apps/core/views.py"]) == "HIGH"
