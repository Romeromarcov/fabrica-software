"""
Clasificador de riesgo por RADIO DE IMPACTO (Fase 3 del PLAN_HARDENING_FABRICA).

Reemplaza la "confianza auto-declarada por el LLM" por una señal determinista derivada
de QUÉ archivos toca el cambio. Reutiliza y extiende el patrón de
`branch_manager.classify_conflict_severity`.

Política (alineada con la superficie de alto riesgo de OmniERP):
  🔴 HIGH   — apps/core, auth/JWT, migraciones, dinero/Decimal, contabilidad,
              localizacion*, settings, permisos, get_queryset (multi-tenant).
  🟡 MEDIUM — serializers, services compartidos, views/viewsets/urls, api, signals,
              y cualquier archivo de código no clasificable como LOW.
  🟢 LOW    — tests, docs, i18n/locale, fixtures, archivos no-código (.md, .txt, .json
              de traducción), UI copy.

El LLM puede SUBIR el tier (declarar más riesgo), nunca bajarlo por debajo del de rutas.
"""
from __future__ import annotations

_ORDER = {"LOW": 0, "MEDIUM": 1, "HIGH": 2}

# Rutas/keywords de alto riesgo (radio de impacto amplio o irreversible).
_HIGH_PATH = (
    "apps/core/", "/core/", "settings", "/migrations/", "migrations/",
    "contabilidad", "localizacion", "localizacion_ve", "/auth", "auth/",
    "jwt", "permission", "permisos", "/security",
)
_HIGH_NAME = ("models.py", "settings.py")
# Lógica de negocio: medio riesgo.
_MEDIUM_PATH = (
    "serializer", "service", "views", "viewset", "/api", "signals",
    "urls", "tasks.py", "mcp.py",
)
# Señales LOW (se evalúan primero: un test que menciona "models" sigue siendo LOW).
# Tokens precisos para no confundir subcadenas (p. ej. "contests" no es "test").
_LOW_PATH = (
    "/test", "test_", "_test", ".test.", ".spec.", "__tests__",
    "/docs/", "docs/", "readme", "i18n", "locale", "fixture",
    "changelog", ".stories.", ".md", ".rst", ".txt",
)
_CODE_EXT = (".py", ".ts", ".tsx", ".js", ".jsx", ".vue")

# Palabras de alto riesgo para clasificar TEXTO (planificación, sin diff todavía).
_HIGH_TEXT = (
    "apps/core", "multi-tenant", "multitenant", "aislamiento", "id_empresa",
    "get_queryset", "migracion", "migración", "migration", "contabilidad",
    "asiento", "localizacion", "localización", "decimal", "dinero", "moneda",
    "auth", "jwt", "permiso", "settings", "fiscal", "igtf", "retencion",
)
_MEDIUM_TEXT = (
    "serializer", "endpoint", "viewset", "view", "service", "api", "crud",
    "modelo", "model", "campo", "field",
)


def _norm(path: str) -> str:
    return path.lower().replace("\\", "/")


def classify_path(path: str) -> str:
    """Clasifica el tier de riesgo de UN archivo por su ruta/nombre."""
    p = _norm(path)
    # LOW primero: tests/docs/i18n ganan aunque mencionen 'models'.
    if any(k in p for k in _LOW_PATH):
        return "LOW"
    if any(k in p for k in _HIGH_PATH) or any(p.endswith(n) for n in _HIGH_NAME):
        return "HIGH"
    if any(k in p for k in _MEDIUM_PATH):
        return "MEDIUM"
    # Archivo de código sin clasificar → MEDIUM (conservador, no se asume LOW).
    if p.endswith(_CODE_EXT):
        return "MEDIUM"
    # No-código (configs sueltas, .md, .json de datos) → LOW.
    return "LOW"


def classify_change_risk(modified_files: list[str]) -> str:
    """Tier de riesgo de un conjunto de archivos modificados (el máximo)."""
    if not modified_files:
        return "LOW"
    tiers = [classify_path(f) for f in modified_files]
    if "HIGH" in tiers:
        return "HIGH"
    if "MEDIUM" in tiers:
        return "MEDIUM"
    return "LOW"


def classify_text_risk(text: str) -> str:
    """Tier de riesgo a partir de TEXTO (p. ej. el MASTER_PLAN), cuando aún no hay diff.

    Heurística de planificación: si el plan menciona dominios de alto riesgo, el piso
    es HIGH; si menciona lógica de negocio, MEDIUM; si no, LOW.
    """
    if not text:
        return "LOW"
    t = text.lower()
    if any(k in t for k in _HIGH_TEXT):
        return "HIGH"
    if any(k in t for k in _MEDIUM_TEXT):
        return "MEDIUM"
    return "LOW"


def max_tier(*tiers: str) -> str:
    """Devuelve el tier más alto de los dados (el LLM puede subir, no bajar)."""
    best = "LOW"
    for t in tiers:
        if _ORDER.get((t or "LOW").upper(), 0) > _ORDER[best]:
            best = (t or "LOW").upper()
    return best


def tier_at_least(tier: str, minimum: str) -> bool:
    return _ORDER.get((tier or "LOW").upper(), 0) >= _ORDER.get(minimum.upper(), 0)
