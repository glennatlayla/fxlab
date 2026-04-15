#!/usr/bin/env bash
# scripts/test-pg.sh — Run the full test suite against PostgreSQL.
#
# This script starts the test infrastructure (PostgreSQL 15 + Redis 7),
# waits for readiness, runs the pytest suite with DATABASE_URL pointing
# at the real PostgreSQL instance, and tears down the containers.
#
# Usage:
#   ./scripts/test-pg.sh              # run full suite
#   ./scripts/test-pg.sh tests/unit/  # run specific directory
#
# Environment:
#   TEST_PG_PORT  — PostgreSQL host port (default: 5433)
#   TEST_REDIS_PORT — Redis host port (default: 6380)
#
# Exit codes:
#   0  — all tests passed
#   1  — tests failed
#   2  — infrastructure failed to start

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(dirname "$SCRIPT_DIR")"
COMPOSE_FILE="$PROJECT_ROOT/docker-compose.test.yml"

PG_PORT="${TEST_PG_PORT:-5433}"
REDIS_PORT="${TEST_REDIS_PORT:-6380}"

DATABASE_URL="postgresql://fxlab_test:fxlab_test@localhost:${PG_PORT}/fxlab_test"
REDIS_URL="redis://localhost:${REDIS_PORT}/0"

echo "=== FXLab PostgreSQL Integration Test Runner ==="
echo "  PostgreSQL port: $PG_PORT"
echo "  Redis port:      $REDIS_PORT"
echo ""

# --- Start infrastructure ---------------------------------------------------

echo "Starting test infrastructure..."
docker compose -f "$COMPOSE_FILE" up -d --wait 2>/dev/null || {
    echo "ERROR: Failed to start test infrastructure."
    echo "  Ensure Docker is running and ports $PG_PORT/$REDIS_PORT are available."
    exit 2
}

echo "Infrastructure ready."

# --- Run tests ---------------------------------------------------------------

echo ""
echo "Running tests against PostgreSQL..."
echo ""

EXIT_CODE=0
ENVIRONMENT=test \
DATABASE_URL="$DATABASE_URL" \
REDIS_URL="$REDIS_URL" \
    python -m pytest "${@:-tests/}" -q --tb=short || EXIT_CODE=$?

# --- Tear down ---------------------------------------------------------------

echo ""
echo "Tearing down test infrastructure..."
docker compose -f "$COMPOSE_FILE" down -v 2>/dev/null

if [ "$EXIT_CODE" -eq 0 ]; then
    echo ""
    echo "All tests passed against PostgreSQL."
else
    echo ""
    echo "Tests failed (exit code: $EXIT_CODE)."
fi

exit "$EXIT_CODE"
