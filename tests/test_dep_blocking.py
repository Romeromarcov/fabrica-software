"""B3.1 — Validación del grafo de dependencias.

Un feature cuya dependencia esté en estado `failed`/`escalated` NO debe
arrancar: queda bloqueado y se omite. Antes, un fallo desbloqueaba al
dependiente; B3.1 invierte esa regla (con opción de opt-out backward-compat).
"""


def test_get_ready_indices_blocks_on_failed_dep():
    from tools.branch_manager import get_ready_indices

    backlog = [
        {"name": "A", "status": "failed", "depends_on": []},
        {"name": "B", "status": "pending", "depends_on": ["A"]},
        {"name": "C", "status": "pending", "depends_on": []},
    ]
    # Default block_on_failed_deps=True → B bloqueado, solo C lista.
    ready = get_ready_indices(backlog, {"B": ["A"]}, max_parallel=5)
    assert ready == [2]  # índice de C, NO el de B


def test_get_ready_indices_old_behavior_optout():
    from tools.branch_manager import get_ready_indices

    backlog = [
        {"name": "A", "status": "failed", "depends_on": []},
        {"name": "B", "status": "pending", "depends_on": ["A"]},
        {"name": "C", "status": "pending", "depends_on": []},
    ]
    # block_on_failed_deps=False → comportamiento antiguo: fallo "satisface" la dep.
    ready = get_ready_indices(backlog, {"B": ["A"]}, max_parallel=5,
                              block_on_failed_deps=False)
    assert 1 in ready  # B vuelve a estar lista


def test_get_ready_indices_completed_dep_unblocks():
    from tools.branch_manager import get_ready_indices

    backlog = [
        {"name": "A", "status": "completed", "depends_on": []},
        {"name": "B", "status": "pending", "depends_on": ["A"]},
    ]
    ready = get_ready_indices(backlog, {"B": ["A"]}, max_parallel=5)
    assert ready == [1]  # dependencia completada → B lista


def test_blocked_feature_indices():
    from tools.branch_manager import blocked_feature_indices

    backlog = [
        {"name": "A", "status": "failed", "depends_on": []},
        {"name": "B", "status": "pending", "depends_on": ["A"]},
        {"name": "C", "status": "pending", "depends_on": []},
    ]
    blocked = blocked_feature_indices(backlog, {"B": ["A"]})
    assert blocked == {1: ["A"]}  # solo B, culpable A


def test_pick_next_feature_skips_failed_dep(monkeypatch):
    import graph_project

    monkeypatch.setattr(graph_project, "save_run_metadata", lambda *a, **k: None)

    state = {
        "project_id": "p1",
        "backlog": [
            {"name": "A", "status": "failed", "depends_on": []},
            {"name": "B", "status": "pending", "depends_on": ["A"]},
            {"name": "C", "status": "pending", "depends_on": []},
        ],
        "dependency_graph": {"B": ["A"]},
    }
    out = graph_project.pick_next_feature(state)
    # Debe elegir C (índice 2), no B (bloqueado por A fallida).
    assert out["current_feature_index"] == 2
    assert out["backlog"][2]["status"] == "running"
    assert out["backlog"][1]["status"] == "pending"  # B sigue sin arrancar
