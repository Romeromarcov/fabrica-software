"""Tests de F1.4 (artefacto de seguridad) y F1.5 (checklist desde gates).

Verifican que la decisión de "apto para cierre" sale de RESULTADOS DE GATES y del
veredicto de seguridad persistido, no del texto libre del agente.
"""
import tools.file_tools as ft


def _patch_runs_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(ft, "RUNS_DIR", tmp_path)


def test_save_security_report_writes_verdict(tmp_path, monkeypatch):
    _patch_runs_dir(tmp_path, monkeypatch)
    path = ft.save_security_report("feat-1", "CLEARANCE", "sin hallazgos")
    content = (tmp_path / "feat-1" / "SECURITY_REPORT.md").read_text(encoding="utf-8")
    assert "SECURITY_REPORT.md" in path
    assert "**Veredicto:** CLEARANCE" in content
    assert "sin hallazgos" in content


def test_guarantees_all_green(tmp_path, monkeypatch):
    _patch_runs_dir(tmp_path, monkeypatch)
    ft.save_run_metadata("feat-ok", {"security_verdict": "CLEARANCE",
                                     "security_report": "x/SECURITY_REPORT.md"})
    from nodes.a1_pr_final import _build_verifiable_guarantees
    state = {"feature_id": "feat-ok", "sandbox_passed": True, "sandbox_gate_failures": []}
    md, all_green = _build_verifiable_guarantees(state)
    assert all_green is True
    assert "APTO" in md


def test_guarantees_blocks_on_tenant_failure(tmp_path, monkeypatch):
    _patch_runs_dir(tmp_path, monkeypatch)
    ft.save_run_metadata("feat-leak", {"security_verdict": "CLEARANCE"})
    from nodes.a1_pr_final import _build_verifiable_guarantees
    state = {
        "feature_id": "feat-leak",
        "sandbox_passed": False,
        "sandbox_gate_failures": [
            {"gate": "tenant-isolation", "layer": "backend", "stderr": "leak", "hard": True}
        ],
    }
    md, all_green = _build_verifiable_guarantees(state)
    assert all_green is False
    assert "NO APTO" in md
    assert "requiere revisión humana" in md.lower() or "requiere humano" in md.lower()


def test_guarantees_blocks_on_security_unfixable(tmp_path, monkeypatch):
    _patch_runs_dir(tmp_path, monkeypatch)
    ft.save_run_metadata("feat-sec", {"security_verdict": "UNFIXABLE"})
    from nodes.a1_pr_final import _build_verifiable_guarantees
    state = {"feature_id": "feat-sec", "sandbox_passed": True, "sandbox_gate_failures": []}
    md, all_green = _build_verifiable_guarantees(state)
    assert all_green is False
