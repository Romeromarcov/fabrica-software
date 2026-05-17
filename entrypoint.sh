#!/bin/sh
set -e

# ── Git identity (necesaria para commits dentro del contenedor) ────────────────
git config --global user.name  "${GIT_USER_NAME:-Omni ERP Bot}"
git config --global user.email "${GIT_USER_EMAIL:-bot@omni-erp.local}"

# Marca el repo montado como safe para git
git config --global --add safe.directory /repo
git config --global --add safe.directory /app

# ── Inicializar DB si no existe ───────────────────────────────────────────────
DB="${DB_PATH:-/data/fabrica_state.db}"
if [ ! -f "$DB" ]; then
  touch "$DB"
fi

# ── Crear directorio de runs si no existe ─────────────────────────────────────
RUNS="${RUNS_DIR:-/data/runs}"
mkdir -p "$RUNS"

exec "$@"
