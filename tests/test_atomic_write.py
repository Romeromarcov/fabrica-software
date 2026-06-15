"""Tests para la escritura atómica (PLAN_BLINDAJE_TOTAL A3.1)."""
import json
import os
import threading

import pytest

import tools.file_tools as file_tools
from tools.file_tools import atomic_write_text, save_run_metadata


def _tmp_files(directory):
    return [p for p in os.listdir(directory) if p.endswith(".tmp")]


def test_overwrite_and_no_leftover_tmp(tmp_path):
    p = tmp_path / "data.txt"
    atomic_write_text(p, "hello")
    atomic_write_text(p, "world")
    assert p.read_text(encoding="utf-8") == "world"
    assert _tmp_files(tmp_path) == []


def test_failure_keeps_original_intact(tmp_path, monkeypatch):
    p = tmp_path / "data.txt"
    p.write_text("original", encoding="utf-8")

    def boom(*args, **kwargs):
        raise OSError("simulated replace failure")

    monkeypatch.setattr(os, "replace", boom)

    with pytest.raises(OSError):
        atomic_write_text(p, "new content that must not land")

    # El archivo original queda intacto (no truncado ni vacío).
    assert p.read_text(encoding="utf-8") == "original"
    # No queda ningún temporal tras la limpieza.
    assert _tmp_files(tmp_path) == []


def test_concurrency_smoke(tmp_path, monkeypatch):
    monkeypatch.setattr(file_tools, "RUNS_DIR", tmp_path)
    feature_id = "feat-concurrencia"

    def worker(i):
        save_run_metadata(feature_id, {"feature_id": feature_id, f"key_{i}": i})

    threads = [threading.Thread(target=worker, args=(i,)) for i in range(10)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    meta_path = tmp_path / feature_id / "metadata.json"
    assert meta_path.exists()
    # JSON válido pese a la contención (lock + escritura atómica).
    data = json.loads(meta_path.read_text(encoding="utf-8"))
    assert data["feature_id"] == feature_id
    assert "updated_at" in data
    # No quedan temporales en el directorio del run.
    assert _tmp_files(tmp_path / feature_id) == []
