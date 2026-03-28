#!/bin/bash
set -e
echo "[entrypoint] Running database migrations..."
python -m alembic upgrade head
echo "[entrypoint] Migrations complete. Starting API server..."
exec "$@"
