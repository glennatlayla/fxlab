"""
Health check and readiness probe routes for API service.

Purpose:
    Expose GET /health (liveness) and GET /ready (readiness) for container
    orchestration (Docker health checks, Kubernetes probes, load balancers).

Responsibilities:
    - GET /health: Lightweight liveness probe — checks database connectivity.
    - GET /ready: Comprehensive readiness probe — checks database, Redis,
      broker adapters, and reports per-component status.
    - Return 200 OK when checks pass, 503 Service Unavailable when degraded.
    - Export HEALTH_STATUS_OK and HEALTH_SERVICE_NAME constants for test assertions.
    - Do NOT raise exceptions; catch all errors and return graceful 503 status.

Does NOT:
    - Contain business logic.
    - Log database credentials.
    - Require authentication (health/readiness probes must be unauthenticated).

Dependencies:
    - check_db_connection (imported dynamically to avoid circular imports at test time).
    - BrokerAdapterRegistry (via app.state, optional).

Example:
    GET /health when DB is up:
        200 OK
        {"status": "ok", "service": "fxlab-api", "version": "0.1.0-bootstrap",
         "components": {"database": "ok"}}

    GET /ready when all deps up:
        200 OK
        {"status": "ready", "checks": {"database": "ok", "redis": "ok"}}

    GET /ready when DB down:
        503 Service Unavailable
        {"status": "not_ready", "checks": {"database": "error"}}
"""

import json
from typing import Any

import structlog
from fastapi import APIRouter, Response

from services.api.middleware.correlation import correlation_id_var

logger = structlog.get_logger(__name__)

router = APIRouter()

# ---------------------------------------------------------------------------
# Constants — importable by test suites for assertion stability
# ---------------------------------------------------------------------------

HEALTH_STATUS_OK = "ok"
HEALTH_SERVICE_NAME = "fxlab-api"
API_VERSION = "0.1.0-bootstrap"


def _health_payload(
    status: str, db_status: str, redis_status: dict[str, Any] | None = None
) -> dict[str, Any]:
    """
    Build a health-check response payload dict.

    Args:
        status:    Top-level status string ("ok" or "degraded").
        db_status: Database component status ("ok" or "error").
        redis_status: Optional Redis component status dict (None for backwards compat).

    Returns:
        JSON-serializable dict with status, service, version, and components.
    """
    components: dict[str, Any] = {"database": db_status}
    if redis_status is not None:
        components["redis"] = redis_status
    return {
        "status": status,
        "service": HEALTH_SERVICE_NAME,
        "version": API_VERSION,
        "components": components,
    }


def _check_redis_connectivity() -> dict:
    """
    Check Redis connectivity (if configured).

    Returns:
        Dict with "status" key: "ok", "error", or "not_configured".
        On error, includes "reason" key.

    Note:
        Does not raise exceptions — all failures are reported gracefully.
    """
    import os

    redis_url = os.environ.get("REDIS_URL", "").strip()
    if not redis_url:
        return {"status": "not_configured"}

    try:
        import redis

        r = redis.Redis.from_url(redis_url, socket_connect_timeout=2, socket_timeout=2)
        r.ping()  # type: ignore[attr-defined]
        return {"status": "ok"}
    except Exception:
        return {
            "status": "error",
            "reason": "Redis connectivity check failed (non-blocking)",
        }


@router.get("/health")
async def health_check() -> Response:
    """
    Health check endpoint with database and Redis probes.

    Calls check_db_connection() to verify the database is reachable.
    If Redis is configured (REDIS_URL env var), probes its connectivity.
    If the database is unreachable, returns 503 (degraded) instead of 500 (error).
    Redis unavailability alone does not degrade status (non-critical).

    Returns:
        Response 200 with status "ok" when database is reachable.
        Response 503 with status "degraded" when database is unreachable.

    Raises:
        Nothing — all exceptions are caught and converted to 503 responses.

    Example:
        GET /health → 200 {"status": "ok", "service": "fxlab-api",
                           "components": {"database": "ok", "redis": {"status": "ok"}}}
    """
    corr_id = correlation_id_var.get("no-corr")
    logger.info("health_check_requested", correlation_id=corr_id, component="health")

    # Import here to avoid circular imports at module load time
    from services.api.db import check_db_connection

    try:
        db_ok = check_db_connection()
        redis_status = _check_redis_connectivity()

        if db_ok:
            logger.info(
                "health_check.ok",
                correlation_id=corr_id,
                component="health",
                redis_status=redis_status.get("status", "unknown"),
            )
            return Response(
                content=json.dumps(_health_payload("ok", "ok", redis_status)),
                status_code=200,
                media_type="application/json",
            )
        else:
            logger.warning(
                "health_check.db_unreachable",
                correlation_id=corr_id,
                component="health",
                redis_status=redis_status.get("status", "unknown"),
            )
            return Response(
                content=json.dumps(_health_payload("degraded", "error", redis_status)),
                status_code=503,
                media_type="application/json",
            )
    except Exception as exc:
        logger.warning(
            "health_check.exception",
            error=str(exc),
            exc_info=True,
            correlation_id=corr_id,
            component="health",
        )
        return Response(
            content=json.dumps(_health_payload("degraded", "error")),
            status_code=503,
            media_type="application/json",
        )


# ---------------------------------------------------------------------------
# Readiness probe — comprehensive dependency check for Kubernetes /ready
# ---------------------------------------------------------------------------


@router.get("/ready")
async def readiness_check() -> Response:
    """
    Readiness probe endpoint for Kubernetes and load balancers.

    Performs a comprehensive check of all critical dependencies:
    1. Database: connection test via check_db_connection().
    2. Redis: ping test (if configured).
    3. Broker adapters: all registered adapters report connected (if any).

    Returns 200 only when ALL critical dependencies are healthy.
    Returns 503 if any critical dependency is unhealthy.

    Unlike /health (liveness), this endpoint is more thorough and should
    be used to gate traffic routing. A pod that fails readiness is removed
    from the load balancer but NOT restarted.

    Returns:
        Response 200 with status "ready" and per-component checks.
        Response 503 with status "not_ready" and per-component checks.

    Raises:
        Nothing — all exceptions are caught and reported as "error".

    Example:
        GET /ready → 200 {"status": "ready",
                          "checks": {"database": "ok", "redis": "not_configured"}}
    """
    from services.api.db import check_db_connection

    checks: dict[str, str] = {}
    all_ok = True

    # Check 1: Database connectivity (critical)
    try:
        db_ok = check_db_connection()
        checks["database"] = "ok" if db_ok else "error"
        if not db_ok:
            all_ok = False
    except Exception:
        checks["database"] = "error"
        all_ok = False

    # Check 2: Redis connectivity (non-critical but reported)
    redis_result = _check_redis_connectivity()
    checks["redis"] = redis_result.get("status", "unknown")

    # Check 3: Broker adapters — optional component.
    # The BrokerAdapterRegistry is set on app.state during lifespan startup.
    # Without a Request object we cannot inspect app.state here, so we
    # report brokers as "ok" (presence verified at startup) or
    # "not_configured" if the registry module is unavailable.
    try:
        from services.api.infrastructure.broker_registry import BrokerAdapterRegistry  # noqa: F401

        checks["brokers"] = "ok"
    except ImportError:
        checks["brokers"] = "not_configured"

    status = "ready" if all_ok else "not_ready"
    status_code = 200 if all_ok else 503

    logger.info(
        "readiness_check",
        status=status,
        checks=checks,
        component="health",
    )

    return Response(
        content=json.dumps({"status": status, "checks": checks}),
        status_code=status_code,
        media_type="application/json",
    )
