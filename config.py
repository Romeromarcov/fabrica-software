"""Configuración central del orquestador. Un solo lugar para cambiar modelos y rutas."""
from pathlib import Path
import os
from dotenv import load_dotenv

load_dotenv()

# ── Rutas de la fábrica ───────────────────────────────────────────────────────
FABRICA_DIR = Path(__file__).parent
RUNS_DIR    = Path(os.getenv("RUNS_DIR", str(FABRICA_DIR / "data" / "runs")))
DB_PATH     = Path(os.getenv("DB_PATH",  str(FABRICA_DIR / "data" / "fabrica_state.db")))

# ── Multi-repo: directorio raíz donde viven todos los proyectos ───────────────
# En Docker: /workspace = C:\Users\PC\Proyectos
# En Windows nativo: configura WORKSPACES_ROOT en .env (ej: C:\Users\PC\Proyectos)
_ws_default = "/workspace" if os.name != "nt" else str(Path.home() / "Proyectos")
WORKSPACES_ROOT = Path(os.getenv("WORKSPACES_ROOT", _ws_default))


def list_repos() -> list[dict]:
    """Descubre repos git disponibles bajo WORKSPACES_ROOT."""
    repos = []
    if not WORKSPACES_ROOT.exists():
        # BUG-020: advertencia explícita en lugar de fallo silencioso
        import warnings
        warnings.warn(
            f"WORKSPACES_ROOT no existe: {WORKSPACES_ROOT}. "
            f"Configura la variable en .env (ej: WORKSPACES_ROOT=C:\\Users\\PC\\Proyectos)",
            stacklevel=2,
        )
        return repos
    for d in sorted(WORKSPACES_ROOT.iterdir()):
        if d.is_dir() and not d.name.startswith(".") and (d / ".git").exists():
            repos.append({"name": d.name, "path": str(d)})
    return repos


def resolve_repo_path(repo_name: str) -> str:
    """Devuelve la ruta absoluta del repo dentro del workspace."""
    return str(WORKSPACES_ROOT / repo_name)


# ── API Keys ──────────────────────────────────────────────────────────────────
ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
GOOGLE_API_KEY    = os.getenv("GOOGLE_API_KEY",    "")
ZHIPU_API_KEY     = os.getenv("ZHIPU_API_KEY",     "")
KIMI_API_KEY      = os.getenv("KIMI_API_KEY",      "")
OPENAI_API_KEY    = os.getenv("OPENAI_API_KEY",    "")

# ── Modelo por agente ─────────────────────────────────────────────────────────
MODEL_A0 = os.getenv("MODEL_A0", "gemini-3.5-flash")   # A0 Arquitecto de Proyecto
MODEL_A1 = os.getenv("MODEL_A1", "gemini-3.5-flash")   # A1 PM / Planificador
MODEL_A2 = os.getenv("MODEL_A2", "claude-sonnet-4-6") # A2 DB Architect
MODEL_A3 = os.getenv("MODEL_A3", "claude-sonnet-4-6") # A3 MCP Toolsmith
MODEL_A4 = os.getenv("MODEL_A4", "glm-5.1")           # A4 Backend Developer
MODEL_A5 = os.getenv("MODEL_A5", "kimi-k2.6")         # A5 Frontend Developer
MODEL_A6 = os.getenv("MODEL_A6", "claude-sonnet-4-6") # A6 Revisor / Refactor
MODEL_A7 = os.getenv("MODEL_A7", "gpt-5.5")           # A7 QA Test — OpenAI
MODEL_A8 = os.getenv("MODEL_A8", "gpt-5.5")           # A8 SecOps — OpenAI

MODEL_A9  = "no-llm"                                         # A9 Sandbox — sin LLM
MODEL_A10 = "no-llm"                                         # A10 Code Writer — sin LLM
MODEL_A11 = os.getenv("MODEL_A11", "claude-sonnet-4-6")     # A11 DevOps — Anthropic
MODEL_A0_REVISOR = MODEL_A0                                  # A0 Revisor usa el mismo modelo que A0

MODEL_PM       = MODEL_A1
MODEL_STANDARD = "claude-sonnet-4-6"
MODEL_FAST     = os.getenv("MODEL_FAST", "claude-haiku-4-5-20251001")

# ── Flags de comportamiento del pipeline ──────────────────────────────────────
# WRITE_TO_REPO: si False, A10 hace dry-run (loguea sin escribir)
WRITE_TO_REPO = os.getenv("WRITE_TO_REPO", "true").lower() == "true"

# ── Límites del pipeline ──────────────────────────────────────────────────────
MAX_QA_ITER_COMPLETO       = int(os.getenv("MAX_QA_ITER_COMPLETO",       "3"))
MAX_QA_ITER_LITE           = int(os.getenv("MAX_QA_ITER_LITE",           "2"))
MAX_SECOPS_ITER            = int(os.getenv("MAX_SECOPS_ITER",            "2"))
MAX_SANDBOX_ITER           = int(os.getenv("MAX_SANDBOX_ITER",           "2"))
CHECKPOINT_TIMEOUT_SECONDS = int(os.getenv("CHECKPOINT_TIMEOUT_SECONDS", "1800"))

