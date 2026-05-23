#!/bin/bash
# backup.sh — Backup diario de /data (runs + LangGraph DB)
#
# CONFIGURACIÓN (variables de entorno o editar aquí):
#   BACKUP_DEST   — Destino del backup. Opciones:
#                   "local"              → /opt/backups/fabrica/
#                   "s3://mi-bucket"     → AWS S3 (requiere aws-cli)
#                   "r2://mi-bucket"     → Cloudflare R2 (requiere aws-cli con endpoint)
#   FABRICA_DATA  — Ruta a /data. Default: /opt/fabrica/data
#   BACKUP_KEEP   — Días de retención local. Default: 7
#   R2_ENDPOINT   — Solo para R2: https://<account>.r2.cloudflarestorage.com
#
# INSTALACIÓN (ejecutar una vez):
#   chmod +x /opt/fabrica/scripts/backup.sh
#   crontab -e
#   # Añadir: 0 3 * * * /opt/fabrica/scripts/backup.sh >> /var/log/fabrica-backup.log 2>&1
#
set -euo pipefail

FABRICA_DATA="${FABRICA_DATA:-/opt/fabrica/data}"
BACKUP_DEST="${BACKUP_DEST:-local}"
BACKUP_LOCAL_DIR="${BACKUP_LOCAL_DIR:-/opt/backups/fabrica}"
BACKUP_KEEP="${BACKUP_KEEP:-7}"
TIMESTAMP=$(date +"%Y%m%d_%H%M%S")
BACKUP_NAME="fabrica_backup_${TIMESTAMP}.tar.gz"
TMP_FILE="/tmp/${BACKUP_NAME}"

echo "=== Fábrica Backup — $(date) ==="
echo "Fuente: ${FABRICA_DATA}"
echo "Destino: ${BACKUP_DEST}"

# ── 1. Crear el tarball ───────────────────────────────────────────────────────
echo "Creando ${BACKUP_NAME}..."
tar -czf "${TMP_FILE}" \
    --exclude="*/node_modules" \
    --exclude="*/__pycache__" \
    -C "$(dirname "${FABRICA_DATA}")" \
    "$(basename "${FABRICA_DATA}")"

SIZE=$(du -sh "${TMP_FILE}" | cut -f1)
echo "Backup creado: ${SIZE}"

# ── 2. Subir al destino ───────────────────────────────────────────────────────

if [[ "${BACKUP_DEST}" == "local" ]]; then
    mkdir -p "${BACKUP_LOCAL_DIR}"
    mv "${TMP_FILE}" "${BACKUP_LOCAL_DIR}/${BACKUP_NAME}"
    echo "Guardado en: ${BACKUP_LOCAL_DIR}/${BACKUP_NAME}"

    # Limpiar backups viejos
    find "${BACKUP_LOCAL_DIR}" -name "fabrica_backup_*.tar.gz" \
        -mtime "+${BACKUP_KEEP}" -delete
    echo "Backups retenidos: $(ls "${BACKUP_LOCAL_DIR}" | wc -l)"

elif [[ "${BACKUP_DEST}" == s3://* ]]; then
    aws s3 cp "${TMP_FILE}" "${BACKUP_DEST}/${BACKUP_NAME}"
    rm -f "${TMP_FILE}"
    echo "Subido a S3: ${BACKUP_DEST}/${BACKUP_NAME}"

    # Limpiar backups viejos en S3 (retener BACKUP_KEEP)
    aws s3 ls "${BACKUP_DEST}/" | grep "fabrica_backup_" | sort | \
        head -n -"${BACKUP_KEEP}" | awk '{print $4}' | \
        xargs -I{} aws s3 rm "${BACKUP_DEST}/{}" 2>/dev/null || true

elif [[ "${BACKUP_DEST}" == r2://* ]]; then
    BUCKET="${BACKUP_DEST#r2://}"
    aws s3 cp "${TMP_FILE}" "s3://${BUCKET}/${BACKUP_NAME}" \
        --endpoint-url "${R2_ENDPOINT}"
    rm -f "${TMP_FILE}"
    echo "Subido a R2: ${BUCKET}/${BACKUP_NAME}"

else
    echo "ERROR: BACKUP_DEST desconocido: ${BACKUP_DEST}"
    rm -f "${TMP_FILE}"
    exit 1
fi

echo "=== Backup completado ==="
