# FXLab — Installation and Deployment Guide

FXLab is a trading platform for backtesting, paper trading, and live execution of quantitative strategies. This guide covers deploying FXLab on a Linux server using Docker.

## System Requirements

| Resource | Minimum | Recommended |
|----------|---------|-------------|
| OS | Ubuntu 20.04+, Debian 11+, RHEL 8+ | Ubuntu 22.04 LTS |
| CPU | 2 cores | 4+ cores |
| RAM | 4 GB | 8 GB |
| Disk | 10 GB free | 20 GB SSD |
| Docker | Engine 24+ | Latest stable |
| Docker Compose | v2 | Latest stable |
| Network | Ports 80, 443 available | Static IP or DNS |

## Quick Start (5 minutes)

```bash
# 1. Extract the release archive
unzip fxlab-*.zip
cd fxlab-*

# 2. Run the installer (as root)
sudo ./install.sh

# 3. Open the web application
# The installer prints the URL at the end. Default: http://<your-ip>:80
```

That's it. The installer handles everything: Docker validation, secret generation, database setup, service startup, and systemd registration.

## What the Installer Does

1. **Validates prerequisites** — checks Docker version, available RAM, disk space, and that ports 80/443 are free.
2. **Copies files** to `/opt/fxlab` (configurable via `FXLAB_HOME`).
3. **Generates secrets** — creates a cryptographically strong JWT signing key and PostgreSQL password if not already set.
4. **Builds Docker images** — multi-stage builds for the API (Python 3.12) and frontend (Node 20 + Nginx).
5. **Starts services** — PostgreSQL, Redis, API, frontend, and Nginx edge proxy.
6. **Runs database migrations** — Alembic migrations execute automatically on API container startup.
7. **Installs systemd service** — FXLab starts automatically on boot.
8. **Runs health checks** — verifies all services are responding.

## Architecture

```
Internet → Nginx (port 80/443)
              ├─ /api/*   → FastAPI Backend (port 8000)
              │               ├─ PostgreSQL (port 5432)
              │               └─ Redis (port 6379)
              └─ /*       → React Frontend (Nginx, port 3000)
```

All services run in Docker containers on a single host, communicating over an internal bridge network. Only the edge Nginx proxy exposes ports to the host.

## Accessing the Application

After installation, access FXLab at:

| Resource | URL |
|----------|-----|
| **Web Application** | `http://<server-ip>:80` |
| **API Endpoint** | `http://<server-ip>:80/api/` |
| **API Health Check** | `http://<server-ip>:80/api/health` |
| **API Documentation** | `http://<server-ip>:80/api/docs` |

Replace `<server-ip>` with your server's IP address or hostname. If you changed the HTTP port during installation, use that port instead of 80.

### Creating Your First User

```bash
# Register a new user via the API
curl -X POST http://localhost/api/auth/register \
  -H "Content-Type: application/json" \
  -d '{
    "username": "admin",
    "password": "your-secure-password",
    "email": "admin@example.com",
    "role": "admin"
  }'

# Login to get a JWT token
curl -X POST http://localhost/api/auth/token \
  -H "Content-Type: application/json" \
  -d '{
    "username": "admin",
    "password": "your-secure-password"
  }'
```

## Service Management

FXLab runs as a systemd service for automatic startup and easy management.

```bash
# Check status
sudo systemctl status fxlab

# Stop the platform
sudo systemctl stop fxlab

# Start the platform
sudo systemctl start fxlab

# Restart (rebuilds images if code changed)
sudo systemctl restart fxlab

# View logs
journalctl -u fxlab -f

# View individual service logs
cd /opt/fxlab
docker compose -f docker-compose.prod.yml logs -f api      # API logs
docker compose -f docker-compose.prod.yml logs -f web      # Frontend logs
docker compose -f docker-compose.prod.yml logs -f postgres  # Database logs
docker compose -f docker-compose.prod.yml logs -f redis     # Redis logs
docker compose -f docker-compose.prod.yml logs -f nginx     # Proxy logs
```

## Configuration

All configuration is in `/opt/fxlab/.env`. This file is created during installation with auto-generated secrets.

### Key Variables

| Variable | Required | Default | Description |
|----------|----------|---------|-------------|
| `JWT_SECRET_KEY` | Yes | Auto-generated | JWT signing key (32+ bytes) |
| `POSTGRES_PASSWORD` | Yes | Auto-generated | Database password |
| `POSTGRES_USER` | No | `fxlab` | Database user |
| `POSTGRES_DB` | No | `fxlab` | Database name |
| `LOG_LEVEL` | No | `WARNING` | API log level |
| `FXLAB_HTTP_PORT` | No | `80` | HTTP port |
| `FXLAB_HTTPS_PORT` | No | `443` | HTTPS port |
| `CORS_ALLOWED_ORIGINS` | No | `http://localhost` | Allowed CORS origins |

