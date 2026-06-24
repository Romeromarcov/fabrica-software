"""Lee y escribe la configuración del orquestador.

En la nube (Railway) las variables vienen del entorno inyectado y el archivo de
config se persiste en el volumen (/data/.env). Precedencia en load():
  DEFAULTS  <  os.environ (Railway)  <  archivo .env (ediciones guardadas por la UI)
Así, recién desplegado toma las keys de Railway; si el usuario edita en la UI, eso
persiste en el volumen y gana.
"""
import os
from pathlib import Path

# /data/.env si existe el volumen (Railway); si no, el .env del repo (local).
_REPO_ENV = Path(__file__).parent.parent / ".env"
_VOL = Path("/data")
ENV_PATH = Path(os.environ.get("CONFIG_ENV_PATH") or (
    str(_VOL / ".env") if _VOL.is_dir() else str(_REPO_ENV)
))

DEFAULT_TOPICS = (
    "Inteligencia Artificial,"
    "Blockchain y Web3,"
    "Mercado Crypto,"
    "Marketing Digital,"
    "Negocios Globales,"
    "Petróleo e Hidrocarburos,"
    "Geopolítica,"
    "Finanzas Venezuela"
)

DEFAULTS = {
    # API Keys — Fábrica de Software
    "ANTHROPIC_API_KEY": "",
    "GOOGLE_API_KEY":    "",
    "ZHIPU_API_KEY":     "",
    "KIMI_API_KEY":      "",
    "OPENAI_API_KEY":    "",
    "NVIDIA_API_KEY":    "",
    "LANGCHAIN_API_KEY": "",
    "LANGCHAIN_TRACING_V2": "false",
    # Telegram — compartido por Fábrica y Agente de Noticias
    "TELEGRAM_BOT_TOKEN": "",
    "TELEGRAM_CHAT_ID":   "",
    # Modelos por agente (orden del workflow)
    "MODEL_A0": "gemini-3.5-flash",          # A0 Arquitecto — Google (thinking)
    "MODEL_A1": "gemini-3.5-flash",          # A1 PM — Google (thinking)
    "MODEL_A2": "claude-sonnet-4-6",        # A2 DB Architect — Anthropic
    "MODEL_A3": "claude-sonnet-4-6",        # A3 MCP Toolsmith — Anthropic
    "MODEL_A4": "glm-5.1",                  # A4 Backend — Z.ai
    "MODEL_A5": "kimi-k2.6",               # A5 Frontend — Kimi
    "MODEL_A6": "claude-sonnet-4-6",        # A6 Revisor/Refactor — Anthropic
    "MODEL_A7": "gpt-5.5",                   # A7 QA Test — OpenAI
    "MODEL_A8": "gpt-5.5",                   # A8 SecOps — OpenAI
    # A9 y A10 no usan LLM
    "MODEL_A11": "claude-sonnet-4-6",       # A11 DevOps — Anthropic
    # Comportamiento del pipeline
    "WRITE_TO_REPO": "true",               # false = dry-run sin escribir archivos
    # Autonomía de la fábrica (alto riesgo) — default seguro false; se activan desde la UI.
    # El default vive aquí y en config.py; la UI persiste el opt-in en /data/.env.
    "AUTO_MERGE_ENABLED":        "false",  # fusiona PRs LOW con gate verde (RUNBOOK §7.4)
    "PARALLEL_FEATURES_ENABLED": "false",  # features concurrentes (CTF-FABRICA-001)
    "FACTORY_MODIFIER_ENABLED":  "false",  # auto-modificación de la fábrica (doble gate)
    # Límites del pipeline
    "MAX_QA_ITER_COMPLETO":       "3",
    "MAX_QA_ITER_LITE":           "2",
    "MAX_SECOPS_ITER":            "2",
    "MAX_SANDBOX_ITER":           "2",
    "CHECKPOINT_TIMEOUT_SECONDS": "1800",
    # Auditoría Arquitectónica (A0 Revisor)
    "ARCH_REVIEW_INTERVAL":       "3",    # 0 = desactivado; default: cada 3 features
    # Agente de Noticias — configuración completa
    "NEWS_AGENT_ENABLED":  "true",
    "NEWS_AGENT_HOUR":     "8",
    "NEWS_AGENT_PROVIDER": "anthropic",          # anthropic | google | openai | custom
    "NEWS_AGENT_MODEL":    "claude-haiku-4-5-20251001",
    "NEWS_AGENT_API_KEY":  "",                   # vacío = usa la key del proveedor
    "NEWS_AGENT_API_URL":  "",                   # solo para proveedor "custom"
    "NEWS_AGENT_TOPICS":   DEFAULT_TOPICS,
    "NEWS_AGENT_TG_TOKEN": "",                   # vacío = usa TELEGRAM_BOT_TOKEN
    "NEWS_AGENT_TG_CHAT":  "",                   # vacío = usa TELEGRAM_CHAT_ID
    # Seguridad & Acceso — producción
    "UI_USERNAME":   "",          # Basic Auth usuario (vacío = sin auth)
    "UI_PASSWORD":   "",          # Basic Auth contraseña
    "GITHUB_TOKEN":  "",          # PAT para git push + gh pr create
    "GITHUB_ACTOR":  "",          # Usuario/org GitHub (para autenticar push)
    "RAILWAY_TOKEN":      "",     # Account token Railway (Deploy / listar proyectos)
    "RAILWAY_PROJECT_ID": "",     # Project ID por defecto (opcional)
    # Auditor Periódico de Codebase
    "AUDITOR_ENABLED":    "true",
    "AUDITOR_WEEKDAY":    "0",                   # 0=lunes … 6=domingo
    "AUDITOR_HOUR":       "7",
    "AUDITOR_MAX_FILES":  "30",
    "AUDITOR_MODEL":      "claude-sonnet-4-6",
    "AUDITOR_REPO":       "all",                 # "all" o nombre exacto del repo
}

