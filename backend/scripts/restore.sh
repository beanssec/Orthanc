#!/bin/bash
# Restore Orthanc (Overwatch) database from a gzip backup
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

echo "Restoring from $BACKUP_FILE ..."
zcat "$BACKUP_FILE" | psql -h postgres -U overwatch overwatch
echo "Restore complete"
