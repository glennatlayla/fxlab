#!/bin/bash
# ------------------------------------------------------------------------------
# FXLab API entrypoint — runs pre-flight checks, migrations, then starts uvicorn.
#
# Pre-flight checks:
#   1. Validates that all required secrets are set (fails fast on missing config).
#   2. Runs Alembic database migrations.
#   3. Starts the API with graceful shutdown support.
# ------------------------------------------------------------------------------

set -euo pipefail

echo "[entrypoint] Running pre-flight secret validation..."

# -- Required secrets ----------------------------------------------------------
if [ -z "${JWT_SECRET_KEY:-}" ]; then
  echo "FATAL: JWT_SECRET_KEY is not set. Generate with: python3 -c \"import secrets; print(secrets.token_urlsafe(48))\"" >&2
  exit 1
fi

if [ ${#JWT_SECRET_KEY} -lt 32 ]; then
  echo "FATAL: JWT_SECRET_KEY must be at least 32 bytes. Current length: ${#JWT_SECRET_KEY}" >&2
  exit 1
fi

if [ -z "${DATABASE_URL:-}" ]; then
  echo "FATAL: DATABASE_URL is not set. Example: postgresql://user:pass@host:5432/dbname" >&2
  exit 1
fi

# -- Optional secrets (required when Keycloak is enabled) ----------------------
if [ -n "${KEYCLOAK_URL:-}" ]; then
  if [ -z "${KEYCLOAK_ADMIN_CLIENT_SECRET:-}" ]; then
    echo "FATAL: KEYCLOAK_ADMIN_CLIENT_SECRET is required when KEYCLOAK_URL is set." >&2
    exit 1
  fi
  echo "[entrypoint] Keycloak integration enabled: ${KEYCLOAK_URL}"
fi

echo "[entrypoint] Secret validation passed."

# -- Database migrations -------------------------------------------------------
echo "[entrypoint] Running database migrations..."
if ! python -m alembic upgrade head; then
  echo "FATAL: Database migrations failed. Check connection string and migration history." >&2
  exit 1
fi
echo "[entrypoint] Migrations complete."

# -- Seed initial admin user (idempotent — skips if users already exist) ------
echo "[entrypoint] Checking for initial admin user..."
if ! python -m services.api.cli.seed_admin; then
  echo "WARNING: Admin seeding failed. You can retry manually:" >&2
  echo "  docker compose exec api python -m services.api.cli.seed_admin" >&2
  # Non-fatal — the API can still start; operator can seed manually.
fi

# -- Start API with graceful shutdown ------------------------------------------
echo "[entrypoint] Starting API server..."

# Trap SIGTERM for graceful shutdown — gives in-flight requests up to 30s to complete.
_term() {
  echo "[entrypoint] SIGTERM received, shutting down gracefully (30s timeout)..."
  kill -TERM "$PID" 2>/dev/null
  wait "$PID"
}
trap _term SIGTERM

# Start uvicorn in the background so we can wait on it
exec "$@" &
PID=$!
wait "$PID"
