#!/bin/bash
# Safe Alembic migration wrapper for Orthanc.
#
# Usage:
#   ./migrate_safe.sh [target_revision]   (default: head)
#
# Features:
#   - Logs current and target revision before running
#   - Detects downgrades: skips in AUTOMATED mode, requires confirmation otherwise
#   - Verifies no pending migrations after upgrade
#   - Exit codes: 0=success, 1=failure/aborted
#
# Environment:
#   AUTOMATED=1        Skip interactive prompts; abort on downgrade instead of prompting
#   ALEMBIC_CMD        Path to alembic binary (default: alembic)

set -uo pipefail

ALEMBIC="${ALEMBIC_CMD:-alembic}"
TARGET="${1:-head}"
AUTOMATED="${AUTOMATED:-0}"

log() { echo "[$(date '+%Y-%m-%d %H:%M:%S')] MIGRATE: $*"; }
fail() { log "ERROR: $*"; exit 1; }

# ── Ensure alembic is available ────────────────────────────────────────────────
command -v "${ALEMBIC}" &>/dev/null || fail "alembic not found (ALEMBIC_CMD=${ALEMBIC})"

# ── Get current revision ───────────────────────────────────────────────────────
log "Checking current migration revision..."
CURRENT_OUTPUT=$("${ALEMBIC}" current 2>&1) || fail "alembic current failed: ${CURRENT_OUTPUT}"
CURRENT_REV=$(echo "${CURRENT_OUTPUT}" | grep -oP '[a-f0-9_]+(?= \(head\))' | head -1 || true)
if [[ -z "${CURRENT_REV}" ]]; then
    CURRENT_REV=$(echo "${CURRENT_OUTPUT}" | grep -oP '^[a-f0-9_]+' | head -1 || true)
fi
log "Current revision: ${CURRENT_REV:-<none / uninitialized>}"
log "Target revision:  ${TARGET}"

# ── Downgrade detection ────────────────────────────────────────────────────────
# A "downgrade" is any explicit non-head target that looks like going backwards
# (relative targets like -1, -2 are clear downgrades; named revisions are harder
#  to compare without full graph traversal, so we warn on any non-'head' target).
IS_DOWNGRADE=0
if [[ "${TARGET}" != "head" ]]; then
    if [[ "${TARGET}" =~ ^-[0-9]+ ]]; then
        IS_DOWNGRADE=1
        log "WARNING: Relative downgrade target detected: ${TARGET}"
    elif [[ -n "${CURRENT_REV}" && "${TARGET}" != "${CURRENT_REV}" ]]; then
        log "WARNING: Non-head target '${TARGET}' — verify this is not a rollback"
        IS_DOWNGRADE=1
    fi
fi

if [[ "${IS_DOWNGRADE}" -eq 1 ]]; then
    if [[ "${AUTOMATED}" == "1" ]]; then
        fail "Downgrade detected (target='${TARGET}'). Aborting in AUTOMATED mode. Set AUTOMATED=0 to override interactively."
    else
        read -r -p "Downgrade to '${TARGET}' detected. Are you sure? [y/N] " confirm
        if [[ "${confirm}" != "y" && "${confirm}" != "Y" ]]; then
            log "Aborted by user"
            exit 1
        fi
    fi
fi

# ── Run migration ──────────────────────────────────────────────────────────────
log "Running: ${ALEMBIC} upgrade ${TARGET}"
"${ALEMBIC}" upgrade "${TARGET}" || fail "alembic upgrade failed"
log "Migration applied successfully"

# ── Verify no pending migrations (only meaningful when targeting head) ─────────
if [[ "${TARGET}" == "head" ]]; then
    log "Verifying no pending migrations remain..."
    CHECK_OUTPUT=$("${ALEMBIC}" check 2>&1) && {
        log "Check passed: database is up to date"
    } || {
        log "WARNING: alembic check reported pending migrations: ${CHECK_OUTPUT}"
        # Non-fatal warning — alembic check exits 1 if there are pending migrations
    }
fi

log "Migration complete"
exit 0
