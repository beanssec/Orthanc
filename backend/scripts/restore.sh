#!/bin/bash
# Restore Orthanc database from a gzip backup
set -euo pipefail

BACKUP_FILE="$1"
if [ -z "$BACKUP_FILE" ]; then
    echo "Usage: restore.sh <backup_file>"
    exit 1
fi

if [ ! -f "$BACKUP_FILE" ]; then
    echo "Error: file not found: $BACKUP_FILE"
    exit 1
fi

PG_HOST="${PGHOST:-postgres}"
PG_USER="${PGUSER:-orthanc}"
PG_DB="${PGDATABASE:-orthanc}"

echo "Restoring from $BACKUP_FILE ..."
zcat "$BACKUP_FILE" | psql -h "$PG_HOST" -U "$PG_USER" "$PG_DB"
echo "Restore complete"