# Conjunto de claves conocidas (para separar "extra keys" definidas por el usuario)
KNOWN_KEYS = set(DEFAULTS.keys())

# Prefijos de proveedor que NO son válidos para cada agente.
# Evita que un swap accidental en el formulario se persista en .env.
# A7 y A8 admiten Anthropic (claude-) Y OpenAI (gpt-) — sin restricción.
MODEL_FORBIDDEN_PREFIX: dict[str, tuple[str, ...]] = {
    "MODEL_A2": ("glm-", "kimi-", "gpt-"),
    "MODEL_A3": ("glm-", "kimi-", "gpt-"),
    "MODEL_A4": ("claude-",),
    "MODEL_A5": ("claude-",),
    "MODEL_A6":  ("glm-", "kimi-"),
    "MODEL_A7":  ("glm-", "kimi-"),        # permite claude-* y gpt-*
    "MODEL_A8":  ("glm-", "kimi-"),        # permite claude-* y gpt-*
    "MODEL_A11": ("glm-", "kimi-", "gpt-"),
}

SENSITIVE = {
    "ANTHROPIC_API_KEY":  ("sk-ant-", "sk-ant-****"),
    "GOOGLE_API_KEY":     ("AIza",    "AIza****"),
    "ZHIPU_API_KEY":      ("",        "****"),
    "KIMI_API_KEY":       ("sk-",     "sk-****"),
    "OPENAI_API_KEY":     ("sk-",     "sk-****"),
    "LANGCHAIN_API_KEY":  ("ls__",    "ls__****"),
    "TELEGRAM_BOT_TOKEN": ("",        "****"),
    "NEWS_AGENT_API_KEY": ("",        "****"),
    "NEWS_AGENT_TG_TOKEN":("",        "****"),
    "UI_PASSWORD":        ("",        "****"),
    "GITHUB_TOKEN":       ("",        "****"),
    "NVIDIA_API_KEY":     ("nvapi-",  "nvapi-****"),
    "RAILWAY_TOKEN":      ("",        "****"),
}


def _mask(key: str, value: str) -> str:
    if key not in SENSITIVE or not value:
        return value
    prefix, masked_prefix = SENSITIVE[key]
    if prefix and value.startswith(prefix):
        return f"{masked_prefix}{value[-4:]}"
    return f"****{value[-4:]}" if len(value) > 4 else "****"


class ConfigStore:
    def load(self, masked: bool = True) -> dict:
        cfg = dict(DEFAULTS)
        # Overlay 1: variables de entorno (Railway) para las keys conocidas.
        for k in DEFAULTS:
            env_v = os.environ.get(k)
            if env_v not in (None, ""):
                cfg[k] = env_v
        # Overlay 2: archivo .env (ediciones guardadas por la UI) — gana sobre el entorno.
        if ENV_PATH.exists():
            for line in ENV_PATH.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line or line.startswith("#") or "=" not in line:
                    continue
                k, _, v = line.partition("=")
                cfg[k.strip()] = v.strip()
        if masked:
            return {k: _mask(k, v) for k, v in cfg.items()}
        return cfg

    def load_extra_keys(self) -> dict:
        """Devuelve las claves del .env que NO están en DEFAULTS (definidas por el usuario)."""
        extra = {}
        if not ENV_PATH.exists():
            return extra
        for line in ENV_PATH.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, _, v = line.partition("=")
            k = k.strip()
            if k not in KNOWN_KEYS:
                extra[k] = v.strip()
        return extra

    def save(self, new_cfg: dict) -> None:
        current = self.load(masked=False)
        # Cargar también las extra keys para no borrarlas al guardar
        extra = self.load_extra_keys()
        current.update(extra)

        # Solo sobreescribir keys sensibles si el valor no es una máscara
        for key in SENSITIVE:
            new_val = new_cfg.get(key, "")
            if new_val and ("****" in new_val):
                new_cfg.pop(key, None)  # ignorar — el usuario no tocó este campo

        # Guardia de modelos: rechazar valores con proveedor incorrecto.
        # Esto previene que un swap accidental en el formulario se persista.
        for model_key, forbidden in MODEL_FORBIDDEN_PREFIX.items():
            new_val = new_cfg.get(model_key, "")
            if new_val and any(new_val.startswith(prefix) for prefix in forbidden):
                # Revertir al valor por defecto en lugar de persistir el error
                new_cfg[model_key] = DEFAULTS[model_key]

        current.update({k: str(v) for k, v in new_cfg.items()})

        lines = ["# Fábrica de Software — Omni ERP — configuración generada por la UI", ""]
        for k, v in current.items():
            lines.append(f"{k}={v}")

        ENV_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")
