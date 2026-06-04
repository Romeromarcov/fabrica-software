"""Test de Fase 7.2 — reporte de gobernanza por feature (observabilidad)."""
import tools.file_tools as ft
import tools.governance_report as gr


def test_feature_governance_reads_metadata(tmp_path, monkeypatch):
    monkeypatch.setattr(ft, "RUNS_DIR", tmp_path)
    ft.save_run_metadata("feat-gov", {
        "status": "completado",
        "risk_level_llm": "LOW",
        "risk_level_path": "HIGH",
        "risk_level": "HIGH",
        "risk_level_final": "HIGH",
        "security_verdict": "CLEARANCE",
        "adversarial_verdict": "ADVERSARIAL BLOCK",
        "approval_mode": "veto_window",
        "auto_mergeable": False,
        "confidence_score": 80,
    })
    gov = gr.feature_governance("feat-gov")
    # El LLM dijo LOW pero las rutas subieron a HIGH — la observabilidad lo expone
    assert gov["risk_llm"] == "LOW"
    assert gov["risk_path"] == "HIGH"
    assert gov["risk_final"] == "HIGH"
    assert gov["adversarial_verdict"] == "ADVERSARIAL BLOCK"
    assert gov["auto_mergeable"] is False

    md = gr.format_governance_md(gov)
    assert "Gobernanza" in md
    assert "Auto-merge: no" in md


def test_feature_governance_missing_metadata(tmp_path, monkeypatch):
    monkeypatch.setattr(ft, "RUNS_DIR", tmp_path)
    gov = gr.feature_governance("inexistente")
    assert gov["risk_final"] == "—"
    assert gov["auto_mergeable"] is False
