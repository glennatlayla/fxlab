# FXLab — Production Deployment Guide

**Last updated:** 2026-04-12
**Applies to:** FXLab API v0.1.0 (Phase 3 complete — all milestones DONE)

---

## 1. Architecture Overview

FXLab runs as a containerised stack behind a TLS-terminating reverse proxy.

```
Internet
   │
   ▼
┌──────────────────────┐
│  Reverse Proxy       │  ◄── TLS termination (nginx / Caddy / ALB)
│  (HTTPS :443)        │
└──────────┬───────────┘
           │ HTTP :8000
           ▼
┌──────────────────────┐     ┌──────────────┐     ┌──────────────┐
│  FXLab API           │────▶│  PostgreSQL   │     │  Redis       │
│  (FastAPI + Uvicorn) │     │  :5432        │     │  :6379       │
└──────────────────────┘     └──────────────┘     └──────────────┘
```

The FastAPI application binds to HTTP only (port 8000). It must **never** be
exposed directly to the internet without a reverse proxy that terminates TLS.

---

## 2. HTTPS / TLS Configuration

FastAPI does not handle TLS directly. Place a reverse proxy in front of the
API container. Any of the following work:

### 2.1 nginx (recommended for self-hosted)

```nginx
upstream fxlab_api {
    server 127.0.0.1:8000;
    keepalive 32;
}

server {
    listen 443 ssl http2;
    server_name api.fxlab.example.com;

    ssl_certificate     /etc/ssl/certs/fxlab.crt;
    ssl_certificate_key /etc/ssl/private/fxlab.key;
    ssl_protocols       TLSv1.2 TLSv1.3;
    ssl_ciphers         HIGH:!aNULL:!MD5;

    # Forward real client IP for rate limiting
    proxy_set_header X-Forwarded-For   $proxy_add_x_forwarded_for;
    proxy_set_header X-Forwarded-Proto $scheme;
    proxy_set_header Host              $host;

    # Correlation ID passthrough
    proxy_set_header X-Correlation-ID  $http_x_correlation_id;

    # Body size — match MAX_REQUEST_BODY_BYTES (512 KB default)
    client_max_body_size 512k;

    location / {
        proxy_pass http://fxlab_api;
        proxy_http_version 1.1;
        proxy_set_header Connection "";
    }

    # Health check (no auth required)
    location = /health {
        proxy_pass http://fxlab_api/health;
        access_log off;
    }
}

# Redirect HTTP → HTTPS
server {
    listen 80;
    server_name api.fxlab.example.com;
    return 301 https://$host$request_uri;
}
```

### 2.2 AWS Application Load Balancer

Configure the ALB target group to point at the API container on port 8000
over HTTP. Attach an ACM certificate to the ALB listener on port 443. Enable
stickiness only if WebSocket support is added later; for REST-only traffic
round-robin is preferred.

### 2.3 Caddy (automatic HTTPS)

```caddyfile
api.fxlab.example.com {
    reverse_proxy localhost:8000
}
```

Caddy obtains and renews Let's Encrypt certificates automatically.

---

## 3. Secrets Management

### 3.1 Required secrets

| Variable | Purpose | Generation |
|----------|---------|------------|
| `JWT_SECRET_KEY` | Signs HS256 access tokens | `python3 -c "import secrets; print(secrets.token_urlsafe(48))"` |
| `POSTGRES_PASSWORD` | PostgreSQL superuser password | Random 32+ character string |
| `DATABASE_URL` | Full connection string with SSL | See §3.3 |

### 3.2 Rules

Never commit secrets to version control. The `.env` file is gitignored. In
production, inject secrets via one of the following methods (ordered by
preference):

1. **Container orchestrator secrets** (Docker Swarm secrets, Kubernetes
   Secrets, ECS task definition secrets).
2. **Cloud secrets manager** (AWS Secrets Manager, GCP Secret Manager, Azure
   Key Vault) — the application reads environment variables; the
   orchestrator retrieves and injects them at container start.
3. **docker-compose secrets** (for single-host deployments):

```yaml
services:
  api:
    environment:
      - JWT_SECRET_KEY_FILE=/run/secrets/jwt_secret
      - DATABASE_URL_FILE=/run/secrets/database_url
    secrets:
      - jwt_secret
      - database_url

secrets:
  jwt_secret:
    external: true
  database_url:
    external: true
```

> Note: The application currently reads `JWT_SECRET_KEY` directly from the
> environment. If using `_FILE`-based injection, add a bootstrap script that
> reads the file into the environment variable before starting uvicorn. The
> entrypoint script (`services/api/entrypoint.sh`) is the right place for this.

