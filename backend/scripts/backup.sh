#!/bin/bash
# Backup Orthanc database
# Features:
#   - gzip compression
#   - timestamped filename
#   - rotation: keep last N backups (default 7)
#   - backup size logging
#   - exit codes: 0=success, 1=failure

set -uo pipefail

# ── Configuration ──────────────────────────────────────────────────────────────
BACKUP_DIR="${BACKUP_DIR:-/app/data/backups}"
KEEP_LAST="${KEEP_LAST:-7}"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
BACKUP_FILE="${BACKUP_DIR}/orthanc_${TIMESTAMP}.sql.gz"
PG_HOST="${PGHOST:-postgres}"
PG_USER="${PGUSER:-orthanc}"
PG_DB="${PGDATABASE:-orthanc}"

# ── Helpers ────────────────────────────────────────────────────────────────────
log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] $*"; }
fail() { log "ERROR: $*"; exit 1; }

# ── Pre-flight ─────────────────────────────────────────────────────────────────
log "Starting backup → ${BACKUP_FILE}"
mkdir -p "${BACKUP_DIR}" || fail "Cannot create backup directory: ${BACKUP_DIR}"

# ── Dump ───────────────────────────────────────────────────────────────────────
pg_dump -h "${PG_HOST}" -U "${PG_USER}" "${PG_DB}" \
    | gzip > "${BACKUP_FILE}" \
    || fail "pg_dump failed (host=${PG_HOST} user=${PG_USER} db=${PG_DB})"

# ── Size logging ───────────────────────────────────────────────────────────────
if command -v du &>/dev/null; then
    BACKUP_SIZE=$(du -sh "${BACKUP_FILE}" 2>/dev/null | cut -f1)
else
    BACKUP_SIZE=$(ls -lh "${BACKUP_FILE}" 2>/dev/null | awk '{print $5}')
fi
log "Backup complete: ${BACKUP_FILE} (${BACKUP_SIZE:-unknown size})"

# ── Rotation: keep last N backups ─────────────────────────────────────────────
TOTAL_BACKUPS=$(ls -1 "${BACKUP_DIR}"/orthanc_*.sql.gz 2>/dev/null | wc -l)
log "Total backups before rotation: ${TOTAL_BACKUPS} (keeping last ${KEEP_LAST})"

DELETED=0
while IFS= read -r old_file; do
    rm -f "${old_file}" && log "Deleted old backup: ${old_file}" && (( DELETED++ )) || true
done < <(ls -t "${BACKUP_DIR}"/orthanc_*.sql.gz 2>/dev/null | tail -n "+$((KEEP_LAST + 1))")

if [[ ${DELETED} -gt 0 ]]; then
    log "Rotation complete: deleted ${DELETED} old backup(s)"
else
    log "Rotation: no backups to delete"
fi

log "Backup finished successfully"
exit 0
