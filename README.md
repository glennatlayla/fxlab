# FXLab

Algorithmic trading platform for backtesting, paper trading, and live execution of equity, futures, and options strategies. Includes strategy authoring, governance workflows, risk management, and a web-based operator dashboard.

## Quick Start

There are two install paths depending on whether you're standing up a developer environment or a production server.

### Developer machine (single command)

```bash
git clone git@github.com:glennatlayla/fxlab.git && cd fxlab && ./scripts/bootstrap.sh
```

`scripts/bootstrap.sh` is idempotent. It detects your OS package manager (apt / dnf / yum / pacman / brew), installs system prerequisites (`python3`, `python${X}-venv` matched to your Python version, build tools, curl, git) via `sudo`, then runs the rest of the dev install: `.venv` + Python deps + nodeenv + frontend `npm install` + pre-commit hooks + `docker compose up -d --wait postgres redis` + `.env` generation with fresh secrets + `alembic upgrade head` + the credential validator + a backend `/health` smoke and frontend `npm run build`. On exit it prints what to do next.

```bash
make install-dev-onboard   # equivalent to ./scripts/bootstrap.sh
make validate-env          # re-run the credential probes only
make verify                # full quality gate
./scripts/bootstrap.sh --reset-env   # archive existing .env, regenerate
```

Useful flags: `--no-docker`, `--no-sudo`, `--install-docker`, `--reset-env`, `--skip-tests`, `--skip-frontend-build`, `--skip-backend-smoke`, `--validate-only`. See `./scripts/bootstrap.sh -h`.

### Production server (single command)

```bash
git clone git@github.com:glennatlayla/fxlab.git /opt/fxlab && sudo bash /opt/fxlab/install.sh
```

This uses your SSH key to clone (private repo), then runs the installer as root. The installer builds all Docker containers, generates secrets, runs database migrations, installs a systemd service for boot persistence, and runs health checks. When it finishes, the platform is live.

> **Note:** If `/opt/fxlab` requires root to create, use: `sudo mkdir -p /opt/fxlab && sudo chown $USER /opt/fxlab && git clone git@github.com:glennatlayla/fxlab.git /opt/fxlab && sudo bash /opt/fxlab/install.sh`

**Update an existing installation:**

```bash
cd /opt/fxlab && git pull && sudo ./install.sh
```

Pulls latest code with your SSH key, then rebuilds containers and restarts services.

## What Gets Deployed

The install script starts a Docker Compose stack with these services:

| Service    | Image / Build        | Port  | Purpose                                    |
|------------|----------------------|-------|--------------------------------------------|
| **nginx**  | nginx:1.25-alpine    | 80/443| TLS termination, reverse proxy             |
| **api**    | services/api/Dockerfile | 8000 | FastAPI backend (strategies, governance, risk) |
| **web**    | frontend/Dockerfile  | 3000  | React operator dashboard                   |
| **postgres** | postgres:15-alpine | 5432  | Strategy metadata, audit ledger, governance |
| **redis**  | redis:7-alpine       | 6379  | Rate limiting, job queue, cache            |
| **keycloak** | keycloak:24.0      | 8080  | Identity provider (RS256 token issuance)   |
| **jaeger** | jaegertracing/all-in-one:1.54 | 16686 | Distributed tracing (OpenTelemetry) |

## Requirements (Production Host)

- Linux (Ubuntu 20.04+, Debian 11+, RHEL 8+)
- Docker Engine 24+ with Compose v2
- Git 2.25+
- 4 GB RAM minimum (8 GB recommended)
- 10 GB free disk space
- Root or sudo access
- SSH key for GitHub access (private repo)

## Configuration

On first install, the script creates `/opt/fxlab/.env` from `.env.production.template`. Edit it to set:

```bash
# Required secrets (no defaults — must be set)
POSTGRES_PASSWORD=<strong-random-password>
JWT_SECRET_KEY=<32+-byte-random-secret>
KEYCLOAK_ADMIN_PASSWORD=<keycloak-admin-password>

# Recommended production settings
ENVIRONMENT=production
LOG_LEVEL=WARNING
ALLOWED_EXECUTION_MODES=shadow,paper    # Add "live" only when ready
CORS_ALLOWED_ORIGINS=https://your-domain.com
```

Generate secrets:

```bash
python3 -c "import secrets; print(secrets.token_urlsafe(48))"
```

See `.env.example` for the full list of configuration options including database pool tuning, rate limiting, Azure Key Vault integration, and OpenTelemetry settings.

## Managing the Platform

```bash
# View running containers and health status
docker compose -f /opt/fxlab/docker-compose.prod.yml ps

# View logs (all services, or a specific one)
docker compose -f /opt/fxlab/docker-compose.prod.yml logs -f
docker compose -f /opt/fxlab/docker-compose.prod.yml logs -f api

# Restart a single service
docker compose -f /opt/fxlab/docker-compose.prod.yml restart api

# Stop everything
docker compose -f /opt/fxlab/docker-compose.prod.yml down

# Start everything
docker compose -f /opt/fxlab/docker-compose.prod.yml up -d

# Check API health
curl http://localhost:8000/health
```

## Endpoints

Once running, access:

- **Operator Dashboard:** http://your-host (port 80, proxied through nginx)
- **API Docs:** http://your-host:8000/docs (interactive Swagger UI)
- **Keycloak Admin:** http://your-host:8080 (user management)
- **Jaeger UI:** http://your-host:16686 (distributed tracing)

## Architecture

```
services/
  api/            FastAPI backend — routes, middleware, repositories
    routes/         HTTP endpoints (governance, audit, strategies, risk)
    services/       Business logic (backtesting, execution, risk gates)
    repositories/   Data access (PostgreSQL via SQLAlchemy)
    middleware/     Rate limiting, body size, correlation ID
    infrastructure/ Config, tracing, secrets, circuit breaker
  worker/         Background workers (market data, strategy execution)
  scheduler/      Scheduled jobs (data collection, rebalancing)

libs/
  contracts/      Pydantic models, schemas, interfaces
  broker/         Brokerage adapters (Alpaca, paper trading)
  indicators/     Technical indicators (MACD, RSI, Stochastic, etc.)

frontend/         React/Vite operator dashboard
```

## Development Setup

See [DEVELOPMENT.md](DEVELOPMENT.md) for setting up a local development environment, running tests, and using the quality-gated `ship.sh` workflow.

## License

Proprietary — Internal Use Only