### 3.3 AWS Secrets Manager integration path

```bash
# Store the secret
aws secretsmanager create-secret \
    --name fxlab/production/jwt-secret \
    --secret-string "$(python3 -c 'import secrets; print(secrets.token_urlsafe(48))')"

# In ECS task definition, reference via valueFrom:
# {
#   "name": "JWT_SECRET_KEY",
#   "valueFrom": "arn:aws:secretsmanager:us-east-1:123456789:secret:fxlab/production/jwt-secret"
# }
```

For rotation: update the secret in Secrets Manager and perform a rolling
restart of the API containers. Active tokens signed with the old key will
fail validation and clients will re-authenticate.

---

## 4. Database Configuration

### 4.1 Connection string

Production PostgreSQL connections require SSL:

```
DATABASE_URL=postgresql://fxlab:<PASSWORD>@db.example.com:5432/fxlab?sslmode=require
```

The `sslmode=require` parameter ensures the connection is encrypted in transit.
For stricter validation, use `sslmode=verify-full` with a CA certificate.

### 4.2 Connection pool tuning

The API uses SQLAlchemy's `QueuePool` for PostgreSQL connections. Pool
parameters are configurable via environment variables:

| Variable | Default | Description |
|----------|---------|-------------|
| `DB_POOL_SIZE` | 5 | Number of persistent connections maintained in the pool |
| `DB_POOL_OVERFLOW` | 10 | Maximum temporary connections beyond `pool_size` |
| `DB_POOL_TIMEOUT` | 30 | Seconds to wait for a connection before raising `TimeoutError` |

**Sizing guidance:**

The total maximum connections is `DB_POOL_SIZE + DB_POOL_OVERFLOW` per
worker process. With the default 2 Uvicorn workers, that means up to
`(5 + 10) × 2 = 30` connections. Ensure your PostgreSQL `max_connections`
is at least this value plus headroom for migrations and monitoring tools.

Recommended starting points:

| Deployment | Workers | Pool Size | Overflow | Max Connections |
|------------|---------|-----------|----------|-----------------|
| Dev/staging | 1 | 5 | 10 | 15 |
| Small production | 2 | 5 | 10 | 30 |
| Medium production | 4 | 10 | 20 | 120 |
| High traffic | 8 | 15 | 30 | 360 |

For high-traffic deployments behind a connection pooler (PgBouncer), set
`DB_POOL_SIZE=2` and `DB_POOL_OVERFLOW=3` per worker, and let PgBouncer
manage the actual PostgreSQL connections.

**Validation:** Non-positive or non-numeric values are rejected at startup
with a CRITICAL-level log entry, and the default is used instead. The engine
also enables `pool_pre_ping=True` to evict stale connections before use.

### 4.3 Migrations

Alembic migrations run automatically on container start via the entrypoint
script (`services/api/entrypoint.sh`). The script calls:

```bash
python -m alembic upgrade head
```

Migrations must be idempotent — the entrypoint runs on every container start,
including rolling restarts. Alembic's version tracking table prevents re-running
already-applied migrations.

For manual migration management:

```bash
# Generate a new migration
alembic revision --autogenerate -m "add_new_table"

# Apply all pending migrations
alembic upgrade head

# Roll back one migration
alembic downgrade -1

# Show current migration state
alembic current
```

---

## 5. Environment Variables Reference

### 5.1 Required in production

| Variable | Example | Notes |
|----------|---------|-------|
| `ENVIRONMENT` | `production` | Dockerfile sets this via ARG; never override to `test` |
| `DATABASE_URL` | `postgresql://...?sslmode=require` | SSL required |
| `JWT_SECRET_KEY` | `<64-char random>` | Generate with `secrets.token_urlsafe(48)` |
| `CORS_ALLOWED_ORIGINS` | `https://app.fxlab.example.com` | Comma-separated; no wildcards |
| `POSTGRES_PASSWORD` | `<random>` | Used by docker-compose postgres service |

### 5.2 Optional (with defaults)

