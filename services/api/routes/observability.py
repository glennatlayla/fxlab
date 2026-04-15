"""
Observability API endpoints (Phase 3 — M11: Alerting + Observability Hardening).

Purpose:
    Expose read-only HTTP endpoints that surface platform health and operational
    diagnostics to operators and monitoring systems.

Responsibilities:
    - GET /health/dependencies   — check reachability/health of all platform dependencies.
    - GET /health/diagnostics    — return platform-wide operational counts snapshot.
    - Provide get_dependency_health_repository() DI factory.
    - Provide get_diagnostics_repository() DI factory.
    - Serialize all response types via JSONResponse (LL-008).

Does NOT:
    - Perform connectivity checks directly (delegates to DependencyHealthRepositoryInterface).
    - Aggregate counts directly (delegates to DiagnosticsRepositoryInterface).
    - Contain classification or threshold logic.

Dependencies:
    - DependencyHealthRepositoryInterface (injected via Depends).
    - DiagnosticsRepositoryInterface (injected via Depends).
    - libs.contracts.observability: DependencyHealthRecord, DependencyHealthResponse,
      DiagnosticsSnapshot.

Error conditions:
    - No HTTP errors raised by these endpoints; both always return 200 when the
      repositories respond. Repository failures propagate as 500.

Known lessons:
    LL-007: DependencyHealthRecord.detail and overall_status are str="" (not Optional[str]).
    LL-008: All handlers use JSONResponse + dict; no response_model=.

Example:
    GET /health/dependencies
    → {"dependencies": [...], "overall_status": "OK", "generated_at": "..."}

    GET /health/diagnostics
    → {"queue_contention_count": 0, "feed_health_count": 0, ...}
"""

from __future__ import annotations

from typing import Any

import structlog
from fastapi import APIRouter, Depends, Header, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import ValidationError
from sqlalchemy.orm import Session

from libs.contracts.alertmanager_webhook import AlertmanagerWebhookPayload
from libs.contracts.interfaces.alert_ingest_service import (
    AlertIngestServiceError,
    AlertIngestServiceInterface,
)
from libs.contracts.interfaces.alert_notification_repository import (
    AlertNotificationRepositoryInterface,
)
from libs.contracts.interfaces.dependency_health_repository import (
    DependencyHealthRepositoryInterface,
)
from libs.contracts.interfaces.diagnostics_repository import (
    DiagnosticsRepositoryInterface,
)
from libs.contracts.observability import (
    DependencyHealthRecord,
    DependencyHealthResponse,
    DiagnosticsSnapshot,
)
from services.api.auth import AuthenticatedUser, get_current_user
from services.api.db import get_db

logger = structlog.get_logger(__name__)

router = APIRouter()


# ---------------------------------------------------------------------------
# Dependency injection factories
# ---------------------------------------------------------------------------


def get_dependency_health_repository() -> DependencyHealthRepositoryInterface:
    """
    Provide a DependencyHealthRepositoryInterface implementation.

    Always returns the real connectivity checker (not mocked).

    Returns:
        DependencyHealthRepositoryInterface implementation (real adapter).
    """
    from services.api.repositories.real_dependency_health_repository import (
        RealDependencyHealthRepository,
    )

    return RealDependencyHealthRepository()


def get_diagnostics_repository(db: Session = Depends(get_db)) -> DiagnosticsRepositoryInterface:
    """
    Provide a DiagnosticsRepositoryInterface implementation.

    Always returns the DB-backed repository bound to the current request's session.

    Args:
        db: SQLAlchemy session injected by FastAPI dependency injection.

    Returns:
        DiagnosticsRepositoryInterface implementation (SQL-backed).
    """
    from services.api.repositories.sql_diagnostics_repository import SqlDiagnosticsRepository

    return SqlDiagnosticsRepository(db=db)


def get_alert_notification_repository(
    db: Session = Depends(get_db),
) -> AlertNotificationRepositoryInterface:
    """
    Provide an AlertNotificationRepositoryInterface implementation.

    Returns the SQL-backed repository bound to the current request's
    session. Import is local so that route imports stay cheap and circular
    imports are avoided at module load.

    Args:
        db: SQLAlchemy session injected by FastAPI dependency injection.

    Returns:
        AlertNotificationRepositoryInterface (SQL-backed).
    """
    from services.api.repositories.sql_alert_notification_repository import (
        SqlAlertNotificationRepository,
    )

    return SqlAlertNotificationRepository(db=db)


