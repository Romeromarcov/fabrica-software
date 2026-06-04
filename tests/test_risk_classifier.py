"""Tests del clasificador de riesgo por radio de impacto (Fase 3)."""
from tools.risk_classifier import (
    classify_path,
    classify_change_risk,
    classify_text_risk,
    max_tier,
    tier_at_least,
)


def test_classify_path_high():
    assert classify_path("backend/apps/core/views.py") == "HIGH"
    assert classify_path("backend/apps/ventas/migrations/0002_x.py") == "HIGH"
    assert classify_path("backend/apps/x/models.py") == "HIGH"
    assert classify_path("backend/apps/contabilidad/services.py") == "HIGH"
    assert classify_path("backend/config/settings.py") == "HIGH"
    assert classify_path("backend/apps/localizacion_ve/adapters.py") == "HIGH"


def test_classify_path_medium():
    assert classify_path("backend/apps/ventas/serializers.py") == "MEDIUM"
    assert classify_path("backend/apps/ventas/views.py") == "MEDIUM"
    assert classify_path("frontend/src/components/Foo.tsx") == "MEDIUM"
    assert classify_path("backend/apps/x/random_logic.py") == "MEDIUM"


def test_classify_path_low():
    assert classify_path("backend/apps/ventas/tests/test_views.py") == "LOW"
    assert classify_path("test_smoke.py") == "LOW"
    assert classify_path("docs/README.md") == "LOW"
    assert classify_path("frontend/src/i18n/es.json") == "LOW"
    assert classify_path("CHANGELOG.md") == "LOW"


def test_contests_is_not_a_test():
    """Regresión: 'contests' contiene 'test' como subcadena pero NO es un test."""
    assert classify_path("backend/apps/contests/views.py") == "MEDIUM"


def test_classify_change_risk_takes_max():
    assert classify_change_risk(["docs/x.md", "apps/core/views.py"]) == "HIGH"
    assert classify_change_risk(["apps/ventas/serializers.py", "docs/x.md"]) == "MEDIUM"
    assert classify_change_risk(["docs/x.md", "tests/test_a.py"]) == "LOW"
    assert classify_change_risk([]) == "LOW"


def test_crit_1_to_3_path_is_high():
    """El archivo de CRIT-1..3 (apps/core/views.py) clasifica HIGH → siempre humano."""
    assert classify_change_risk(["backend/apps/core/views.py"]) == "HIGH"


def test_classify_text_risk():
    assert classify_text_risk("Refactor del aislamiento multi-tenant en apps/core") == "HIGH"
    assert classify_text_risk("Añadir asiento contable automático") == "HIGH"
    assert classify_text_risk("Nuevo serializer para el endpoint de productos") == "MEDIUM"
    assert classify_text_risk("Cambiar el texto del botón de bienvenida") == "LOW"


def test_max_tier_llm_can_only_raise():
    # LLM dice LOW pero las rutas dicen HIGH → gana HIGH
    assert max_tier("LOW", "HIGH") == "HIGH"
    # LLM dice HIGH y rutas MEDIUM → gana HIGH (el LLM puede subir)
    assert max_tier("HIGH", "MEDIUM") == "HIGH"
    assert max_tier("LOW", "LOW") == "LOW"
    assert max_tier("MEDIUM", "LOW") == "MEDIUM"


def test_tier_at_least():
    assert tier_at_least("HIGH", "MEDIUM") is True
    assert tier_at_least("LOW", "MEDIUM") is False