| Variable | Default | Notes |
|----------|---------|-------|
| `LOG_LEVEL` | `INFO` | `DEBUG`, `INFO`, `WARNING`, `ERROR` |
| `DB_POOL_SIZE` | `5` | PostgreSQL pool size per worker |
| `DB_POOL_OVERFLOW` | `10` | Max overflow connections per worker |
| `DB_POOL_TIMEOUT` | `30` | Connection wait timeout (seconds) |
| `SQL_ECHO` | `false` | Set `true` to log all SQL (debug only) |
| `JWT_ALGORITHM` | `HS256` | Token signing algorithm |
| `JWT_EXPIRATION_MINUTES` | `60` | Access token lifetime |
| `JWT_MAX_TOKEN_BYTES` | `16384` | Reject oversized tokens |
| `MAX_REQUEST_BODY_BYTES` | `524288` | 512 KB body size limit |
| `RATE_LIMIT_GOVERNANCE` | `20` | Governance endpoint rate (req/min/IP) |
| `RATE_LIMIT_DEFAULT` | `100` | Default endpoint rate (req/min/IP) |
| `REDIS_URL` | `redis://redis:6379/0` | Redis connection string |

---

## 6. Container Build and Run

### 6.1 Build

```bash
# Production build
docker build -t fxlab-api:latest -f services/api/Dockerfile .

# Development build (enables --reload)
docker build -t fxlab-api:dev \
    --build-arg ENVIRONMENT=development \
    -f services/api/Dockerfile .
```

### 6.2 Run with docker-compose

```bash
# Copy and configure environment
cp .env.example .env
# Edit .env — set JWT_SECRET_KEY, POSTGRES_PASSWORD, CORS_ALLOWED_ORIGINS

# Start all services
docker-compose up -d

# Verify health
curl -f http://localhost:8000/health
```

### 6.3 Production container checklist

The Dockerfile follows security best practices:

- Multi-stage build (build dependencies excluded from runtime image)
- Non-root user (`fxlab`) with `--system` flag
- Health check via `curl -f http://localhost:8000/health`
- `ENVIRONMENT=production` set at image build time via ARG
- Entrypoint runs migrations before starting the application
- Production mode: 2 Uvicorn workers, no `--reload`

---

## 7. Health Checks

The `GET /health` endpoint is public (no authentication required) and returns:

```json
// Healthy
{"status": "ok", "database": "connected"}  // HTTP 200

// Unhealthy
{"status": "degraded", "database": "unreachable"}  // HTTP 503
```

**Configure your load balancer / orchestrator health check to target
`GET /health` on port 8000.** The docker-compose file and Dockerfile both
include health check definitions with these parameters:

- Interval: 10 seconds
- Timeout: 5 seconds
- Retries: 5
- Start period: 10 seconds (allows time for migrations)

Wait for the health check to pass before routing traffic to a new container
during rolling deployments.

---

## 8. Middleware Stack

The API applies middleware in this order (outermost first):

| Order | Middleware | Purpose | Config |
|-------|-----------|---------|--------|
| 1 | `CorrelationIDMiddleware` | Assigns/propagates `X-Correlation-ID` | None |
| 2 | `RateLimitMiddleware` | Sliding-window per-IP rate limiting | `RATE_LIMIT_*` env vars |
| 3 | `BodySizeLimitMiddleware` | Rejects oversized request bodies | `MAX_REQUEST_BODY_BYTES` |
| 4 | `CORSMiddleware` | Cross-origin resource sharing | `CORS_ALLOWED_ORIGINS` |

Rate limiting uses an in-memory sliding window per IP address. This is
suitable for single-instance deployments. For horizontally scaled deployments,
replace with a Redis-backed rate limiter (tracked as a future enhancement;
the `REDIS_URL` variable is already available).

---

## 9. Pre-Flight Checklist

Run through this checklist before every production deployment:

```
[ ] ENVIRONMENT=production is set in the container (Dockerfile default)
[ ] JWT_SECRET_KEY is a 32+ byte random secret (not a default/placeholder)
[ ] DATABASE_URL uses sslmode=require (or sslmode=verify-full)
[ ] CORS_ALLOWED_ORIGINS is set to the actual frontend domain (no wildcards)
[ ] POSTGRES_PASSWORD is a strong random value (not "fxlab" or "change-me")
[ ] Health check endpoint responds 200 before routing traffic
[ ] Alembic migrations have been tested against a staging database
[ ] Rate limiting is active (verify: 21 rapid requests → 429 on governance)
[ ] Container runs as non-root user (verify: docker exec ... whoami → fxlab)
[ ] No .env file is baked into the container image
[ ] Log level is INFO or WARNING (not DEBUG in production)
[ ] SQL_ECHO is false (not true — leaks query text to logs)
[ ] Redis is reachable (if using Redis-backed features)
[ ] PostgreSQL max_connections >= (DB_POOL_SIZE + DB_POOL_OVERFLOW) × workers
[ ] TLS certificate is valid and not expiring within 30 days
[ ] Reverse proxy forwards X-Forwarded-For and X-Correlation-ID headers
```

