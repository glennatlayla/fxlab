# FXLab — Development Setup

Local development environment setup for contributors.

## Prerequisites

- Python 3.12+
- pip
- Git with SSH access to github.com

## Setup

One command does the full bootstrap on a fresh clone:

```bash
git clone git@github.com:glennatlayla/fxlab.git
cd fxlab

# Verify on Debian/Ubuntu that python3-venv is available (one-time, system-level):
#   sudo apt install python3.12-venv

make bootstrap          # creates .venv, installs Python deps + pre-commit hooks,
                        # bootstraps node LTS via nodeenv, runs frontend npm install
make verify             # confirm everything is wired correctly (format + lint + tests + compose)

cp .env.example .env    # copy environment config (one-time)
```

`make bootstrap` is idempotent — re-running on an already-bootstrapped clone is safe and skips work that is already done. It is the canonical setup path; the manual `python3 -m venv .venv` / `pip install` recipe still works but is no longer the recommended starting point. Node.js is installed into the venv by nodeenv (no system Node install required).

## Running a Strategy Backtest (CLI, synthetic data)

Until Oanda fxpractice creds are wired, every strategy in
`Strategy Repo/` can be backtested against deterministic synthetic
FX bars:

```bash
.venv/bin/python -m services.cli.run_synthetic_backtest \
    --ir "Strategy Repo/fxlab_kathy_lien_public_strategy_pack/FX_DoubleBollinger_TrendZone.strategy_ir.json" \
    --start 2026-01-01 --end 2026-04-01 --seed 42 \
    --output /tmp/blotter.json
```

- `--seed`: deterministic. Same IR + same window + same seed = byte-identical blotter.
- `--output`: JSON file with one entry per trade (entry/exit times,
  prices, side, units, realized PnL).
- Stdout: summary (total trades, win rate, total return, Sharpe).

Synthetic provider (`libs/strategy_ir/synthetic_market_data_provider.py`)
emits seeded GBM bars for the 7 FX majors across timeframes
{15m, 1h, 4h, 1d}. The CLI uses `PaperBrokerAdapter`
(`libs/strategy_ir/paper_broker_adapter.py`) for fully simulated
fills. When Oanda creds land, the constructor args swap to
`OandaMarketDataProvider` + `OandaBrokerAdapter` — no other code
changes.

## Database Backup / Restore (Postgres)

The `services/cli/db_backup.py` CLI wraps `pg_dump` / `psql` so an
operator can capture and restore the FXLab Postgres database without
remembering connection-string mechanics. Three modes are supported,
each with a corresponding Makefile target.

```bash
# 1. Capture a backup. Default OUTPUT is /tmp/fxlab-backup-<UTC ts>.sql.
DATABASE_URL=postgresql://fxlab:secret@localhost:5432/fxlab \
    make db-backup
# or with a specific path:
DATABASE_URL=postgresql://fxlab:secret@localhost:5432/fxlab \
    make db-backup OUTPUT=/var/backups/fxlab-2026-04-25.sql

# 2. Verify a backup BEFORE restoring (no DB I/O — parses the dump
#    locally and reports per-table row counts).
make db-verify INPUT=/var/backups/fxlab-2026-04-25.sql

# 3. Restore. The CLI refuses to overwrite a non-empty database
#    unless FORCE=1 is set — guardrail against accidentally clobbering
#    a populated DB. Drop+recreate the schema explicitly if you
#    actually intend to overwrite.
DATABASE_URL=postgresql://fxlab:secret@localhost:5432/fxlab \
    make db-restore INPUT=/var/backups/fxlab-2026-04-25.sql
# Force overwrite (rare; intended for restore-into-existing-DB scenarios):
DATABASE_URL=postgresql://fxlab:secret@localhost:5432/fxlab \
    make db-restore INPUT=/var/backups/fxlab-2026-04-25.sql FORCE=1
```

Notes:

- `pg_dump` and `psql` must be on `PATH` (Debian/Ubuntu:
  `sudo apt install postgresql-client`). The CLI exits 1 with a clear
  message if either binary is missing.
- The password from `DATABASE_URL` is passed to subprocesses via
  `PGPASSWORD` — never via argv (so it never appears in `ps` output)
  and never logged. Every log line and error message that names the
  target uses the redacted form `postgresql://user:***@host:5432/db`.
- Default subprocess timeouts are 600s (backup) and 1200s (restore);
  override with `--timeout SECONDS` on the underlying CLI if needed.
- Use `db-verify` as the dry-run check before any production restore.

Direct CLI invocation (when not using Make):

```bash
DATABASE_URL=postgresql://fxlab:secret@localhost:5432/fxlab \
    .venv/bin/python -m services.cli.db_backup \
    --mode backup --output /tmp/fxlab-backup.sql
```

## Running Tests

```bash
# Full test suite with coverage (same as ship.sh runs)
pytest tests/unit/ -q --tb=short

# Specific test file
pytest tests/unit/test_api_bootstrap.py -v

# Generate HTML coverage report
pytest --cov-report=html
open htmlcov/index.html
```

## Code Quality

```bash
# Format
ruff format services/ libs/ tests/

# Lint
ruff check services/ libs/ tests/

# Type check
mypy services/ libs/ --ignore-missing-imports --no-strict-optional
```

## Ship (Quality-Gated Push)

The `ship.sh` script runs all quality gates, commits, and pushes in one command:

```bash
# Dry run — gates only, no commit
./ship.sh --dry-run

# Ship with auto-generated commit message
./ship.sh

# Ship with custom message
./ship.sh "feat(api): add kill switch endpoint"

# Skip tests (format + lint only)
./ship.sh --skip-tests
```

Gates run in order: format, lint, mypy, pytest. All must pass before the commit is created.

## Local Docker Stack (Development)

```bash
# Start all services (Postgres, Redis, Keycloak, Jaeger, API, Web)
docker compose up -d

# API available at http://localhost:8000
# Frontend at http://localhost:3000
# Keycloak at http://localhost:8080
# Jaeger at http://localhost:16686

# Stop
docker compose down
```

## Project Layout

```
services/api/       FastAPI backend
libs/contracts/     Pydantic models and interfaces
libs/broker/        Brokerage adapters
libs/indicators/    Technical indicators
frontend/           React/Vite dashboard
tests/unit/         Unit tests (4300+)
tests/integration/  Integration tests
```

See [CLAUDE.md](CLAUDE.md) for the full coding standards, onion architecture rules, and TDD workflow.
