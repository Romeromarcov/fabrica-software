"""
CTF-FABRICA-001 — el merge_coordinator NO debe fugar worktrees en los paths de conflicto.

Antes, `_cleanup_worktrees` solo corría en los paths de merge limpio (CASO 1 y CASO 3
SECUENCIAL/SELECTIVO). En conflicto HIGH (RESOLVER/CANCELAR) y CASO 3 ESCALAR, los
worktrees del batch quedaban huérfanos en `.fabrica_worktrees/`, acumulándose entre runs
y arriesgando reutilización de un checkout sucio. Estos tests fijan que todos los paths
terminales limpian.
"""
import pytest

pytest.importorskip("langgraph")  # merge_coordinator importa langgraph


def _make_state():
    return {
        "parallel_batch": [0, 1],
        "repo_path": "/tmp/fake_repo",
        "project_id": "proj-1",
        "project_name": "Demo",
        "backlog": [
            {"name": "Feature A", "feature_id": "20260618_100000_a",
             "description": "x", "acceptance_criteria": ""},
            {"name": "Feature B", "feature_id": "20260618_100001_b",
             "description": "y", "acceptance_criteria": ""},
        ],
    }


def _force_high_conflict(monkeypatch, mc):
    """Monkeypatchea el módulo para que el flujo llegue a un conflicto HIGH sin LLM ni git."""
    monkeypatch.setattr(mc, "get_branch_modified_files", lambda branch, repo: ["models.py"])
    monkeypatch.setattr(
        mc, "detect_file_conflicts",
        lambda branch_files: [{"file": "models.py", "branches": ["Feature A", "Feature B"]}],
    )
    monkeypatch.setattr(mc, "classify_conflict_severity", lambda conflicts: "HIGH")
    monkeypatch.setattr(mc, "format_conflict_report", lambda *a, **k: "REPORTE")
    monkeypatch.setattr(mc, "save_run_metadata", lambda *a, **k: None)
    monkeypatch.setattr(mc, "_notify_telegram_conflict", lambda *a, **k: None)
    # Spy de la limpieza
    calls = []
    monkeypatch.setattr(mc, "_cleanup_worktrees", lambda repo, fids: calls.append((repo, list(fids))))
    return calls


def test_cleanup_runs_on_high_conflict_cancelar(monkeypatch):
    from nodes import merge_coordinator as mc
    calls = _force_high_conflict(monkeypatch, mc)
    monkeypatch.setattr(mc, "interrupt", lambda payload: "CANCELAR")

    out = mc.merge_coordinator(_make_state())

    assert len(calls) == 1, "CANCELAR debe limpiar los worktrees del batch"
    assert calls[0][1] == ["20260618_100000_a", "20260618_100001_b"]
    assert out["merge_conflict_resolved"] is False


def test_cleanup_runs_on_high_conflict_resolver(monkeypatch):
    from nodes import merge_coordinator as mc
    calls = _force_high_conflict(monkeypatch, mc)
    monkeypatch.setattr(mc, "interrupt", lambda payload: "RESOLVER")

    out = mc.merge_coordinator(_make_state())

    assert len(calls) == 1, "RESOLVER debe limpiar los worktrees del batch"
    assert calls[0][1] == ["20260618_100000_a", "20260618_100001_b"]
    assert out["merge_conflict_resolved"] is True


def test_no_cleanup_when_no_feature_ids(monkeypatch):
    """Path temprano (sin feature_id) no intenta limpiar (no hay worktrees creados)."""
    from nodes import merge_coordinator as mc
    calls = _force_high_conflict(monkeypatch, mc)
    state = _make_state()
    state["backlog"] = [{"name": "Sin id"}, {"name": "Tampoco"}]
    mc.merge_coordinator(state)
    assert calls == []