### Changing Ports

If ports 80/443 are unavailable, set custom ports before installing:

```bash
export FXLAB_HTTP_PORT=8080
export FXLAB_HTTPS_PORT=8443
sudo -E ./install.sh
```

Or edit `.env` after installation and restart:

```bash
sudo nano /opt/fxlab/.env
# Change FXLAB_HTTP_PORT and FXLAB_HTTPS_PORT
sudo systemctl restart fxlab
```

## Database Management

### Backups

```bash
# Create a backup
docker compose -f docker-compose.prod.yml exec postgres \
  pg_dump -U fxlab -d fxlab > backup-$(date +%Y%m%d).sql

# Restore a backup
docker compose -f docker-compose.prod.yml exec -T postgres \
  psql -U fxlab -d fxlab < backup-20260413.sql
```

### Migrations

Database migrations run automatically when the API container starts. To run them manually:

```bash
cd /opt/fxlab
docker compose -f docker-compose.prod.yml exec api \
  python -m alembic upgrade head
```

## Troubleshooting

### Services won't start

```bash
# Check Docker daemon
sudo systemctl status docker

# Check container status
cd /opt/fxlab
docker compose -f docker-compose.prod.yml ps

# Check container logs for errors
docker compose -f docker-compose.prod.yml logs --tail=50
```

### Port conflicts

```bash
# Find what's using port 80
sudo ss -tlnp | grep :80

# Kill the conflicting process or change the FXLab port
sudo nano /opt/fxlab/.env
# Set FXLAB_HTTP_PORT=8080
sudo systemctl restart fxlab
```

### Database connection failures

```bash
# Check PostgreSQL is running
docker compose -f docker-compose.prod.yml exec postgres pg_isready

# Check database logs
docker compose -f docker-compose.prod.yml logs postgres

# Reset database (CAUTION: destroys all data)
docker compose -f docker-compose.prod.yml down -v
docker volume rm fxlab-postgres-data
sudo systemctl restart fxlab
```

### Memory issues

```bash
# Check container resource usage
docker stats --no-stream

# If containers are OOM-killed, increase host RAM or adjust limits
# in docker-compose.prod.yml under deploy.resources.limits
```

### Resetting the installation

```bash
# Stop and remove everything
sudo systemctl stop fxlab
cd /opt/fxlab
docker compose -f docker-compose.prod.yml down -v --rmi all
sudo systemctl disable fxlab
sudo rm /etc/systemd/system/fxlab.service
sudo systemctl daemon-reload

# Re-install
sudo ./install.sh
```

## Updating FXLab

```bash
# 1. Extract the new release
unzip fxlab-new-version.zip -d /tmp/fxlab-update

# 2. Stop the current instance
sudo systemctl stop fxlab

# 3. Back up the database
cd /opt/fxlab
docker compose -f docker-compose.prod.yml exec postgres \
  pg_dump -U fxlab -d fxlab > /tmp/fxlab-backup-$(date +%Y%m%d).sql

# 4. Update application files (preserves .env and data volumes)
sudo rsync -a --exclude '.env' --exclude '.git' \
  /tmp/fxlab-update/fxlab-*/ /opt/fxlab/

# 5. Rebuild and restart (migrations run automatically)
sudo systemctl start fxlab

# 6. Verify
sudo systemctl status fxlab
curl http://localhost/api/health
```

## Security Notes

- The `.env` file contains secrets and is set to mode 600 (owner-read-only). Back it up securely.
- PostgreSQL and Redis are not exposed to the host network — they communicate only within the Docker bridge network.
- The Nginx edge proxy includes security headers (CSP, HSTS, X-Frame-Options).
- The API container runs as a non-root user (`fxlab`).
- JWT tokens expire after 60 minutes by default.
- Rate limiting is enforced on all API endpoints (100 req/min default, stricter on auth and governance endpoints).

## File Structure

```
/opt/fxlab/
├── .env                           # Production secrets (auto-generated)
├── .env.production.template       # Configuration template
├── docker-compose.prod.yml        # Production Docker Compose
├── install.sh                     # Installation script
├── build-release.sh               # Release packaging script
├── README-INSTALL.md              # This file
├── alembic.ini                    # Database migration config
├── requirements.txt               # Python dependencies
├── deploy/
│   ├── nginx/fxlab.conf          # Nginx reverse proxy config
│   └── systemd/fxlab.service     # systemd service unit
├── services/
│   └── api/                      # FastAPI backend
│       ├── Dockerfile
│       ├── entrypoint.sh
│       ├── main.py
│       └── ...
├── frontend/
│   ├── Dockerfile
│   ├── nginx.conf                # Frontend Nginx (internal)
│   └── src/                      # React application
├── libs/                         # Shared contracts and utilities
├── migrations/                   # Alembic database migrations
└── config/                       # Service configuration
```