# ── Auditoría arquitectónica (A0 Revisor) ─────────────────────────────────────
# Cada cuántos features completados corre el A0 Revisor (0 = desactivado)
ARCH_REVIEW_INTERVAL = int(os.getenv("ARCH_REVIEW_INTERVAL", "3"))

# ── VII-1: Pre-planificación chat ────────────────────────────────────────────
# Si True, el botón "Nuevo Feature" redirige al chat pre-planificación antes de A1.
PRECHAT_ENABLED = os.getenv("PRECHAT_ENABLED", "true").lower() == "true"

# ── VII-3: Railway Deploy ─────────────────────────────────────────────────────
RAILWAY_TOKEN      = os.getenv("RAILWAY_TOKEN",      "")
RAILWAY_PROJECT_ID = os.getenv("RAILWAY_PROJECT_ID", "")
RAILWAY_ENABLED    = bool(RAILWAY_TOKEN and RAILWAY_PROJECT_ID)

# ── P0-B: GitHub OAuth 2.0 ───────────────────────────────────────────────────
# Si están configurados, el flujo OAuth reemplaza el PAT manual.
# Crear OAuth App en github.com → Settings → Developer Settings → OAuth Apps
GITHUB_CLIENT_ID     = os.getenv("GITHUB_CLIENT_ID",     "")
GITHUB_CLIENT_SECRET = os.getenv("GITHUB_CLIENT_SECRET", "")
GITHUB_OAUTH_SECRET  = os.getenv("GITHUB_OAUTH_SECRET",  "fabrica-dev-secret-change-me")
GITHUB_OAUTH_CALLBACK = os.getenv(
    "GITHUB_OAUTH_CALLBACK_URL",
    "http://localhost:7860/auth/callback",
)
GITHUB_OAUTH_ENABLED = bool(GITHUB_CLIENT_ID and GITHUB_CLIENT_SECRET)

# ── IX-1: Multi-usuario RBAC ─────────────────────────────────────────────────
# Si True, todas las rutas web requieren login.
# El primer arranque con RBAC_ENABLED=true migra el usuario de BasicAuth como owner.
RBAC_ENABLED = os.getenv("RBAC_ENABLED", "false").lower() == "true"

# ── IX-2: PWA / Push Notifications ───────────────────────────────────────────
# Claves VAPID para Web Push (opcional — solo para notificaciones push reales).
VAPID_PUBLIC_KEY  = os.getenv("VAPID_PUBLIC_KEY",  "")
VAPID_PRIVATE_KEY = os.getenv("VAPID_PRIVATE_KEY", "")
VAPID_SUBJECT     = os.getenv("VAPID_SUBJECT",     "mailto:admin@fabrica.local")

# ── Bloque VI: Paralelismo de Features ───────────────────────────────────────
# PARALLEL_FEATURES_ENABLED: si True, el Project Loop ejecuta features
# independientes en paralelo (requiere pipeline estable, error rate < 10%).
PARALLEL_FEATURES_ENABLED = os.getenv("PARALLEL_FEATURES_ENABLED", "false").lower() == "true"
MAX_PARALLEL_FEATURES     = int(os.getenv("MAX_PARALLEL_FEATURES", "2"))

# ── Bloque III: Reducción de Intervención Humana ──────────────────────────────
# Ventana de veto: minutos que el Founder tiene para vetar un plan antes de que
# el pipeline continúe automáticamente (solo aplica en project_mode).
VETO_WINDOW_MINUTES = int(os.getenv("VETO_WINDOW_MINUTES", "30"))

# Auto-merge: si True y risk_level=LOW, el PR se fusiona automáticamente tras crearse.
# F1.5: además exige que el gate de cierre (sandbox + seguridad) esté verde; si no,
# el auto-merge se bloquea aunque risk_level sea LOW.
AUTO_MERGE_ENABLED = os.getenv("AUTO_MERGE_ENABLED", "false").lower() == "true"

# ── Fase 1 (PLAN_HARDENING_FABRICA): endurecimiento de gates ──────────────────
# STRICT_GATES: si True, una herramienta requerida-por-stack ausente cuenta como
# FALLO del gate (no skip silencioso). Espejo leído también por tools/code_sandbox.py.
STRICT_GATES = os.getenv("STRICT_GATES", "true").lower() == "true"
# TENANT_ISOLATION_GATE: "auto" (activo si el repo destino es Django y usa id_empresa),
# "true" (forzar), "false" (desactivar). Gate DURO de aislamiento multi-tenant (R-CODE-1).
TENANT_ISOLATION_GATE = os.getenv("TENANT_ISOLATION_GATE", "auto").lower()

