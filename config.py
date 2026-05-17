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
WORKSPACES_ROOT = Path(os.getenv("WORKSPACES_ROOT", "/workspace"))


def list_repos() -> list[dict]:
    """Descubre repos git disponibles bajo WORKSPACES_ROOT."""
    repos = []
    if not WORKSPACES_ROOT.exists():
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
MODEL_A1 = os.getenv("MODEL_A1", "gemini-2.5-pro")
MODEL_A2 = os.getenv("MODEL_A2", "claude-sonnet-4-6")
MODEL_A3 = os.getenv("MODEL_A3", "claude-sonnet-4-6")
MODEL_A4 = os.getenv("MODEL_A4", "claude-sonnet-4-6")
MODEL_A5 = os.getenv("MODEL_A5", "claude-sonnet-4-6")
MODEL_A6 = os.getenv("MODEL_A6", "claude-sonnet-4-6")
MODEL_A7 = os.getenv("MODEL_A7", "claude-sonnet-4-6")
MODEL_A8 = os.getenv("MODEL_A8", "claude-sonnet-4-6")

MODEL_PM       = MODEL_A1
MODEL_STANDARD = "claude-sonnet-4-6"
MODEL_FAST     = os.getenv("MODEL_FAST", "claude-haiku-4-5-20251001")

# ── Límites del pipeline ──────────────────────────────────────────────────────
MAX_QA_ITER_COMPLETO       = int(os.getenv("MAX_QA_ITER_COMPLETO",       "3"))
MAX_QA_ITER_LITE           = int(os.getenv("MAX_QA_ITER_LITE",           "2"))
CHECKPOINT_TIMEOUT_SECONDS = int(os.getenv("CHECKPOINT_TIMEOUT_SECONDS", "1800"))

# ── URLs OpenAI-compatibles por proveedor ─────────────────────────────────────
PROVIDER_URLS = {
    "google": "https://generativelanguage.googleapis.com/v1beta/openai/",
    "zhipu":  "https://api.z.ai/api/paas/v4/",
    "kimi":   "https://api.moonshot.ai/v1",
}

# ── Precios ($/1M tokens) ─────────────────────────────────────────────────────
PRICES = {
    "claude-opus-4-7":           {"input": 15.00, "output": 75.00, "cache_read": 1.50},
    "claude-sonnet-4-6":         {"input":  3.00, "output": 15.00, "cache_read": 0.30},
    "claude-haiku-4-5-20251001": {"input":  0.80, "output":  4.00, "cache_read": 0.08},
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
    "a2_backend":  "agents/agent_02_backend/system_prompt.md",
    "a3_frontend": "agents/agent_03_frontend/system_prompt.md",
    "a4_qa":       "agents/agent_04_qa/system_prompt.md",
    "a5_refactor": "agents/agent_05_refactor/system_prompt.md",
    "a6_db":       "agents/agent_06_db/system_prompt.md",
    "a7_secops":   "agents/agent_07_secops/system_prompt.md",
    "a8_mcp":      "agents/agent_08_mcp_toolsmith/system_prompt.md",
}
