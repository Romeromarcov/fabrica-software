"""Lee y escribe la configuración en el archivo .env del orquestador."""
from pathlib import Path

ENV_PATH = Path(__file__).parent.parent / ".env"

DEFAULTS = {
    # API Keys
    "ANTHROPIC_API_KEY": "",
    "GOOGLE_API_KEY":    "",
    "ZHIPU_API_KEY":     "",
    "KIMI_API_KEY":      "",
    "LANGCHAIN_API_KEY": "",
    "LANGCHAIN_TRACING_V2": "false",
    # Modelos por agente
    "MODEL_A1": "gemini-3.1-pro-preview",
    "MODEL_A2": "glm-5.1",
    "MODEL_A3": "kimi-k2.6",
    "MODEL_A4": "claude-sonnet-4-6",
    "MODEL_A5": "claude-sonnet-4-6",
    "MODEL_A6": "claude-sonnet-4-6",
    "MODEL_A7": "claude-sonnet-4-6",
    "MODEL_A8": "claude-sonnet-4-6",
    # Límites
    "MAX_QA_ITER_COMPLETO":       "3",
    "MAX_QA_ITER_LITE":           "2",
    "CHECKPOINT_TIMEOUT_SECONDS": "1800",
}

SENSITIVE = {
    "ANTHROPIC_API_KEY": ("sk-ant-", "sk-ant-****"),
    "GOOGLE_API_KEY":    ("AIza",    "AIza****"),
    "ZHIPU_API_KEY":     ("",        "****"),
    "KIMI_API_KEY":      ("sk-",     "sk-****"),
    "LANGCHAIN_API_KEY": ("ls__",    "ls__****"),
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

    def save(self, new_cfg: dict) -> None:
        current = self.load(masked=False)
        # Solo sobreescribir keys sensibles si el valor no es una máscara
        for key in SENSITIVE:
            new_val = new_cfg.get(key, "")
            if new_val and ("****" in new_val):
                new_cfg.pop(key, None)  # ignorar — el usuario no tocó este campo
        current.update({k: str(v) for k, v in new_cfg.items()})

        lines = ["# Fábrica de Software — Omni ERP — configuración generada por la UI", ""]
        for k, v in current.items():
            lines.append(f"{k}={v}")

        ENV_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")
