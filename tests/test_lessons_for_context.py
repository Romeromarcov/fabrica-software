"""
Tests F0.2 — Memoria semántica de lecciones cableada al aprendizaje.

Verifica:
  • `lessons_for_context` enruta a memoria semántica cuando VECTOR_MEMORY_ENABLED=true
    y degrada al bloque keyword (`load_lessons`) cuando el store está frío o el flag off.
  • `append_to_lessons` espeja los patrones a `vector_memory` (escritura que cubre A7 y A8),
    de modo que una lección persistida es recuperable luego por `lessons_for_context`.

El backend chromadb NO es requerido: se ejercita el fallback keyword aislado en tmp_path.
"""
import tools.vector_memory as vm
import tools.learning_memory as lm


def _isolate_store(tmp_path, monkeypatch):
    monkeypatch.setattr(vm, "_store_dir", lambda: tmp_path / "vmem")
    monkeypatch.setattr(vm, "backend", lambda: "keyword")


def test_lessons_for_context_uses_semantic_when_enabled(tmp_path, monkeypatch):
    _isolate_store(tmp_path, monkeypatch)
    monkeypatch.setattr(lm, "VECTOR_MEMORY_ENABLED", True, raising=False)
    monkeypatch.setattr("config.VECTOR_MEMORY_ENABLED", True, raising=False)

    repo = "/repos/omnierp"
    vm.record_lesson(repo, "[seguridad | ALTA] endpoint sin require_role expone datos", {})

    block = lm.lessons_for_context(repo, "seguridad require_role endpoint datos")
    assert "memoria" in block.lower()
    assert "require_role" in block


def test_lessons_for_context_falls_back_when_cold(tmp_path, monkeypatch):
    """Store semántico vacío → no regresa: usa el bloque keyword de load_lessons."""
    _isolate_store(tmp_path, monkeypatch)
    monkeypatch.setattr("config.VECTOR_MEMORY_ENABLED", True, raising=False)

    repo = tmp_path / "repo"
    (repo / "agents").mkdir(parents=True)
    (repo / lm.LESSONS_FILE).write_text(
        "# Lessons Learned\n\n- [2026-06-23 | feat | QA | ALTA] no olvidar validación de entrada\n",
        encoding="utf-8",
    )
    block = lm.lessons_for_context(str(repo), "consulta sin coincidencia semantica xyzqkw")
    assert "LECCIONES APRENDIDAS" in block
    assert "validación de entrada" in block


def test_lessons_for_context_keyword_when_disabled(tmp_path, monkeypatch):
    _isolate_store(tmp_path, monkeypatch)
    monkeypatch.setattr("config.VECTOR_MEMORY_ENABLED", False, raising=False)

    repo = tmp_path / "repo2"
    (repo / "agents").mkdir(parents=True)
    (repo / lm.LESSONS_FILE).write_text(
        "# Lessons Learned\n\n- [2026-06-23 | feat | SEC | ALTA] cerrar CORS abierto\n",
        encoding="utf-8",
    )
    block = lm.lessons_for_context(str(repo), "cualquier query")
    assert "cerrar CORS abierto" in block


def test_append_to_lessons_mirrors_to_vector_memory(tmp_path, monkeypatch):
    """La escritura de A7/A8 (append_to_lessons) indexa en la memoria semántica."""
    _isolate_store(tmp_path, monkeypatch)
    monkeypatch.setattr("config.VECTOR_MEMORY_ENABLED", True, raising=False)

    repo = tmp_path / "repo3"
    (repo / "agents").mkdir(parents=True)
    patterns = [{
        "date": "2026-06-23", "feature": "facturacion", "source": "qa",
        "severity": "ALTA", "category": "validacion",
        "description": "falta validar impuestos negativos en el endpoint de factura",
    }]
    assert lm.append_to_lessons(str(repo), patterns) is True

    # Recuperable por la memoria semántica del mismo repo.
    hits = vm.query(vm.namespace_for(str(repo)), "validar impuestos factura", top_k=3)
    assert hits
    assert "impuestos" in hits[0]["text"]