---

## 10. Monitoring and Observability

### 10.1 Structured logging

All log output uses `structlog` in JSON format. Every log entry includes:

- `correlation_id`: Traces a request through all layers (from `X-Correlation-ID` header)
- `operation`: Snake-case operation name
- `component`: Originating module or class
- `duration_ms`: For timed operations
- `result`: `success`, `failure`, or `partial`

Configure log aggregation (ELK, CloudWatch Logs, Datadog) to ingest JSON
from stdout/stderr.

### 10.2 Key log events to alert on

| Log pattern | Severity | Action |
|-------------|----------|--------|
| `db.connection_check_failed` | CRITICAL | Database unreachable — check connectivity |
| `db.pool_config_invalid` | CRITICAL | Invalid pool env var — using default |
| `auth.invalid_token` | WARNING | Monitor for brute-force attempts |
| `rate_limit.exceeded` | WARNING | Monitor for DDoS or misconfigured clients |
| `api.unhandled_error` | ERROR | Investigate immediately |

### 10.3 Prometheus metrics

Prometheus counters and histograms are exposed at `GET /metrics`:

| Metric | Type | Description |
|--------|------|-------------|
| `approval_requests_total` | Counter | Governance approval requests |
| `override_requests_total` | Counter | Override requests by type |
| `chart_cache_hits_total` | Counter | Chart cache hits vs misses |
| `lttb_applied_total` | Counter | LTTB downsampling invocations |
| `export_requests_total` | Counter | Data export requests |
| `orders_submitted_total` | Counter | Orders submitted to brokers |
| `orders_filled_total` | Counter | Orders filled by brokers |
| `kill_switch_mtth_seconds` | Histogram | Kill-switch mean-time-to-halt |
| `broker_request_duration_seconds` | Histogram | Broker API call latency |

Configure Prometheus to scrape `/metrics` every 15–30 seconds.

### 10.4 Distributed tracing

OpenTelemetry is configured to export traces to a Jaeger-compatible OTLP
endpoint. Set `OTEL_EXPORTER_OTLP_ENDPOINT` (default: `http://jaeger:4317`)
and `OTEL_TRACES_SAMPLER_ARG` (default: `1.0` — sample all; reduce in
production to `0.1` or lower for high-throughput deployments).

Instrumented layers: FastAPI middleware, SQLAlchemy queries, HTTPX outbound
calls. All spans carry `correlation_id` as a baggage item.

---

## 11. Backup and Recovery

### 11.1 Database backups

PostgreSQL backups should be configured at the infrastructure level:

```bash
# Manual backup
pg_dump -h db.example.com -U fxlab -d fxlab -Fc > fxlab_$(date +%Y%m%d_%H%M%S).dump

# Restore
pg_restore -h db.example.com -U fxlab -d fxlab -c fxlab_backup.dump
```

For managed databases (RDS, Cloud SQL), enable automated daily backups with
at least 7-day retention. Enable point-in-time recovery (PITR) for critical
deployments.

### 11.2 Secret rotation

To rotate `JWT_SECRET_KEY`:

1. Generate a new secret.
2. Update the secret in your secrets manager.
3. Perform a rolling restart of all API containers.
4. Active tokens signed with the old key will fail validation; users will
   need to re-authenticate. Plan rotation during low-traffic windows.

---

## 12. Troubleshooting

### API returns 401 on all requests

- Verify `JWT_SECRET_KEY` matches between the token issuer and the API.
- Check token expiration: `python3 -c "import jwt; print(jwt.decode(TOKEN, options={'verify_signature': False}))"`.
- Ensure `ENVIRONMENT` is not set to `test` in production (allows `TEST_TOKEN` bypass).

### Database connection errors at startup

- Verify `DATABASE_URL` is correct and the database is reachable.
- Check that migrations completed: look for `[entrypoint] Migrations complete` in logs.
- Verify PostgreSQL `max_connections` is sufficient for the pool configuration.

### Rate limiting too aggressive / too lenient

- Check `RATE_LIMIT_GOVERNANCE` and `RATE_LIMIT_DEFAULT` environment variables.
- Rate limits are per IP address; ensure `X-Forwarded-For` is forwarded by the reverse proxy.
- In-memory rate limiter resets on container restart.

### Health check failing

- `GET /health` returns 503 when the database is unreachable.
- Check PostgreSQL connectivity and credentials.
- Verify the container has network access to the database host.

