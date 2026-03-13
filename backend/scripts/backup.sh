#!/bin/bash
# Backup Orthanc (Overwatch) database
set -euo pipefail

BACKUP_DIR="${BACKUP_DIR:-/app/data/backups}"
TIMESTAMP=$(date +%Y%m%d_%H%M%S)
BACKUP_FILE="${BACKUP_DIR}/overwatch_${TIMESTAMP}.sql.gz"

mkdir -p "$BACKUP_DIR"
pg_dump -h postgres -U overwatch overwatch | gzip > "$BACKUP_FILE"
echo "Backup saved to $BACKUP_FILE"

# Retain only the 7 most recent backups
ls -t "${BACKUP_DIR}"/overwatch_*.sql.gz | tail -n +8 | xargs -r rm
echo "Old backups cleaned"
