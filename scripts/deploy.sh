#!/bin/bash
# deploy.sh — Instalación de Fábrica de Software en un VPS Ubuntu 22.04/24.04
#
# USO (como root o con sudo):
#   curl -fsSL https://raw.githubusercontent.com/tu-org/fabrica-software/main/scripts/deploy.sh | bash
#
#   O clonando manualmente:
#   git clone https://github.com/tu-org/fabrica-software /opt/fabrica-software
#   cd /opt/fabrica-software && sudo bash scripts/deploy.sh
#
# QUÉ HACE:
#   1. Instala Docker + Docker Compose + Caddy + Git
#   2. Crea la estructura de directorios en /opt/fabrica/
#   3. Copia docker-compose.prod.yml y .env.example
#   4. Configura el backup diario en crontab
#   5. Arranca los servicios
#   6. Muestra instrucciones finales (dominio, API keys)
#
set -euo pipefail

# ── Colores ───────────────────────────────────────────────────────────────────
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; BLUE='\033[0;34m'; NC='\033[0m'
info()    { echo -e "${BLUE}[INFO]${NC} $*"; }
success() { echo -e "${GREEN}[OK]${NC}   $*"; }
warn()    { echo -e "${YELLOW}[WARN]${NC} $*"; }
error()   { echo -e "${RED}[ERR]${NC}  $*"; exit 1; }

# ── Config ────────────────────────────────────────────────────────────────────
FABRICA_DIR="/opt/fabrica"
WORKSPACES_DIR="/opt/workspaces"
FABRICA_REPO="${FABRICA_REPO:-https://github.com/tu-org/fabrica-software}"
FABRICA_BRANCH="${FABRICA_BRANCH:-main}"

echo ""
echo "╔══════════════════════════════════════════════════╗"
echo "║   🏭  Fábrica de Software — Instalador VPS       ║"
echo "╚══════════════════════════════════════════════════╝"
echo ""

# ── Verificar root ────────────────────────────────────────────────────────────
if [[ $EUID -ne 0 ]]; then
    error "Ejecutar como root: sudo bash scripts/deploy.sh"
fi

# ── 1. Actualizar sistema ─────────────────────────────────────────────────────
info "Actualizando paquetes..."
apt-get update -qq && apt-get upgrade -y -qq
success "Sistema actualizado"

# ── 2. Instalar Docker ────────────────────────────────────────────────────────
if ! command -v docker &>/dev/null; then
    info "Instalando Docker..."
    curl -fsSL https://get.docker.com | sh
    systemctl enable docker
    systemctl start docker
    success "Docker instalado: $(docker --version)"
else
    success "Docker ya instalado: $(docker --version)"
fi

# ── 3. Instalar Caddy ─────────────────────────────────────────────────────────
if ! command -v caddy &>/dev/null; then
    info "Instalando Caddy..."
    apt-get install -y -qq debian-keyring debian-archive-keyring apt-transport-https
    curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/gpg.key' \
        | gpg --dearmor -o /usr/share/keyrings/caddy-stable-archive-keyring.gpg
    curl -1sLf 'https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt' \
        | tee /etc/apt/sources.list.d/caddy-stable.list
    apt-get update -qq && apt-get install -y -qq caddy
    success "Caddy instalado: $(caddy version)"
else
    success "Caddy ya instalado: $(caddy version)"
fi

# ── 4. Instalar herramientas ──────────────────────────────────────────────────
info "Instalando herramientas (git, make, awscli)..."
apt-get install -y -qq git make awscli curl jq
success "Herramientas instaladas"

# ── 5. Crear estructura de directorios ────────────────────────────────────────
info "Creando directorios..."
mkdir -p "${FABRICA_DIR}"/{data/runs,scripts,logs}
mkdir -p "${WORKSPACES_DIR}"
mkdir -p /var/log/caddy
chmod 755 "${WORKSPACES_DIR}"
success "Directorios creados en ${FABRICA_DIR}"

# ── 6. Clonar / actualizar el repo ────────────────────────────────────────────
REPO_DIR="${FABRICA_DIR}/src"
if [[ -d "${REPO_DIR}/.git" ]]; then
    info "Actualizando repo..."
    git -C "${REPO_DIR}" pull origin "${FABRICA_BRANCH}"
else
    info "Clonando repo..."
    git clone --branch "${FABRICA_BRANCH}" "${FABRICA_REPO}" "${REPO_DIR}"
fi
success "Código en ${REPO_DIR}"

# ── 7. Configurar .env ────────────────────────────────────────────────────────
ENV_FILE="${FABRICA_DIR}/.env"
if [[ ! -f "${ENV_FILE}" ]]; then
    info "Creando .env desde .env.example..."
    cp "${REPO_DIR}/.env.example" "${ENV_FILE}"
    warn "⚠️  EDITA ${ENV_FILE} con tus API keys antes de continuar"
    warn "   nano ${ENV_FILE}"