def get_alert_ingest_service(
    repo: AlertNotificationRepositoryInterface = Depends(get_alert_notification_repository),
) -> AlertIngestServiceInterface:
    """
    Provide an AlertIngestServiceInterface implementation.

    Wires the default ``AlertIngestService`` with the request-scoped
    repository. ID and clock factories default to the production
    implementations (ULID + UTC clock).

    Args:
        repo: Request-scoped alert notification repository.

    Returns:
        AlertIngestServiceInterface.
    """
    from services.api.services.alert_ingest_service import AlertIngestService

    return AlertIngestService(repository=repo)


# ---------------------------------------------------------------------------
# Serialisation helpers
# ---------------------------------------------------------------------------


def _serialize_dep_record(record: DependencyHealthRecord) -> dict[str, Any]:
    """
    Serialize a DependencyHealthRecord to a JSON-safe dict.

    Args:
        record: The domain record to serialize.

    Returns:
        Dict with name, status (str), latency_ms, detail.

    Example:
        _serialize_dep_record(rec) == {"name": "database", "status": "OK", ...}
    """
    return {
        "name": record.name,
        "status": record.status.value,
        "latency_ms": record.latency_ms,
        "detail": record.detail,
    }


def _serialize_dep_health_response(resp: DependencyHealthResponse) -> dict[str, Any]:
    """
    Serialize a DependencyHealthResponse to a JSON-safe dict.

    Args:
        resp: The domain response to serialize.

    Returns:
        Dict with dependencies (list of serialized records), overall_status, generated_at.

    Example:
        _serialize_dep_health_response(resp)["overall_status"] == "OK"
    """
    return {
        "dependencies": [_serialize_dep_record(r) for r in resp.dependencies],
        "overall_status": resp.overall_status,
        "generated_at": resp.generated_at.isoformat(),
    }


def _serialize_diagnostics_snapshot(snap: DiagnosticsSnapshot) -> dict[str, Any]:
    """
    Serialize a DiagnosticsSnapshot to a JSON-safe dict.

    Args:
        snap: The domain snapshot to serialize.

    Returns:
        Dict with all four count fields and generated_at.

    Example:
        _serialize_diagnostics_snapshot(snap)["parity_critical_count"] == 0
    """
    return {
        "queue_contention_count": snap.queue_contention_count,
        "feed_health_count": snap.feed_health_count,
        "parity_critical_count": snap.parity_critical_count,
        "certification_blocked_count": snap.certification_blocked_count,
        "generated_at": snap.generated_at.isoformat(),
    }


# ---------------------------------------------------------------------------
# Route handlers
# ---------------------------------------------------------------------------


@router.get("/health/dependencies", tags=["observability"])
def get_dependency_health(
    x_correlation_id: str = Header(default="no-corr"),
    repo: DependencyHealthRepositoryInterface = Depends(get_dependency_health_repository),
    user: AuthenticatedUser = Depends(get_current_user),
) -> JSONResponse:
    """
    Check reachability and health of all platform dependencies.

    Returns a consolidated health status for: database, queues, artifact_store,
    feed_health_service. The overall_status reflects the worst individual status
    (DOWN > DEGRADED > OK).

    Args:
        x_correlation_id: Request-scoped tracing ID (from header).
        repo: DependencyHealthRepositoryInterface (injected).

    Returns:
        200 JSONResponse with dependencies list, overall_status, generated_at.

    Example:
        GET /health/dependencies
        → 200 {"dependencies": [...], "overall_status": "OK", "generated_at": "..."}
    """
    corr = x_correlation_id or "no-corr"
    logger.info(
        "health_dependencies.requested",
        operation="health_dependencies",
        correlation_id=corr,
        component="observability_router",
    )

    resp = repo.check(correlation_id=corr)
    body = _serialize_dep_health_response(resp)

    logger.info(
        "health_dependencies.completed",
        operation="health_dependencies",
        correlation_id=corr,
        component="observability_router",
        overall_status=body["overall_status"],
        dependency_count=len(body["dependencies"]),
        result="success",
    )
    return JSONResponse(content=body)


@router.get("/health/diagnostics", tags=["observability"])
def get_diagnostics(
    x_correlation_id: str = Header(default="no-corr"),
    repo: DiagnosticsRepositoryInterface = Depends(get_diagnostics_repository),
    user: AuthenticatedUser = Depends(get_current_user),
) -> JSONResponse:
    """
    Return platform-wide operational counts snapshot.

    Aggregates counts across queue contention, feed health, parity critical
    events, and certification blocked feeds so operators can spot systemic
    issues at a glance.

    Args:
        x_correlation_id: Request-scoped tracing ID (from header).
        repo: DiagnosticsRepositoryInterface (injected).

    Returns:
        200 JSONResponse with queue_contention_count, feed_health_count,
        parity_critical_count, certification_blocked_count, generated_at.

    Example:
        GET /health/diagnostics
        → 200 {"queue_contention_count": 0, "feed_health_count": 0, ...}
    """
    corr = x_correlation_id or "no-corr"
    logger.info(
        "health_diagnostics.requested",
        operation="health_diagnostics",
        correlation_id=corr,
        component="observability_router",
    )

    snap = repo.snapshot(correlation_id=corr)
    body = _serialize_diagnostics_snapshot(snap)

    logger.info(
        "health_diagnostics.completed",
        operation="health_diagnostics",
        correlation_id=corr,
        component="observability_router",
        parity_critical_count=snap.parity_critical_count,
        certification_blocked_count=snap.certification_blocked_count,
        result="success",
    )
    return JSONResponse(content=body)


