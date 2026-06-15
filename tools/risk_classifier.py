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


# ── Fase 4: utilidades de paralelismo seguro ──────────────────────────────────

def select_parallel_safe(indices, tier_of) -> list:
    """Filtra los índices candidatos para que NINGÚN feature HIGH corra en paralelo.

    - Si el primer candidato es HIGH → se devuelve solo ese (HIGH corre en serie).
    - Si no → se devuelven los candidatos no-HIGH (los HIGH se difieren a la
      siguiente ronda, donde quedarán de primeros y correrán solos).

    `tier_of(idx) -> "LOW"|"MEDIUM"|"HIGH"`. Función pura (sin langgraph) para tests.
    """
    indices = list(indices)
    if not indices:
        return []
    if (tier_of(indices[0]) or "MEDIUM").upper() == "HIGH":
        return [indices[0]]
    safe = [i for i in indices if (tier_of(i) or "MEDIUM").upper() != "HIGH"]
    return safe or [indices[0]]


def batch_tier(texts: list[str]) -> str:
    """Tier agregado de un lote de features (máximo de sus textos)."""
    if not texts:
        return "LOW"
    return max_tier(*[classify_text_risk(t) for t in texts])


def approval_action(tier: str, confidence: int, mode: str, project_mode: bool) -> str:
    """Decisión del gate de aprobación de arranque (única fuente de verdad).

    Devuelve: "auto" (auto-aprueba) · "veto" (ventana de veto) · "human" (stop manual).
    El tier (ya con piso de rutas, Fase 3) gobierna; la confianza solo afina dentro de LOW.
    """
    if mode == "lightning":
        return "auto"
    if not project_mode:
        return "human"                      # standalone: siempre aprobación manual
    t = (tier or "MEDIUM").upper()
    if confidence >= 85 and t == "LOW":
        return "auto"
    if confidence >= 60 and t != "HIGH":
        return "veto"
    return "human"                          # HIGH (o baja confianza) → humano obligatorio


def final_risk_for_merge(files_written: list[str], base_risk: str, gate_all_green: bool) -> str:
    """Tier final para la decisión de auto-merge: máx(base, rutas del diff); gate no
    verde fuerza HIGH (F3.4). Única fuente de verdad usada por a1_pr_final."""
    fr = max_tier(base_risk, classify_change_risk(files_written))
    return "HIGH" if not gate_all_green else fr


def is_auto_mergeable(files_written: list[str], base_risk: str,
                      gate_all_green: bool, auto_merge_enabled: bool,
                      *, independent_review_passed: bool = True) -> bool:
    """Solo tier LOW + gate verde + flag activo + revisor independiente verde es
    auto-mergeable (C3).

    Auto-merge se permite SOLO si:
        auto_merge_enabled AND fr == "LOW" AND gate_all_green AND independent_review_passed

    `independent_review_passed` (keyword-only, default True para compatibilidad con
    los call sites/tests existentes que pasan 4 args posicionales) refleja el estado
    del revisor independiente (una GitHub Action que corre fuera de este pipeline).
    Si el pipeline NO tiene confirmación de que el revisor independiente pasó, el
    llamador debe pasar False, y el auto-merge queda conservadoramente DENEGADO."""
    fr = final_risk_for_merge(files_written, base_risk, gate_all_green)
    return bool(
        auto_merge_enabled
        and fr == "LOW"
        and gate_all_green
        and independent_review_passed
    )
