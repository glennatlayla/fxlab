# FXLab API — Multi-stage Dockerfile
#
# Stage 1 (builder): install dependencies in an isolated layer.
# Stage 2 (runtime): copy only installed packages + source; run as non-root.
#
# Build args:
#   ENVIRONMENT  — "development" enables uvicorn --reload (default: production)

# ---------------------------------------------------------------------------
# Stage 1: builder
# ---------------------------------------------------------------------------
FROM python:3.12-slim AS builder

WORKDIR /build

# Install system build deps (psycopg2-binary needs libpq at link time)
RUN apt-get update && apt-get install -y --no-install-recommends \
        gcc \
        libpq-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir --prefix=/install -r requirements.txt

# ---------------------------------------------------------------------------
# Stage 2: runtime
# ---------------------------------------------------------------------------
FROM python:3.12-slim AS runtime

# Runtime libpq for psycopg2
RUN apt-get update && apt-get install -y --no-install-recommends \
        libpq5 \
        curl \
    && rm -rf /var/lib/apt/lists/*

# Non-root user (principle of least privilege)
RUN useradd --system --create-home --shell /bin/false fxlab

WORKDIR /app

# Copy installed packages from builder
COPY --from=builder /install /usr/local

# Copy application source
COPY services/ ./services/
COPY libs/ ./libs/
COPY migrations/ ./migrations/
COPY alembic.ini ./alembic.ini

# Ensure non-root ownership
RUN chown -R fxlab:fxlab /app

# Make entrypoint executable
RUN chmod +x /app/services/api/entrypoint.sh

USER fxlab

EXPOSE 8000

# Health check matching docker-compose expectation
HEALTHCHECK --interval=10s --timeout=5s --retries=5 --start-period=10s \
    CMD curl -f http://localhost:8000/health || exit 1

# Default: production mode (no reload). Override ENVIRONMENT=development to enable reload.
ARG ENVIRONMENT=production
ENV ENVIRONMENT=${ENVIRONMENT}

# Entrypoint: run migrations, then execute the CMD
ENTRYPOINT ["bash", "services/api/entrypoint.sh"]

# CMD: uvicorn with environment-specific settings
CMD ["sh", "-c", \
     "if [ \"$ENVIRONMENT\" = 'development' ]; then \
        uvicorn services.api.main:app --host 0.0.0.0 --port 8000 --reload; \
      else \
        uvicorn services.api.main:app --host 0.0.0.0 --port 8000 --workers 2; \
      fi"]
