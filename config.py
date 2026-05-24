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

# ── Modelo por agente ─────────────────────────────────────────────────────────
MODEL_A0 = os.getenv("MODEL_A0", "gemini-3.5-flash")   # A0 Arquitecto de Proyecto
MODEL_A1 = os.getenv("MODEL_A1", "gemini-3.5-flash")   # A1 PM / Planificador
MODEL_A2 = os.getenv("MODEL_A2", "claude-sonnet-4-6") # A2 DB Architect
MODEL_A3 = os.getenv("MODEL_A3", "claude-sonnet-4-6") # A3 MCP Toolsmith
MODEL_A4 = os.getenv("MODEL_A4", "glm-5.1")           # A4 Backend Developer
MODEL_A5 = os.getenv("MODEL_A5", "kimi-k2.6")         # A5 Frontend Developer
MODEL_A6 = os.getenv("MODEL_A6", "claude-sonnet-4-6") # A6 Revisor / Refactor
MODEL_A7 = os.getenv("MODEL_A7", "claude-sonnet-4-6") # A7 QA Test
MODEL_A8 = os.getenv("MODEL_A8", "claude-sonnet-4-6") # A8 SecOps

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

# ── Agente de Noticias (independiente de la Fábrica) ─────────────────────────
NEWS_AGENT_ENABLED = os.getenv("NEWS_AGENT_ENABLED", "true").lower() == "true"
NEWS_AGENT_HOUR    = int(os.getenv("NEWS_AGENT_HOUR", "8"))
NEWS_AGENT_MODEL   = os.getenv("NEWS_AGENT_MODEL",   "claude-haiku-4-5-20251001")

# ── URLs OpenAI-compatibles por proveedor ─────────────────────────────────────
PROVIDER_URLS = {
    "google": "https://generativelanguage.googleapis.com/v1beta/openai/",
    "zhipu":  "https://api.z.ai/api/paas/v4/",
    "kimi":   "https://api.moonshot.ai/v1",
}

# ── Precios ($/1M tokens) — claude-sonnet-4-6 aplica a agentes 2,3,6,7,8 ─────
PRICES = {
    "claude-opus-4-7":           {"input": 15.00, "output": 75.00, "cache_read": 1.50},
    "claude-sonnet-4-6":         {"input":  3.00, "output": 15.00, "cache_read": 0.30},
    "claude-haiku-4-5-20251001": {"input":  0.80, "output":  4.00, "cache_read": 0.08},
    "gemini-3.5-flash":          {"input":  0.30, "output":  2.50, "cache_read": 0.00},
    "gemini-3.1-pro-preview":    {"input":  2.50, "output": 15.00, "cache_read": 0.00},
    "gemini-2.5-pro":            {"input":  1.25, "output": 10.00, "cache_read": 0.00},
    "glm-5.1":                   {"input":  0.50, "output":  1.50, "cache_read": 0.00},
    "kimi-k2.6":                 {"input":  1.00, "output":  3.00, "cache_read": 0.00},
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
