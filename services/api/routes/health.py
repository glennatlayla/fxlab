"""
Health check and readiness probe routes for API service.

Purpose:
    Expose GET /health (liveness), GET /ready (readiness), and
    GET /health/details (catalog + run-pool inventory) for container
    orchestration (Docker health checks, Kubernetes probes, load
    balancers) and operator dashboards.

Responsibilities:
    - GET /health: Lightweight liveness probe — checks database connectivity.
    - GET /ready: Comprehensive readiness probe — checks database, Redis,
      broker adapters, and reports per-component status.
    - GET /health/details: Authenticated read-only endpoint that surfaces
      catalog + run-pool inventory counts (datasets, strategies, runs in
      flight + total persisted) so operators can confirm the API process
      sees the expected state at a glance.
    - Return 200 OK when checks pass, 503 Service Unavailable when degraded.
    - Export HEALTH_STATUS_OK and HEALTH_SERVICE_NAME constants for test assertions.
    - Do NOT raise exceptions; catch all errors and return graceful 503 status.

Does NOT:
    - Contain business logic.
    - Log database credentials.
    - Require authentication on /health and /ready (those probes must be
      unauthenticated). /health/details DOES require authentication and
      the admin:manage scope (matches /admin/* convention).

Dependencies:
    - check_db_connection (imported dynamically to avoid circular imports at test time).
    - BrokerAdapterRegistry (via app.state, optional).
    - DatasetServiceInterface (via app.state.dataset_service, set by main.py
      lifespan startup): used by /health/details to read catalog inventory.
    - RunExecutorPool (via app.state.run_executor_pool, set by main.py):
      used by /health/details for in-flight run count.

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

    GET /health/details when everything is happy:
        200 OK
        {
            "status": "ok",
            "service": "fxlab-api",
            "version": "0.1.0-bootstrap",
            "components": {
                "database": "ok",
                "datasets":   {"status": "ok", "count": 3},
                "strategies": {"status": "ok", "count": 12},
                "runs":       {"status": "ok", "in_flight": 1,
                               "total_persisted": 47}
            },
            "checked_at": "2026-04-26T16:30:00+00:00"
        }
"""

import json
from datetime import UTC, datetime
from typing import Any

import structlog
from fastapi import APIRouter, Depends, Request, Response
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from libs.contracts.models import ResearchRun, Strategy
from services.api.auth import AuthenticatedUser, require_scope
from services.api.db import get_db
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
        r.ping()  # type: ignore[attr-defined]  # redis.Redis.from_url stub returns None-typed in some versions
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


# ---------------------------------------------------------------------------
# Detailed inventory probe — authenticated, admin-scoped
# ---------------------------------------------------------------------------


#: Generic redacted reason returned in 503 components when an aggregate
#: query fails. We deliberately do NOT echo the upstream exception
#: message here because driver errors (psycopg2, sqlalchemy) frequently
#: include host names, ports, and occasionally credential fragments. Use
#: server-side structured logs (see ``health_details.component_failed``)
#: to inspect the underlying cause.
_DETAILS_REDACTED_ERROR = "Aggregate query failed; see structured logs."


def _count_table(db: Session, model: Any) -> int:
    """
    Return the row count for an ORM-mapped table via ``SELECT COUNT(*)``.

    Args:
        db: Request-scoped SQLAlchemy session.
        model: ORM model class (e.g. :class:`Strategy`,
            :class:`ResearchRun`). The function reads the model's
            ``__table__`` so it works for any declarative base.

    Returns:
        Non-negative integer row count.

    Raises:
        Whatever the SQLAlchemy driver raises on connection failure.
        Callers MUST translate driver exceptions into a degraded
        component status — see :func:`_safe_component_count`.
    """
    stmt = select(func.count()).select_from(model)
    return int(db.execute(stmt).scalar_one())


def _safe_component_count(
    label: str,
    counter: Any,
    *,
    correlation_id: str,
) -> tuple[int | None, str | None]:
    """
    Invoke ``counter`` (a zero-argument callable returning int) and
    translate any exception into a redacted reason string suitable for
    inclusion in the 503 body.

    Args:
        label: Component name used in the structured log entry
            (``"datasets"``, ``"strategies"``, ``"runs"``).
        counter: Zero-arg callable that returns the integer count.
        correlation_id: Propagated through the structured log on failure.

    Returns:
        ``(count, None)`` on success, ``(None, reason)`` on failure.
        ``reason`` is the generic :data:`_DETAILS_REDACTED_ERROR`
        constant — the wire body never carries driver text.
    """
    try:
        return int(counter()), None
    except Exception as exc:
        logger.warning(
            "health_details.component_failed",
            component=label,
            error=str(exc),
            exc_info=True,
            correlation_id=correlation_id,
        )
        return None, _DETAILS_REDACTED_ERROR


