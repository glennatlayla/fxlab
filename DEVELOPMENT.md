# FXLab — Development Setup

Local development environment setup for contributors.

## Prerequisites

- Python 3.12+
- pip
- Git with SSH access to github.com

## Setup

```bash
git clone git@github.com:glennatlayla/fxlab.git
cd fxlab

# Create virtual environment and install dependencies
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt

# Copy environment config
cp .env.example .env
```

Node.js is installed automatically into the venv by `ship.sh` via nodeenv. No system Node install required.

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
