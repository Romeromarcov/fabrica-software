"""Tests de la memoria vectorial (PLAN_PLATAFORMA_V2 R1, Fase 2).

Se ejercita el FALLBACK por keywords (chromadb no requerido en CI). Almacén JSONL
aislado en tmp_path.
"""
import pytest

from tools import vector_memory as vm


@pytest.fixture(autouse=True)
def _tmp_store(tmp_path, monkeypatch):
    monkeypatch.setattr(vm, "_store_dir", lambda: tmp_path / "vmem")
    # Fuerza el backend keyword (no dependemos de chromadb en CI).
    monkeypatch.setattr(vm, "backend", lambda: "keyword")
    yield


def test_add_and_query_keyword_fallback():
    vm.add_memory("software:repoA", "Plan de facturación con multi-tenant e impuestos",
                  {"feature": "facturacion"})
    vm.add_memory("software:repoA", "Dashboard de inventario con gráficos", {"feature": "inv"})

    results = vm.query("software:repoA", "necesito facturación con impuestos", top_k=2)
    assert results
    assert "facturación" in results[0]["text"].lower()
    assert results[0]["metadata"]["feature"] == "facturacion"


def test_query_empty_namespace_returns_empty():
    assert vm.query("software:vacio", "lo que sea") == []


def test_namespaces_are_isolated():
    vm.add_memory("ns1", "alpha beta gamma", {})
    vm.add_memory("ns2", "delta epsilon", {})
    r1 = vm.query("ns1", "alpha", top_k=5)
    r2 = vm.query("ns2", "alpha", top_k=5)
    assert len(r1) == 1
    assert r2 == []   # 'alpha' no está en ns2


def test_add_empty_text_is_noop():
    assert vm.add_memory("ns", "") is False
    assert vm.query("ns", "x") == []


def test_query_ranks_by_overlap():
    vm.add_memory("ns", "auth login jwt token sesion", {})
    vm.add_memory("ns", "auth login basico", {})
    results = vm.query("ns", "auth login jwt token", top_k=2)
    # La entrada con más solapamiento de keywords va primero.
    assert results[0]["text"].startswith("auth login jwt")
    assert results[0]["score"] >= results[1]["score"]


def test_namespace_sanitization():
    vm.add_memory("software:repo/with spaces", "contenido x", {})
    assert vm.query("software:repo/with spaces", "contenido")


def test_chromadb_available_is_bool():
    assert isinstance(vm.chromadb_available(), bool)
