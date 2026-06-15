FROM python:3.12-slim

# ── System deps + Node.js + gh CLI ───────────────────────────────────────────
RUN apt-get update && apt-get install -y --no-install-recommends \
      git curl ca-certificates gnupg tzdata \
    # Node.js 22 LTS (para instalar openclaw CLI via npm)
    && curl -fsSL https://deb.nodesource.com/setup_22.x | bash - \
    && apt-get install -y nodejs \
    # gh CLI
    && curl -fsSL https://cli.github.com/packages/githubcli-archive-keyring.gpg \
         | dd of=/usr/share/keyrings/githubcli-archive-keyring.gpg \
    && echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/githubcli-archive-keyring.gpg] \
         https://cli.github.com/packages stable main" \
         | tee /etc/apt/sources.list.d/github-cli.list \
    && apt-get update && apt-get install -y gh \
    && rm -rf /var/lib/apt/lists/*

# ── OpenClaw CLI (OPCIONAL) ───────────────────────────────────────────────────
# Solo se instala si se construye con --build-arg INSTALL_OPENCLAW=true.
# Por defecto NO se instala: la fábrica corre en modo directo (APIs de proveedores).
# Re-habilitar: build con INSTALL_OPENCLAW=true y poner USE_OPENCLAW=true en el .env.
ARG INSTALL_OPENCLAW=false
RUN if [ "$INSTALL_OPENCLAW" = "true" ]; then npm install -g openclaw@latest; fi

# ── Herramientas de calidad de código (Sandbox A9) ───────────────────────────
# TypeScript compiler — para tsc --noEmit en proyectos TS del cliente
RUN npm install -g typescript
# vitest / jest se instalan por proyecto; tsc ya está disponible globalmente

# ── Zona horaria Venezuela (UTC-4) ───────────────────────────────────────────
ENV TZ=America/Caracas
RUN ln -snf /usr/share/zoneinfo/$TZ /etc/localtime && echo $TZ > /etc/timezone

# ── Python deps ───────────────────────────────────────────────────────────────
WORKDIR /app

COPY requirements.txt .
# A3.2 (pinning): existe requirements.lock (pip-compile, deps transitivas fijadas).
# Aún NO se instala desde el lock: se generó con Python 3.11 y falta verificarlo en
# CI bajo python:3.12 (Bloque C: pip-audit). Una vez verificado, cambiar a:
#   RUN pip install --no-cache-dir -r requirements.lock
RUN pip install --no-cache-dir -r requirements.txt

# ── App code ──────────────────────────────────────────────────────────────────
COPY . .

# Directorio de datos por defecto (sobreescrito por RUNS_DIR env var en compose)
RUN mkdir -p /data/runs

EXPOSE 7860

# ── Entrypoint ────────────────────────────────────────────────────────────────
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

# ── A3.3: usuario no-root ─────────────────────────────────────────────────────
# Crear el usuario sin privilegios `fabrica` (uid 10001) y darle propiedad de las
# rutas que la app escribe en runtime:
#   /app        → entrypoint reescribe /app/.env (guardia de modelos) y clona repos
#   /data       → DB (/data/fabrica_state.db) y runs (/data/runs)
#   /workspace  → WORKSPACES_ROOT: repos destino clonados al arrancar (clone-on-startup)
#   /home/fabrica → git config --global escribe ~/.gitconfig
# NOTA: si en producción se monta un volumen sobre /data o /workspace (compose),
# el host debe darle propiedad/permiso de escritura al uid 10001.
RUN useradd --create-home --uid 10001 --shell /bin/sh fabrica \
    && mkdir -p /data/runs /workspace \
    && chown -R fabrica:fabrica /app /data /workspace

USER fabrica

ENTRYPOINT ["/entrypoint.sh"]
# sh -c para que ${PORT} (inyectado por Railway) se expanda; default 7860 local/compose.
CMD ["sh", "-c", "uvicorn ui.server:app --host 0.0.0.0 --port ${PORT:-7860}"]
