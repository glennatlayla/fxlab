"""
Audit Export and Retention Policy API endpoints (Phase 6 — M12).

Purpose:
    Provide HTTP endpoints for creating audit trail exports in multiple
    formats (JSON, CSV, NDJSON) and querying the data retention policy
    configuration.

Responsibilities:
    - POST /audit/export              — Create a new audit export job.
    - GET  /audit/export/{job_id}     — Retrieve export job metadata.
    - GET  /audit/export/{job_id}/content — Download raw export bytes.
    - GET  /audit/retention-policy    — Return current retention configuration.
    - Provide get_audit_export_service() DI factory for dependency injection.

Does NOT:
    - Execute retention policy (see RetentionService, scheduled job).
    - Format or compress exports (delegated to AuditExportService).
    - Access the database directly (uses injected service interface).

Dependencies:
    - AuditExportServiceInterface (injected via Depends).
    - AuditExportRequest, AuditExportResult, RetentionPolicyConfig contracts.
    - NotFoundError, ValidationError (domain exceptions → HTTP errors).

Error conditions:
    - POST /audit/export raises HTTP 422 when service raises ValidationError.
    - GET /audit/export/{job_id} raises HTTP 404 when NotFoundError.
    - GET /audit/export/{job_id}/content raises HTTP 404 when NotFoundError.

Example:
    POST /audit/export
    {"date_from": "2025-01-01T00:00:00Z", "date_to": "2025-12-31T23:59:59Z", "format": "csv"}

    GET /audit/export/01HQEXPORT0AAAAAAAAAAAAA

    GET /audit/retention-policy
"""

from __future__ import annotations

import structlog
from fastapi import APIRouter, Depends, Header, HTTPException
from fastapi.responses import JSONResponse, Response
from sqlalchemy.orm import Session

from libs.contracts.audit_export import AuditExportRequest
from libs.contracts.errors import NotFoundError, ValidationError
from services.api.auth import AuthenticatedUser, require_scope
from services.api.db import get_db
from services.api.services.interfaces.audit_export_service_interface import (
    AuditExportServiceInterface,
)

logger = structlog.get_logger(__name__)

router = APIRouter()


# ---------------------------------------------------------------------------
# Dependency injection provider
# ---------------------------------------------------------------------------


def get_audit_export_service(
    db: Session = Depends(get_db),
) -> AuditExportServiceInterface:
    """
    DI factory for AuditExportServiceInterface.

    Wires the production AuditExportService with a SQL-backed export
    repository (which uses the artifact storage backend for export
    content) and the SQL audit explorer repository for event queries.
    Override this in tests via ``app.dependency_overrides``.

    Args:
        db: SQLAlchemy session injected by FastAPI dependency injection.

    Returns:
        AuditExportServiceInterface implementation (production-wired).
    """
    # Deferred imports to avoid circular dependencies at module load
    from services.api.repositories.sql_audit_explorer_repository import (
        SqlAuditExplorerRepository,
    )
    from services.api.repositories.sql_audit_export_repository import (
        SqlAuditExportRepository,
    )
    from services.api.routes.artifacts import get_artifact_storage
    from services.api.services.audit_export_service import AuditExportService

    storage = get_artifact_storage()
    export_repo = SqlAuditExportRepository(db=db, storage=storage)
    explorer_repo = SqlAuditExplorerRepository(db=db)
    return AuditExportService(
        export_repo=export_repo,
        explorer_repo=explorer_repo,
    )


# ---------------------------------------------------------------------------
# Route handlers
# ---------------------------------------------------------------------------


@router.post("/export")
def create_export(
    request: AuditExportRequest,
    x_correlation_id: str = Header(default="no-corr"),
    service: AuditExportServiceInterface = Depends(get_audit_export_service),
    user: AuthenticatedUser = Depends(require_scope("exports:write")),
) -> JSONResponse:
    """
    Create a new audit trail export job.

    Accepts export parameters (date range, format, filters, compression),
    delegates to the AuditExportService, and returns job metadata including
    the SHA-256 content hash for tamper detection.

    Args:
        request: Validated AuditExportRequest body.
        x_correlation_id: Request-scoped tracing ID from HTTP header.
        service: Injected AuditExportServiceInterface.
        user: Authenticated user with exports:write scope.

    Returns:
        JSONResponse 200 with AuditExportResult fields.

    Raises:
        HTTPException 422: If the service raises ValidationError.

    Example:
        POST /audit/export
        {"date_from": "2025-01-01T00:00:00Z", "date_to": "2025-12-31T23:59:59Z"}
        → {"job_id": "...", "status": "completed", "record_count": 42, ...}
    """
    corr = x_correlation_id or "no-corr"
    logger.info(
        "audit_export.create_requested",
        operation="create_export",
        component="audit_export_router",
        correlation_id=corr,
        format=request.format.value,
        date_from=request.date_from.isoformat(),
        date_to=request.date_to.isoformat(),
        actor_filter=request.actor,
        action_type_filter=request.action_type,
        compress=request.compress,
        created_by=user.email,
    )

    try:
        result = service.create_export(request, created_by=user.email)
    except ValidationError as exc:
        logger.warning(
            "audit_export.validation_failed",
            operation="create_export",
            component="audit_export_router",
            correlation_id=corr,
            error=str(exc),
        )
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    logger.info(
        "audit_export.create_completed",
        operation="create_export",
        component="audit_export_router",
        correlation_id=corr,
        job_id=result.job_id,
        record_count=result.record_count,
        result="success",
    )

    return JSONResponse(content=result.model_dump(mode="json"))


