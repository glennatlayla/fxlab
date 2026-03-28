"""
FastAPI application entry point.

Responsibilities:
- Create and configure the FastAPI application instance.
- Register all route routers.
- Export service-layer stubs that are mocked in tests (get_run_results,
  get_readiness_report, submit_promotion_request, check_permission,
  audit_service).
- Define lifespan context manager for startup/shutdown logging.

Does NOT:
- Contain business logic.
- Perform I/O directly.

Example:
    from services.api.main import app
    # Use with TestClient or uvicorn.
"""

from __future__ import annotations

import os
from contextlib import asynccontextmanager
from typing import Any, Literal

import structlog
from fastapi import FastAPI, HTTPException, Path
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from services.api.middleware.body_size import BodySizeLimitMiddleware
from services.api.middleware.correlation import CorrelationIDMiddleware
from services.api.middleware.rate_limit import RateLimitMiddleware

from libs.contracts.base import APIResponse
from services.api.routes import (
    approvals,
    artifacts,
    audit,
    charts,
    data_certification,
    exports,
    feed_health,
    feeds,
    governance,
    health,
    observability,
    overrides,
    parity,
    promotions,
    queues,
    readiness,
    research,
    runs,
    strategies,
    symbol_lineage,
)

logger = structlog.get_logger(__name__)

API_VERSION = "0.1.0-bootstrap"


# ---------------------------------------------------------------------------
# Lifespan — must be defined before FastAPI() is instantiated.
# ---------------------------------------------------------------------------