# ── Agente de Noticias (independiente de la Fábrica) ─────────────────────────
NEWS_AGENT_ENABLED = os.getenv("NEWS_AGENT_ENABLED", "true").lower() == "true"
NEWS_AGENT_HOUR    = int(os.getenv("NEWS_AGENT_HOUR", "8"))
NEWS_AGENT_MODEL   = os.getenv("NEWS_AGENT_MODEL",   "claude-haiku-4-5-20251001")

# ── URLs OpenAI-compatibles por proveedor ─────────────────────────────────────
PROVIDER_URLS = {
    "openai": "https://api.openai.com/v1",
    "google": "https://generativelanguage.googleapis.com/v1beta/openai/",
    "zhipu":  "https://api.z.ai/api/paas/v4/",
    "kimi":   "https://api.moonshot.ai/v1",
}

# ── Proveedores IA personalizados (OpenAI-compatible) ─────────────────────────
# Cargados desde data/custom_providers.json en tiempo de arranque.
# Clave en PROVIDER_URLS: "cp_<API_KEY_VAR>"  (ej: "cp_OPENROUTER_API_KEY")
_CUSTOM_PROVIDERS_PATH = FABRICA_DIR / "data" / "custom_providers.json"

def _load_custom_providers() -> list[dict]:
    try:
        import json as _j
        if _CUSTOM_PROVIDERS_PATH.exists():
            return _j.loads(_CUSTOM_PROVIDERS_PATH.read_text(encoding="utf-8")) or []
    except Exception:
        pass
    return []

CUSTOM_PROVIDERS: list[dict] = _load_custom_providers()

for _cp in CUSTOM_PROVIDERS:
    _cp_key = "cp_" + (_cp.get("api_key_var") or "CUSTOM_API_KEY")
    if _cp.get("base_url"):
        PROVIDER_URLS[_cp_key] = _cp["base_url"]

# ── Precios ($/1M tokens) ─────────────────────────────────────────────────────
PRICES = {
    # Anthropic
    "claude-opus-4-7":           {"input": 15.00, "output": 75.00, "cache_read": 1.50},
    "claude-sonnet-4-6":         {"input":  3.00, "output": 15.00, "cache_read": 0.30},
    "claude-haiku-4-5-20251001": {"input":  0.80, "output":  4.00, "cache_read": 0.08},
    # Google
    "gemini-3.5-flash":          {"input":  0.30, "output":  2.50, "cache_read": 0.00},
    "gemini-3.1-pro-preview":    {"input":  2.50, "output": 15.00, "cache_read": 0.00},
    "gemini-2.5-pro":            {"input":  1.25, "output": 10.00, "cache_read": 0.00},
    # OpenAI
    "gpt-5.5":                   {"input":  5.00, "output": 30.00, "cache_read": 0.50},
    "gpt-5.5-2026-04-23":        {"input":  5.00, "output": 30.00, "cache_read": 0.50},
    "gpt-4o":                    {"input":  2.50, "output": 10.00, "cache_read": 0.00},
    "gpt-4o-mini":               {"input":  0.15, "output":  0.60, "cache_read": 0.00},
    "gpt-4-turbo":               {"input": 10.00, "output": 30.00, "cache_read": 0.00},
    # Z.ai (ZhiPu)
    "glm-5.1":                   {"input":  0.50, "output":  1.50, "cache_read": 0.00},
    "glm-4-plus":                {"input":  0.70, "output":  2.00, "cache_read": 0.00},
    # Kimi (Moonshot)
    "kimi-k2.6":                 {"input":  1.00, "output":  3.00, "cache_read": 0.00},
    "moonshot-v1-8k":            {"input":  0.12, "output":  0.12, "cache_read": 0.00},
    "moonshot-v1-32k":           {"input":  0.24, "output":  0.24, "cache_read": 0.00},
}

_DEFAULT_PRICE = {"input": 3.00, "output": 15.00, "cache_read": 0.00}


def get_price(model: str) -> dict:
    return PRICES.get(model, _DEFAULT_PRICE)


# ── Docs estáticos por repo (leídos en runtime desde el repo destino) ─────────
STATIC_DOC_PATHS = {
    "project_context":  "agents/PROJECT_CONTEXT.md",
    "coding_standards": "agents/CODING_STANDARDS.md",
    "decision_log":     "agents/DECISION_LOG.md",
}

SYSTEM_PROMPT_PATHS = {
    "a1_pm":       "agents/agent_01_pm/system_prompt.md",
    "a2_db":       "agents/agent_02_db/system_prompt.md",
    "a3_mcp":      "agents/agent_03_mcp_toolsmith/system_prompt.md",
    "a4_backend":  "agents/agent_04_backend/system_prompt.md",
    "a5_frontend": "agents/agent_05_frontend/system_prompt.md",
    "a6_refactor": "agents/agent_06_refactor/system_prompt.md",
    "a7_qa":       "agents/agent_07_qa/system_prompt.md",
    "a8_secops":   "agents/agent_08_secops/system_prompt.md",
}