---

## 13. Staging Dry-Run Checklist

Run through this checklist before promoting any release to production.
Each item must pass; failures block the promotion.

### 13.1 Infrastructure validation

```
[ ] Docker images build successfully (API + frontend)
[ ] docker-compose up -d starts all services (API, PostgreSQL, Redis, Jaeger)
[ ] API container runs as non-root user: docker exec fxlab-api whoami → fxlab
[ ] No .env baked into container: docker exec fxlab-api cat /app/.env → not found
[ ] Production sentinel present: docker exec fxlab-api cat /app/.production-build → exists
[ ] ENVIRONMENT=production blocks TEST_TOKEN bypass (verify 401 with Bearer TEST_TOKEN)
```

### 13.2 Database and migrations

```
[ ] alembic upgrade head completes without errors
[ ] alembic current shows latest revision (14 migrations as of Phase 3)
[ ] All tables created: users, strategies, deployments, orders, order_fills,
    positions, pnl_snapshots, approvals, overrides, draft_autosaves,
    chart_cache_entries, feed_health_events, exports, artifacts, audit_events
[ ] sslmode=require enforced for PostgreSQL URL (startup validation)
[ ] Connection pool size matches worker count × pool_size
```

### 13.3 Authentication and authorization

```
[ ] JWT_SECRET_KEY is ≥32 bytes (startup validation catches undersized keys)
[ ] Token issuance returns valid JWT with correct scopes
[ ] Expired tokens return 401
[ ] Token size >16KB returns 401 (DoS guard)
[ ] Each RBAC scope correctly gates its endpoints (7 scopes verified)
[ ] Separation-of-duties: submitter cannot approve own request
```

### 13.4 API endpoint smoke tests

```
[ ] GET /health returns 200 with db: ok
[ ] GET /ready returns 200 with db, redis, brokers status
[ ] GET /metrics returns Prometheus text format
[ ] GET /strategies/ returns 200 with auth, 401 without
[ ] POST /strategies/draft/autosave returns 200 with valid payload
[ ] GET /approvals/ returns paginated list
[ ] GET /overrides/ returns paginated list
[ ] GET /queues/ returns queue snapshots
[ ] GET /feed-health returns feed health reports
[ ] GET /runs/{id}/charts returns chart data (or 404 for missing run)
```

### 13.5 Security headers and middleware

```
[ ] Response includes X-Frame-Options: DENY
[ ] Response includes X-Content-Type-Options: nosniff
[ ] Response includes Referrer-Policy: strict-origin-when-cross-origin
[ ] CORS rejects requests from non-allowed origins
[ ] Rate limiter triggers after configured threshold (10 req/min for auth)
[ ] Rate limiter uses Redis backend (LOGIN_TRACKER_BACKEND=redis)
[ ] Request body >524KB returns 413
```

### 13.6 Observability

```
[ ] Structured JSON logs on stdout with correlation_id
[ ] Prometheus /metrics endpoint returns counters and histograms
[ ] OpenTelemetry traces arrive at Jaeger (check Jaeger UI on :16686)
[ ] Health check endpoints respond within 1 second
[ ] Log level set to INFO or WARNING (not DEBUG)
```

### 13.7 Graceful shutdown

```
[ ] Send SIGTERM to API container
[ ] Verify /ready returns 503 immediately (stops receiving new traffic)
[ ] Verify in-flight requests complete before container exits
[ ] Verify container exits within terminationGracePeriodSeconds (45s)
[ ] Verify new container passes readiness probe before receiving traffic
```

### 13.8 Frontend validation

```
[ ] Frontend nginx serves index.html on all routes (SPA fallback)
[ ] Static assets have Cache-Control: max-age=31536000, immutable
[ ] Content-Security-Policy header present and correct
[ ] HSTS header present with includeSubDomains and preload
[ ] Frontend connects to API backend (check browser network tab)
[ ] Auth flow completes: login → token → authenticated route access
```

### 13.9 Known operational gaps (document for follow-up)

These items are recommended but not required for initial production launch:

```
[ ] External secrets management (AWS Secrets Manager / Vault) — currently manual injection
[ ] Infrastructure-as-Code (Terraform/Pulumi) — currently YAML templates
[ ] Prometheus alerting rules — metrics exist but no alert thresholds defined
[ ] Automated CD pipeline — currently manual promotion
[ ] Load testing — no capacity planning data exists yet
[ ] SBOM generation — no CycloneDX/SPDX in CI
[ ] User-based rate limiting — only per-IP currently
```