def _check_pydantic_core() -> None:
    """
    Detect whether pydantic-core's compiled Rust extension is loaded.

    The compiled extension is required for field constraint enforcement
    (min_length, pattern, ge/le, type coercion). When only the pure-Python
    stub is available, these constraints are silently skipped and manual
    HTTPException(422) workarounds must cover all critical validation paths.

    This check runs at startup so the problem surfaces immediately in logs
    rather than being discovered at runtime via data corruption.

    Note:
        The known root cause in this deployment is that the installed wheel
        was compiled for macOS (darwin) but the service runs on Linux.
        Fix: reinstall pydantic-core from PyPI using a Linux wheel:
            pip install --force-reinstall pydantic-core==<version>
    """
    try:
        from pydantic_core import SchemaValidator

        module = getattr(SchemaValidator, "__module__", "")
        if "stub" in module:
            logger.critical(
                "pydantic_core.stub_detected",
                component="startup",
                detail=(
                    "pydantic-core compiled Rust extension is NOT loaded. "
                    "Field constraints (min_length, pattern, ge/le) are "
                    "silently ignored on all Pydantic models. "
                    "Manual HTTPException(422) guards must cover all critical "
                    "validation paths. "
                    "Root cause: installed wheel is for macOS/darwin; "
                    "reinstall with a linux-aarch64 wheel to fix."
                ),
            )
        else:
            logger.info("pydantic_core.extension_loaded", module=module)
    except Exception as exc:  # pragma: no cover
        logger.error(
            "pydantic_core.check_failed",
            error=str(exc),
            exc_info=True,
        )


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Application lifespan manager.

    Logs startup and shutdown events so infrastructure can monitor the API
    process lifecycle. Also runs critical dependency checks on startup.
    """
    _check_pydantic_core()
    logger.info("api.startup", version="0.1.0")
    yield
    logger.info("api.shutdown")


# ---------------------------------------------------------------------------
# Application instance
# ---------------------------------------------------------------------------

app = FastAPI(
    title="FXLab Phase 3 API",
    description="Web UX and Governance API for FXLab trading platform",
    version="0.1.0",
    lifespan=lifespan,
)

# ---------------------------------------------------------------------------
# Register routers
# ---------------------------------------------------------------------------

app.include_router(runs.router)
app.include_router(readiness.router)
app.include_router(exports.router)          # M13-T4: Export stubs (zip bundles in M31)
app.include_router(research.router)         # M13-T4: Research stubs (M25/M26 will implement)
app.include_router(governance.router, prefix="/governance", tags=["governance"])  # M13-T4: Governance misc
app.include_router(charts.router)           # M7: Chart + LTTB + Queue Backend APIs
app.include_router(data_certification.router)  # M8: Certification Viewer
app.include_router(parity.router)           # M8: Parity Dashboard
app.include_router(promotions.router)
app.include_router(approvals.router, prefix="/approvals", tags=["approvals"])
app.include_router(overrides.router, prefix="/overrides", tags=["overrides"])  # M23: Override request/get
app.include_router(strategies.router, prefix="/strategies", tags=["strategies"])  # M23: Draft autosave
app.include_router(audit.router, prefix="/audit", tags=["audit"])
app.include_router(symbol_lineage.router, prefix="/symbols", tags=["symbol_lineage"])  # M9
app.include_router(observability.router)  # M11: Alerting + Observability Hardening
app.include_router(queues.router, prefix="/queues", tags=["queues"])
app.include_router(feed_health.router)
app.include_router(feeds.router)      # M6: Feed Registry + Versioned Config
app.include_router(artifacts.router)  # M5: Artifact Registry + Storage Abstraction

# ---------------------------------------------------------------------------
# CORS — read allowed origins from CORS_ALLOWED_ORIGINS env var.
# Defaults to localhost dev origins for local development.
#
# SECURITY NOTE: allow_origins=["*"] with allow_credentials=True is rejected
# by browsers (CORS spec §3.2.2 forbids wildcard + credentials). Production
# containers MUST set CORS_ALLOWED_ORIGINS to the actual frontend domain
# (e.g. "https://app.fxlab.example.com"). Multiple origins are
# comma-separated: "https://app.fxlab.example.com,https://beta.fxlab.example.com"
# ---------------------------------------------------------------------------
_cors_origins_raw: str = os.environ.get(
    "CORS_ALLOWED_ORIGINS",
    "http://localhost:3000,http://localhost:5173",
)
_cors_origins: list[str] = [o.strip() for o in _cors_origins_raw.split(",") if o.strip()]

app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type", "X-User-ID", "X-Correlation-ID"],
)

# ---------------------------------------------------------------------------
# M14-T1: Infrastructure hardening middleware stack
# Order (last-registered = outermost/runs first):
#   CorrelationIDMiddleware (runs first — must be outermost to set context)
#   BodySizeLimitMiddleware (size check before rate limiting)
#   RateLimitMiddleware (rate limit enforcement)
#   CORSMiddleware (already registered above)
# ---------------------------------------------------------------------------

app.add_middleware(RateLimitMiddleware)
app.add_middleware(BodySizeLimitMiddleware)
app.add_middleware(CorrelationIDMiddleware)

logger.info("fastapi_app_initialized")


# ---------------------------------------------------------------------------
# Response models
# ---------------------------------------------------------------------------

# Health status constants
HEALTH_STATUS_OK = "ok"
HEALTH_SERVICE_NAME = "fxlab-api"


class HealthCheckResponse(BaseModel):
    """
    Response model for all health check endpoints.

    Attributes:
        success: True if service is healthy.
        status: Canonical status string — always "ok" when healthy.
        version: API version string for diagnostics.
        service: Service identifier for multi-service deployments.
    """

    success: bool
    status: str
    version: str
    service: str


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@app.get("/", tags=["health"])
async def root() -> dict[str, str]:
    """
    Root endpoint providing API metadata.

    Returns:
        API title and version.
    """
    return {"title": "FXLab Phase 3 Web UX API", "version": API_VERSION}


@app.get("/health", tags=["health"])
async def health_check() -> HealthCheckResponse | dict:
    """
    Container orchestration health check endpoint with database probe.

    Returns a 200 OK response when the service is ready to accept traffic.
    Probes the database to verify connectivity; returns 503 if the database
    is unreachable.

    Used by Docker health checks, Kubernetes liveness/readiness probes,
    and load balancers.

    Returns:
        - 200 OK with HealthCheckResponse when database is reachable.
        - 503 Service Unavailable with degraded status when database is unreachable.
    """
    from services.api.db import check_db_connection
    from fastapi.responses import Response
    import json

    try:
        db_ok = check_db_connection()
        if db_ok:
            logger.info("health_check.success")
            return HealthCheckResponse(
                success=True,
                status=HEALTH_STATUS_OK,
                version=API_VERSION,
                service=HEALTH_SERVICE_NAME,
            )
        else:
            logger.warning("health_check.db_unreachable")
            return Response(
                content=json.dumps({
                    "success": False,
                    "status": "degraded",
                    "version": API_VERSION,
                    "service": HEALTH_SERVICE_NAME,
                }),
                status_code=503,
                media_type="application/json",
            )
    except Exception as exc:
        logger.warning("health_check.db_check_failed", error=str(exc), exc_info=True)
        return Response(
            content=json.dumps({
                "success": False,
                "status": "degraded",
                "version": API_VERSION,
                "service": HEALTH_SERVICE_NAME,
            }),
            status_code=503,
            media_type="application/json",
        )



# ---------------------------------------------------------------------------
# Service-layer stubs — imported by route handlers and mocked in tests.
# ---------------------------------------------------------------------------


class _AuditServiceStub:
    """
    Stub audit service.

    Real implementation will be injected via dependency injection once the
    audit infrastructure is wired.  Tests mock this object directly via
    ``patch("services.api.main.audit_service")``.
    """

    def log_event(self, **kwargs: Any) -> None:  # noqa: D102
        logger.debug("audit.log_event.stub", **kwargs)


def check_permission(
    requester_id: str,
    permission: Any = None,
    rbac_service: Any = None,
) -> bool:
    """
    Check whether the requester has permission for the requested action.

    Args:
        requester_id: ULID of the user making the request.
        permission: Optional ``libs.authz.interfaces.rbac.Permission`` enum
                    value specifying the action to check.  When provided
                    together with ``rbac_service``, the decision is delegated
                    to the service.
        rbac_service: Optional ``RBACInterface`` implementation.  When
                      provided, the permission decision is delegated to it
                      rather than using the fallback stub.

    Returns:
        True if permission is granted; False otherwise.

    Note:
        Falls back to returning True (permissive stub) when no
        ``rbac_service`` is supplied, preserving backward compatibility
        with route handlers that call this without RBAC context.
        Tests that need to enforce RBAC can supply a ``MockRBACService``
        via the ``rbac_service`` parameter.
        Tests that need to suppress access entirely use
        ``patch("services.api.main.check_permission", return_value=False)``.
    """
    if rbac_service is not None and permission is not None:
        return rbac_service.has_permission(requester_id, permission)
    # Backward-compatible stub — returns True when no RBAC service is wired.
    return True


def get_run_results(run_id: str) -> dict[str, Any] | None:
    """
    Retrieve results for a completed run.

    Args:
        run_id: ULID of the run.

    Returns:
        Dict of run results with basic structure, or None if the run does not
        exist.  Returns a default stub result so that the route can return 200
        in bootstrap tests that verify the route is registered.  Tests that
        need 404 behaviour mock this via
        ``patch("services.api.main.get_run_results")``.
    """
    logger.info("get_run_results.stub_called", run_id=run_id)
    # Return a default result so the endpoint returns 200 (not 404) for any
    # ULID in the bootstrap test.  The real implementation will query a DB.
    return {
        "run_id": run_id,
        "metrics": {},
        "artifacts": [],
    }


def get_readiness_report(run_id: str) -> dict[str, Any] | None:
    """
    Retrieve the readiness report for a run.

    Args:
        run_id: ULID of the run.

    Returns:
        Dict representing the readiness report with default structure, or None
        if not found.  Returns a default stub result so the route returns 200
        in bootstrap tests.  Tests that need 404 behaviour mock this via
        ``patch("services.api.main.get_readiness_report")``.
    """
    logger.info("get_readiness_report.stub_called", run_id=run_id)
    return {
        "run_id": run_id,
        "readiness_grade": "UNKNOWN",
        "blockers": [],
        "scoring_evidence": {},
    }


def submit_promotion_request(payload: Any) -> dict[str, str]:
    """
    Enqueue a promotion request for async processing.

    Args:
        payload: Validated PromotionRequest (or compatible dict).

    Returns:
        Dict with ``job_id`` (ULID string) and ``status`` ("pending").

    Note:
        Stub — real implementation enqueues a background job.
        Tests mock this via ``patch("services.api.main.submit_promotion_request")``.
    """
    logger.info("submit_promotion_request.stub_called")
    return {
        "job_id": "01HQ7X9Z8K3M4N5P6Q7R8S9T0X",
        "status": "pending",
    }


# Singleton audit service stub — replaced in tests via patch.
audit_service = _AuditServiceStub()

# ---------------------------------------------------------------------------
# Public API surface
# ---------------------------------------------------------------------------

__all__ = [
    "app",
    "audit_service",
    "check_permission",
    "get_readiness_report",
    "get_run_results",
    "submit_promotion_request",
]
