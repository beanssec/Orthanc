#!/usr/bin/env bash
# ── CI-ready test runner for Orthanc backend ────────────────────────────────
# Usage:  bash backend/run_tests.sh [pytest args...]
# Example: bash backend/run_tests.sh --collect-only
#          bash backend/run_tests.sh tests/test_auth.py -v
# ─────────────────────────────────────────────────────────────────────────────
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Set PYTHONPATH so `from app.*` imports resolve correctly
export PYTHONPATH="${SCRIPT_DIR}:${PYTHONPATH:-}"

# Export test-safe environment variables (won't clobber existing values)
export DATABASE_URL="${DATABASE_URL:-postgresql+asyncpg://invalid:invalid@localhost:5999/invalid_test}"
export JWT_SECRET="${JWT_SECRET:-test-secret-key-orthanc-2024}"
export JWT_ALGORITHM="${JWT_ALGORITHM:-HS256}"
export ENCRYPTION_KEY="${ENCRYPTION_KEY:-test-encryption-key-orthanc-24}"

echo "──────────────────────────────────────────────────────────────────"
echo "  Orthanc Backend Test Runner"
echo "  PYTHONPATH: ${PYTHONPATH}"
echo "  Test args:  $*"
echo "──────────────────────────────────────────────────────────────────"

cd "${SCRIPT_DIR}"

python -m pytest "$@"
EXIT_CODE=$?

echo "──────────────────────────────────────────────────────────────────"
if [ $EXIT_CODE -eq 0 ]; then
  echo "  ✅  All tests passed"
else
  echo "  ❌  Tests failed (exit code: ${EXIT_CODE})"
fi
echo "──────────────────────────────────────────────────────────────────"

exit $EXIT_CODE
