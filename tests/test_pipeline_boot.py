"""Regresión de arranque del pipeline (bugs hallados por el E2E en vivo 2026-06-16).

1. `compile_graph()` / `compile_graph_project_mode()` deben compilar sin lanzar:
   con langgraph-checkpoint-sqlite 2.x/3.x, `SqliteSaver.from_conn_string()` devuelve
   un context manager (no un saver) → antes reventaba con TypeError al compilar.
2. `build_fewshots(None)` (modo feature standalone, sin project_id) no debe lanzar
   TypeError (`Path / None`) — debe devolver "" (sin ejemplos).
"""
import tempfile
from pathlib import Path

import pytest


def test_compile_graph_does_not_raise(monkeypatch):
    import graph
    # Apuntar el checkpointer a un sqlite temporal (no tocar el DB real).
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    monkeypatch.setattr(graph, "DB_PATH", Path(tmp.name))
    app = graph.compile_graph()
    assert app.__class__.__name__ == "CompiledStateGraph"
    app2 = graph.compile_graph_project_mode()
    assert app2.__class__.__name__ == "CompiledStateGraph"


def test_make_sqlite_checkpointer_returns_saver(monkeypatch):
    import graph
    from langgraph.checkpoint.sqlite import SqliteSaver
    tmp = tempfile.NamedTemporaryFile(suffix=".db", delete=False)
    tmp.close()
    monkeypatch.setattr(graph, "DB_PATH", Path(tmp.name))
    cp = graph._make_sqlite_checkpointer()
    assert isinstance(cp, SqliteSaver)


@pytest.mark.parametrize("pid", [None, "", 0])
def test_build_fewshots_without_project_id_returns_empty(pid):
    from tools.fewshot_builder import build_fewshots, _read_metrics
    assert build_fewshots(pid, context="backend") == ""
    assert _read_metrics(pid) == []
