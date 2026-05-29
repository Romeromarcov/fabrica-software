#!/bin/sh
set -e

# ── Git identity (necesaria para commits dentro del contenedor) ────────────────
git config --global user.name  "${GIT_USER_NAME:-Omni ERP Bot}"
git config --global user.email "${GIT_USER_EMAIL:-bot@omni-erp.local}"

# M-13: marcar todos los directorios como safe (repos de clientes en /workspace)
# Usar --replace-all para que sea idempotente en cada reinicio del contenedor
git config --global --replace-all safe.directory '*'

# ── Inicializar DB si no existe ───────────────────────────────────────────────
DB="${DB_PATH:-/data/fabrica_state.db}"
if [ ! -f "$DB" ]; then
  touch "$DB"
fi

# ── Crear directorio de runs si no existe ─────────────────────────────────────
RUNS="${RUNS_DIR:-/data/runs}"
mkdir -p "$RUNS"

# ── Guardia de modelos: detecta y corrige asignaciones invertidas ─────────────
# Ejecutar antes de arrancar el servidor para que NUNCA queden modelos mal
# asignados, aunque el .env se haya corrompido desde la UI.
python3 - <<'PYEOF'
import re, sys

ENV_PATH = "/app/.env"

# Asignaciones CORRECTAS por agente (proveedor esperado)
CORRECT = {
    "MODEL_A0": "gemini-3.5-flash",   # A0 Arquitecto  → Google
    "MODEL_A1": "gemini-3.5-flash",   # A1 PM          → Google
    "MODEL_A2": "claude-sonnet-4-6",  # A2 DB Architect → Anthropic
    "MODEL_A3": "claude-sonnet-4-6",  # A3 MCP Toolsmith → Anthropic
    "MODEL_A4": "glm-5.1",            # A4 Backend     → ZhiPu
    "MODEL_A5": "kimi-k2.6",          # A5 Frontend    → Kimi
    "MODEL_A6": "claude-sonnet-4-6",  # A6 Revisor     → Anthropic
    "MODEL_A7": "gpt-5.5",            # A7 QA          → OpenAI
    "MODEL_A8": "gpt-5.5",            # A8 SecOps      → OpenAI
}

# Prefijos de proveedor que NO deben aparecer en cada agente
# A7/A8 admiten tanto claude-* (Anthropic) como gpt-* (OpenAI) — sin restricción de prefijo
FORBIDDEN_PREFIX = {
    "MODEL_A2": ("glm-", "kimi-", "gpt-"),
    "MODEL_A3": ("glm-", "kimi-", "gpt-"),
    "MODEL_A4": ("claude-",),
    "MODEL_A5": ("claude-",),
    "MODEL_A6": ("glm-", "kimi-"),
    "MODEL_A7": ("glm-", "kimi-"),
    "MODEL_A8": ("glm-", "kimi-"),
}

try:
    with open(ENV_PATH, "r", encoding="utf-8") as f:
        content = f.read()
except FileNotFoundError:
    sys.exit(0)

changed = False
for key, correct_val in CORRECT.items():
    forbidden = FORBIDDEN_PREFIX.get(key, ())
    # Buscar el valor actual
    m = re.search(rf"^{key}=(.*)$", content, re.MULTILINE)
    if not m:
        # No existe → añadir
        content += f"\n{key}={correct_val}"
        changed = True
        print(f"[entrypoint] {key} faltaba → añadido {correct_val}")
        continue
    current_val = m.group(1).strip()
    if any(current_val.startswith(prefix) for prefix in forbidden):
        # Valor incorrecto → corregir
        content = re.sub(
            rf"^{key}=.*$", f"{key}={correct_val}", content, flags=re.MULTILINE
        )
        changed = True
        print(f"[entrypoint] {key} era '{current_val}' (incorrecto) → corregido a '{correct_val}'")

if changed:
    with open(ENV_PATH, "w", encoding="utf-8") as f:
        f.write(content)
    print("[entrypoint] .env corregido y guardado.")
else:
    print("[entrypoint] Modelos OK — sin cambios.")
PYEOF

exec "$@"