@router.get("/export/{job_id}")
def get_export_result(
    job_id: str,
    x_correlation_id: str = Header(default="no-corr"),
    service: AuditExportServiceInterface = Depends(get_audit_export_service),
    user: AuthenticatedUser = Depends(require_scope("exports:read")),
) -> JSONResponse:
    """
    Retrieve export job metadata by job ID.

    Args:
        job_id: ULID of the export job.
        x_correlation_id: Request-scoped tracing ID.
        service: Injected AuditExportServiceInterface.
        user: Authenticated user with exports:read scope.

    Returns:
        JSONResponse 200 with AuditExportResult fields.

    Raises:
        HTTPException 404: If job_id is unknown.

    Example:
        GET /audit/export/01HQEXPORT0AAAAAAAAAAAAA
        → {"job_id": "...", "status": "completed", ...}
    """
    corr = x_correlation_id or "no-corr"
    logger.info(
        "audit_export.get_result_requested",
        operation="get_export_result",
        component="audit_export_router",
        correlation_id=corr,
        job_id=job_id,
    )

    try:
        result = service.get_export_result(job_id)
    except NotFoundError:
        logger.info(
            "audit_export.result_not_found",
            operation="get_export_result",
            component="audit_export_router",
            correlation_id=corr,
            job_id=job_id,
            result="not_found",
        )
        raise HTTPException(status_code=404, detail="Export job not found.") from None

    return JSONResponse(content=result.model_dump(mode="json"))


@router.get("/export/{job_id}/content")
def get_export_content(
    job_id: str,
    x_correlation_id: str = Header(default="no-corr"),
    service: AuditExportServiceInterface = Depends(get_audit_export_service),
    user: AuthenticatedUser = Depends(require_scope("exports:read")),
) -> Response:
    """
    Download the raw export content bytes.

    Returns the export file as an ``application/octet-stream`` response.
    The caller is responsible for decompressing if the export was gzip-compressed
    (check the export result's ``compressed`` field).

    Args:
        job_id: ULID of the export job.
        x_correlation_id: Request-scoped tracing ID.
        service: Injected AuditExportServiceInterface.
        user: Authenticated user with exports:read scope.

    Returns:
        Response 200 with raw bytes and ``application/octet-stream`` content type.

    Raises:
        HTTPException 404: If job_id is unknown or content unavailable.

    Example:
        GET /audit/export/01HQEXPORT0AAAAAAAAAAAAA/content
        → raw bytes
    """
    corr = x_correlation_id or "no-corr"
    logger.info(
        "audit_export.get_content_requested",
        operation="get_export_content",
        component="audit_export_router",
        correlation_id=corr,
        job_id=job_id,
    )

    try:
        content = service.get_export_content(job_id)
    except NotFoundError:
        logger.info(
            "audit_export.content_not_found",
            operation="get_export_content",
            component="audit_export_router",
            correlation_id=corr,
            job_id=job_id,
            result="not_found",
        )
        raise HTTPException(status_code=404, detail="Export content not found.") from None

    return Response(
        content=content,
        media_type="application/octet-stream",
    )


@router.get("/retention-policy")
def get_retention_policy(
    x_correlation_id: str = Header(default="no-corr"),
    service: AuditExportServiceInterface = Depends(get_audit_export_service),
    user: AuthenticatedUser = Depends(require_scope("exports:read")),
) -> JSONResponse:
    """
    Return the current data retention policy configuration.

    Returns per-entity-type retention periods including regulatory minimums,
    grace periods, and schedule metadata.

    Args:
        x_correlation_id: Request-scoped tracing ID.
        service: Injected AuditExportServiceInterface.
        user: Authenticated user with exports:read scope.

    Returns:
        JSONResponse 200 with RetentionPolicyConfig fields.

    Example:
        GET /audit/retention-policy
        → {"policies": [...], "last_run_at": null, "next_run_at": null}
    """
    corr = x_correlation_id or "no-corr"
    logger.info(
        "audit_export.retention_policy_requested",
        operation="get_retention_policy",
        component="audit_export_router",
        correlation_id=corr,
    )

    config = service.get_retention_policy()

    return JSONResponse(content=config.model_dump(mode="json"))
