"""Tests del documentador A12 (PLAN_PLATAFORMA_V2 M11, Fase 10)."""
from tools import doc_generator as dg


def test_changelog_groups_by_layer():
    files = ["apps/core/models.py", "apps/core/views.py", "src/App.tsx",
             "tests/test_x.py", "README.md"]
    out = dg.build_changelog("mi-feature", files)
    assert "Changelog — mi-feature" in out
    assert "### datos" in out and "models.py" in out
    assert "### backend/api" in out and "views.py" in out
    assert "### frontend" in out and "App.tsx" in out
    assert "### tests" in out
    assert "### docs" in out
    assert "Total:** 5" in out


def test_changelog_empty():
    out = dg.build_changelog("f", [])
    assert "Sin archivos escritos" in out


def test_changelog_with_summary():
    out = dg.build_changelog("f", ["a/models.py"], summary="Resumen del cambio.")
    assert "Resumen del cambio." in out


def test_mermaid_endpoints():
    routes = [{"method": "get", "path": "/api/items", "handler": "ItemList"},
              {"method": "post", "path": "/api/items", "handler": "ItemCreate"}]
    out = dg.mermaid_endpoints(routes)
    assert out.startswith("```mermaid")
    assert "flowchart LR" in out
    assert "GET /api/items" in out
    assert "ItemList" in out
    assert out.strip().endswith("```")


def test_mermaid_endpoints_empty():
    out = dg.mermaid_endpoints([])
    assert "Sin endpoints" in out


def test_mermaid_er():
    models = [{"name": "Empresa", "fields": ["id_empresa", "nombre"]},
              {"name": "Factura", "fields": []}]
    out = dg.mermaid_er(models)
    assert "erDiagram" in out
    assert "Empresa {" in out
    assert "nombre" in out
    assert "Factura {" in out  # sin fields → id por defecto
    assert "string id" in out


def test_mermaid_id_sanitization():
    out = dg.mermaid_endpoints([{"method": "GET", "path": "/x", "handler": "my-handler.view"}])
    # El id sanitizado no debe romper Mermaid (sin '.' ni '-').
    assert "my_handler_view" in out


def test_render_feature_docs_full():
    out = dg.render_feature_docs(
        "feat", ["apps/core/models.py"],
        routes=[{"method": "GET", "path": "/", "handler": "Home"}],
        models=[{"name": "M", "fields": ["a"]}],
    )
    assert "Changelog — feat" in out
    assert "## Endpoints" in out
    assert "## Modelo de datos" in out
    assert "erDiagram" in out