# ---------------------------------------------------------------------------
# Alertmanager webhook receiver
# ---------------------------------------------------------------------------


@router.post("/observability/alert-webhook", tags=["observability"])
async def ingest_alertmanager_webhook(
    request: Request,
    x_correlation_id: str = Header(default="no-corr"),
    service: AlertIngestServiceInterface = Depends(get_alert_ingest_service),
) -> JSONResponse:
    """
    Receive an Alertmanager v4 webhook batch and persist every alert.

    This endpoint is the target of Alertmanager's ``default_webhook`` and
    ``critical_webhook`` receivers. It parses the batch, validates it
    against the Alertmanager v4 schema, hands off to the ingest service
    for persistence, and returns a small summary.

    Security model:
        The endpoint is unauthenticated because Alertmanager cannot be
        configured with bearer tokens in the same way downstream
        services can. The production deployment relies on network
        isolation — Alertmanager is only reachable on the internal Docker
        network (``fxlab-api:8000``) and the route is not exposed through
        the ingress. The body size, rate limit, and correlation-ID
        middleware defined in main.py still apply.

    Args:
        request: FastAPI request (used only to read the raw JSON body).
        x_correlation_id: Request-scoped tracing ID from header. If
            Alertmanager does not send one (it currently does not), the
            default ``"no-corr"`` is used and surfaced in logs.
        service: AlertIngestServiceInterface (injected).

    Returns:
        202 Accepted + JSON summary on success:
            {"received": int, "persisted": int,
             "correlation_id": str, "group_key": str}

    Raises:
        HTTPException(400): If the inbound JSON cannot be parsed or
            fails Alertmanager v4 schema validation.
        HTTPException(500): If persistence fails. The underlying cause
            is logged with exc_info; clients should retry because
            Alertmanager will re-send on non-2xx responses.

    Example:
        POST /observability/alert-webhook
        { "version": "4", "groupKey": "...", "alerts": [...] }
        → 202 {"received": 1, "persisted": 1, ...}
    """
    corr = x_correlation_id or "no-corr"
    logger.info(
        "alert_webhook.request_received",
        operation="alert_webhook",
        correlation_id=corr,
        component="observability_router",
    )

    # Parse + validate body. We manually read the body so we can return a
    # clean 400 on malformed JSON instead of a 422 with Pydantic's
    # default envelope.
    try:
        body = await request.json()
    except ValueError as exc:
        logger.warning(
            "alert_webhook.invalid_json",
            operation="alert_webhook",
            correlation_id=corr,
            component="observability_router",
            error=str(exc),
        )
        raise HTTPException(status_code=400, detail="Request body is not valid JSON") from exc

    try:
        payload = AlertmanagerWebhookPayload.model_validate(body)
    except ValidationError as exc:
        logger.warning(
            "alert_webhook.schema_violation",
            operation="alert_webhook",
            correlation_id=corr,
            component="observability_router",
            error=str(exc),
        )
        raise HTTPException(
            status_code=400,
            detail=f"Alertmanager payload failed schema validation: {exc.error_count()} error(s)",
        ) from exc

    try:
        result = service.ingest(payload, correlation_id=corr)
    except AlertIngestServiceError as exc:
        # We log the full cause but do not leak it to the client.
        logger.error(
            "alert_webhook.persist_failed",
            operation="alert_webhook",
            correlation_id=corr,
            component="observability_router",
            error=str(exc),
            exc_info=True,
        )
        raise HTTPException(
            status_code=500,
            detail="Failed to persist alert notifications",
        ) from exc

    logger.info(
        "alert_webhook.request_completed",
        operation="alert_webhook",
        correlation_id=corr,
        component="observability_router",
        received_count=result.received_count,
        persisted_count=result.persisted_count,
        group_key=result.group_key,
        result="success",
    )
    return JSONResponse(
        status_code=202,
        content={
            "received": result.received_count,
            "persisted": result.persisted_count,
            "correlation_id": result.correlation_id,
            "group_key": result.group_key,
        },
    )