else
    success ".env ya existe — no se sobreescribe"
fi

# ── 8. Configurar docker-compose.prod.yml ────────────────────────────────────
COMPOSE_FILE="${FABRICA_DIR}/docker-compose.prod.yml"
cp "${REPO_DIR}/docker-compose.prod.yml" "${COMPOSE_FILE}"

# Escribir el .env de variables de paths para docker-compose
cat > "${FABRICA_DIR}/.env.compose" <<EOF
WORKSPACES_PATH=${WORKSPACES_DIR}
FABRICA_DATA_PATH=${FABRICA_DIR}/data
OPENCLAW_CONFIG=/root/.openclaw
FABRICA_ENV_PATH=${ENV_FILE}
EOF
success "docker-compose.prod.yml configurado"

# ── 9. Copiar scripts ─────────────────────────────────────────────────────────
cp "${REPO_DIR}/scripts/backup.sh" "${FABRICA_DIR}/scripts/backup.sh"
chmod +x "${FABRICA_DIR}/scripts/backup.sh"

# Configurar crontab para backup diario a las 3 AM
CRON_LINE="0 3 * * * FABRICA_DATA=${FABRICA_DIR}/data BACKUP_DEST=local ${FABRICA_DIR}/scripts/backup.sh >> /var/log/fabrica-backup.log 2>&1"
(crontab -l 2>/dev/null | grep -v "fabrica/scripts/backup"; echo "${CRON_LINE}") | crontab -
success "Backup diario configurado (3:00 AM)"

# ── 10. Copiar Caddyfile ──────────────────────────────────────────────────────
CADDY_FILE="/etc/caddy/Caddyfile"
if [[ ! -f "${CADDY_FILE}.orig" ]]; then
    cp "${CADDY_FILE}" "${CADDY_FILE}.orig" 2>/dev/null || true
fi
cp "${REPO_DIR}/Caddyfile" "${CADDY_FILE}"
warn "⚠️  Edita /etc/caddy/Caddyfile y reemplaza 'fabrica.tudominio.com' con tu dominio"

# ── 11. Arrancar servicios ────────────────────────────────────────────────────
info "Levantando contenedores..."
cd "${FABRICA_DIR}"
docker compose -f docker-compose.prod.yml --env-file .env.compose pull 2>/dev/null || true
docker compose -f docker-compose.prod.yml --env-file .env.compose up -d --build

# Esperar a que la UI esté lista
info "Esperando que la UI esté lista..."
for i in {1..30}; do
    if curl -sf http://localhost:7860/health &>/dev/null; then
        success "UI respondiendo en localhost:7860"
        break
    fi
    sleep 2
done

# ── 12. Mostrar instrucciones finales ─────────────────────────────────────────
SERVER_IP=$(curl -sf https://ipv4.icanhazip.com || echo "TU_IP")

echo ""
echo "╔══════════════════════════════════════════════════════════════╗"
echo "║  ✅  Instalación completada                                  ║"
echo "╚══════════════════════════════════════════════════════════════╝"
echo ""
echo -e "${GREEN}Pasos finales que requieren TU acción:${NC}"
echo ""
echo "  1. Editar el .env con tus API keys:"
echo "     ${YELLOW}nano ${ENV_FILE}${NC}"
echo ""
echo "  2. Editar el Caddyfile con tu dominio:"
echo "     ${YELLOW}nano /etc/caddy/Caddyfile${NC}"
echo "     Reemplaza 'fabrica.tudominio.com' con tu dominio real"
echo "     Asegúrate de que el DNS apunta a: ${SERVER_IP}"
echo ""
echo "  3. Arrancar Caddy (HTTPS):"
echo "     ${YELLOW}systemctl enable caddy && systemctl start caddy${NC}"
echo ""
echo "  4. Clonar tus repos de cliente en ${WORKSPACES_DIR}:"
echo "     ${YELLOW}git clone https://github.com/tu-org/omni-erp ${WORKSPACES_DIR}/omni-erp${NC}"
echo ""
echo "  5. Reiniciar la fábrica para que detecte los repos:"
echo "     ${YELLOW}docker compose -f ${COMPOSE_FILE} restart fabrica${NC}"
echo ""
echo -e "  Tu UI estará disponible en: ${GREEN}https://fabrica.tudominio.com${NC}"
echo ""
echo "Comandos útiles:"
echo "  Ver logs:     docker compose -f ${COMPOSE_FILE} logs -f fabrica"
echo "  Reiniciar:    docker compose -f ${COMPOSE_FILE} restart"
echo "  Backup ahora: bash ${FABRICA_DIR}/scripts/backup.sh"
echo ""