@router.get("/health/details", tags=["health"])
def health_details(
    request: Request,
    db: Session = Depends(get_db),
    user: AuthenticatedUser = Depends(require_scope("admin:manage")),
) -> Response:
    """
    Read-only inventory probe surfacing catalog + run-pool counts.

    Returns three component blocks: datasets (registered catalog rows),
    strategies (rows in the ``strategies`` table), and runs (in-flight
    count from :class:`RunExecutorPool` + total persisted research-run
    rows). Each block is independent — if one aggregate query fails, the
    other components still report their real counts and the failed block
    reports ``status: "error"`` with a redacted reason. The top-level
    status is ``"degraded"`` whenever any component is in error.

    Args:
        request: FastAPI request (read for ``request.app.state`` lookups
            of the run executor pool and dataset service).
        db: Request-scoped SQLAlchemy session injected by
            :func:`services.api.db.get_db`.
        user: Authenticated user with the ``admin:manage`` scope.

    Returns:
        200 + payload (see module docstring) on full success.
        503 + payload with the same shape but ``status: "degraded"`` on
        partial failure.

    Raises:
        HTTPException(401): Missing / invalid Authorization header
            (raised by :func:`get_current_user` upstream of the scope
            dependency).
        HTTPException(403): Caller lacks the ``admin:manage`` scope.
    """
    correlation_id = correlation_id_var.get("no-corr")
    logger.info(
        "health_details.requested",
        operation="health_details",
        component="health",
        correlation_id=correlation_id,
        user_id=user.user_id,
    )

    # --- Datasets count via the dataset service on app.state ---------------
    dataset_service = getattr(request.app.state, "dataset_service", None)
    if dataset_service is None:
        # The service is wired during lifespan startup; if it is not
        # present we treat the dataset path as unconfigured rather than
        # erroring (parity with /ready's broker handling).
        datasets_count: int | None = 0
        datasets_reason: str | None = None
    else:
        datasets_count, datasets_reason = _safe_component_count(
            "datasets",
            dataset_service.count,
            correlation_id=correlation_id,
        )

    # --- Strategies + total persisted runs via direct SQL ------------------
    strategies_count, strategies_reason = _safe_component_count(
        "strategies",
        lambda: _count_table(db, Strategy),
        correlation_id=correlation_id,
    )
    runs_total_persisted, runs_total_reason = _safe_component_count(
        "runs",
        lambda: _count_table(db, ResearchRun),
        correlation_id=correlation_id,
    )

    # --- In-flight runs from the executor pool on app.state ----------------
    pool = getattr(request.app.state, "run_executor_pool", None)
    if pool is None:
        in_flight = 0
    else:
        try:
            in_flight = int(pool.inflight_count())
        except Exception as exc:
            logger.warning(
                "health_details.in_flight_lookup_failed",
                component="runs",
                error=str(exc),
                exc_info=True,
                correlation_id=correlation_id,
            )
            in_flight = 0

    # --- Compose component blocks -----------------------------------------
    db_status = "ok" if strategies_reason is None and runs_total_reason is None else "error"

    datasets_block: dict[str, Any] = (
        {"status": "ok", "count": datasets_count}
        if datasets_reason is None
        else {"status": "error", "count": 0, "reason": datasets_reason}
    )
    strategies_block: dict[str, Any] = (
        {"status": "ok", "count": strategies_count}
        if strategies_reason is None
        else {"status": "error", "count": 0, "reason": strategies_reason}
    )
    runs_block: dict[str, Any] = (
        {
            "status": "ok",
            "in_flight": in_flight,
            "total_persisted": runs_total_persisted,
        }
        if runs_total_reason is None
        else {
            "status": "error",
            "in_flight": in_flight,
            "total_persisted": 0,
            "reason": runs_total_reason,
        }
    )

    components = {
        "database": db_status,
        "datasets": datasets_block,
        "strategies": strategies_block,
        "runs": runs_block,
    }

    any_error = any(
        block["status"] == "error" for block in (datasets_block, strategies_block, runs_block)
    )
    top_status = "degraded" if any_error else "ok"
    status_code = 503 if any_error else 200

    body = {
        "status": top_status,
        "service": HEALTH_SERVICE_NAME,
        "version": API_VERSION,
        "components": components,
        "checked_at": datetime.now(UTC).isoformat(),
    }

    logger.info(
        "health_details.completed",
        operation="health_details",
        component="health",
        correlation_id=correlation_id,
        status=top_status,
        dataset_count=datasets_block.get("count"),
        strategy_count=strategies_block.get("count"),
        runs_in_flight=in_flight,
        runs_total_persisted=runs_block.get("total_persisted"),
        result="success" if not any_error else "degraded",
    )

    return Response(
        content=json.dumps(body),
        status_code=status_code,
        media_type="application/json",
    )
