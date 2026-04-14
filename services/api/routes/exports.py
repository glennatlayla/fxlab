"""
Export API routes.

Responsibilities:
- Expose export job lifecycle endpoints: create, list, get detail, download.
- Validate request payloads using Pydantic contracts.
- Delegate all business logic to ExportService.
- Map domain errors to HTTP status codes.
- Enforce scope-based authorization.

Does NOT:
- Contain business logic or bundle generation.
- Access the database or artifact storage directly.
- Manage export job lifecycle.

Dependencies:
- ExportServiceInterface (injected via module-level DI).
- libs.contracts.export: ExportJobCreate, ExportJobResponse, ExportType, ExportStatus.
- services.api.auth: require_scope for authorization.
- structlog for structured logging.

Error conditions:
- 401 Unauthorized: Missing or invalid authentication token.
- 403 Forbidden: Caller lacks required scope.
- 404 Not Found: job_id not found or artifact not available.
- 422 Unprocessable Entity: invalid request payload.

Example:
    POST /exports
    {"export_type": "trades", "object_id": "01HRUN..."}
    → 201 {"id": "01HEXPORT...", "status": "complete", ...}

    GET  /exports?requested_by=01HUSER...&limit=10
    → 200 {"exports": [...], "total_count": 5}

    GET  /exports/{id}
    → 200 {"id": "01HEXPORT...", "status": "complete", ...}

    GET  /exports/{id}/download
    → 200 (binary zip content)
"""

from __future__ import annotations

import structlog
from fastapi import APIRouter, Depends, HTTPException, Path, Query, status
from fastapi.responses import JSONResponse, Response

from libs.contracts.errors import NotFoundError
from libs.contracts.export import ExportJobCreate
from services.api.auth import AuthenticatedUser, require_scope
from services.api.middleware.correlation import correlation_id_var
from services.api.services.interfaces.export_service_interface import (
    ExportServiceInterface,
)

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/exports", tags=["exports"])


# ---------------------------------------------------------------------------
# Module-level DI for ExportService
# ---------------------------------------------------------------------------

_export_service: ExportServiceInterface | None = None


def set_export_service(service: ExportServiceInterface) -> None:
    """
    Register the ExportService instance for route injection.

    Called during application bootstrap or in test setup.

    Args:
        service: ExportServiceInterface implementation.
    """
    global _export_service
    _export_service = service


def get_export_service() -> ExportServiceInterface:
    """
    Retrieve the registered ExportService.

    Returns:
        The registered ExportServiceInterface implementation.

    Raises:
        HTTPException 503: If no service has been registered.
    """
    if _export_service is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Export service not configured.",
        )
    return _export_service


# ---------------------------------------------------------------------------
# POST /exports — Create an export job
# ---------------------------------------------------------------------------


@router.post(
    "/",
    status_code=status.HTTP_201_CREATED,
    summary="Create a new export job",
)
async def create_export(
    payload: ExportJobCreate,
    user: AuthenticatedUser = Depends(require_scope("operator:write")),
    service: ExportServiceInterface = Depends(get_export_service),
) -> JSONResponse:
    """
    Create a new export job and generate the artifact bundle.

    The export is processed synchronously: the response returns a
    COMPLETE job with artifact_uri on success, or a FAILED job on error.

    Args:
        payload: ExportJobCreate with export_type and object_id.
        user: Authenticated user with operator:write scope.
        service: Injected ExportService.

    Returns:
        201 JSONResponse with the created ExportJobResponse.

    Example:
        POST /exports
        {"export_type": "trades", "object_id": "01HRUN..."}
        → 201 {"id": "01HEXPORT...", "status": "complete", ...}
    """
    corr_id = correlation_id_var.get("no-corr")

    logger.info(
        "exports.create.called",
        export_type=payload.export_type.value,
        object_id=payload.object_id,
        user_id=user.user_id,
        correlation_id=corr_id,
        component="export_routes",
    )

    job = service.create_export(
        export_type=payload.export_type,
        object_id=payload.object_id,
        requested_by=user.user_id,
        correlation_id=corr_id,
    )

    logger.info(
        "exports.create.completed",
        job_id=job.id,
        status=job.status.value,
        correlation_id=corr_id,
        component="export_routes",
    )

    return JSONResponse(
        content=job.model_dump(mode="json"),
        status_code=status.HTTP_201_CREATED,
    )


# ---------------------------------------------------------------------------
# GET /exports — List export jobs
# ---------------------------------------------------------------------------


@router.get(
    "/",
    summary="List export jobs",
)
async def list_exports(
    requested_by: str | None = Query(None, description="Filter by requesting user ULID"),
    object_id: str | None = Query(None, description="Filter by exported object ULID"),
    limit: int = Query(50, ge=1, le=200, description="Page size"),
    offset: int = Query(0, ge=0, description="Page offset"),
    user: AuthenticatedUser = Depends(require_scope("exports:read")),
    service: ExportServiceInterface = Depends(get_export_service),
) -> JSONResponse:
    """
    List export jobs with optional filtering and pagination.

    Args:
        requested_by: Optional filter by requesting user ULID.
        object_id: Optional filter by exported object ULID.
        limit: Maximum results per page (1-200, default 50).
        offset: Number of results to skip.
        user: Authenticated user with exports:read scope.
        service: Injected ExportService.

    Returns:
        200 JSONResponse with exports list and total_count.
    """
    corr_id = correlation_id_var.get("no-corr")

    exports, total = service.list_exports(
        requested_by=requested_by,
        object_id=object_id,
        limit=limit,
        offset=offset,
    )

    logger.debug(
        "exports.list.completed",
        count=len(exports),
        total=total,
        correlation_id=corr_id,
        component="export_routes",
    )

    return JSONResponse(
        content={
            "exports": [e.model_dump(mode="json") for e in exports],
            "total_count": total,
        }
    )


# ---------------------------------------------------------------------------
# GET /exports/{job_id} — Get export detail
# ---------------------------------------------------------------------------


@router.get(
    "/{job_id}",
    summary="Get export job by ID",
)
async def get_export(
    job_id: str = Path(..., description="Export job ULID"),
    user: AuthenticatedUser = Depends(require_scope("exports:read")),
    service: ExportServiceInterface = Depends(get_export_service),
) -> JSONResponse:
    """
    Retrieve an export job by its ULID.

    Args:
        job_id: ULID of the export job.
        user: Authenticated user with exports:read scope.
        service: Injected ExportService.

    Returns:
        200 JSONResponse with the export job.

    Raises:
        HTTPException 404: If job does not exist.
    """
    corr_id = correlation_id_var.get("no-corr")

    job = service.get_export(job_id)
    if job is None:
        logger.warning(
            "exports.get.not_found",
            job_id=job_id,
            correlation_id=corr_id,
            component="export_routes",
        )
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Export job {job_id} not found",
        )

    logger.debug(
        "exports.get.completed",
        job_id=job_id,
        status=job.status.value,
        correlation_id=corr_id,
        component="export_routes",
    )

    return JSONResponse(content=job.model_dump(mode="json"))


# ---------------------------------------------------------------------------
# GET /exports/{job_id}/download — Download export artifact
# ---------------------------------------------------------------------------


@router.get(
    "/{job_id}/download",
    summary="Download export artifact",
)
async def download_export(
    job_id: str = Path(..., description="Export job ULID"),
    user: AuthenticatedUser = Depends(require_scope("exports:read")),
    service: ExportServiceInterface = Depends(get_export_service),
) -> Response:
    """
    Download the completed export artifact as a zip file.

    Streams the binary zip content with appropriate Content-Type
    and Content-Disposition headers.

    Args:
        job_id: ULID of the export job.
        user: Authenticated user with exports:read scope.
        service: Injected ExportService.

    Returns:
        200 Response with binary zip content.

    Raises:
        HTTPException 404: If job not found or not yet complete.
    """
    corr_id = correlation_id_var.get("no-corr")

    logger.info(
        "exports.download.called",
        job_id=job_id,
        user_id=user.user_id,
        correlation_id=corr_id,
        component="export_routes",
    )

    try:
        data = service.download_export(job_id, correlation_id=corr_id)
    except NotFoundError as exc:
        logger.warning(
            "exports.download.not_found",
            job_id=job_id,
            error=str(exc),
            correlation_id=corr_id,
            component="export_routes",
        )
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=str(exc),
        )
    except FileNotFoundError as exc:
        logger.error(
            "exports.download.artifact_missing",
            job_id=job_id,
            error=str(exc),
            correlation_id=corr_id,
            component="export_routes",
        )
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Export artifact for job {job_id} not found in storage",
        )

    logger.info(
        "exports.download.completed",
        job_id=job_id,
        byte_size=len(data),
        correlation_id=corr_id,
        component="export_routes",
    )

    return Response(
        content=data,
        media_type="application/zip",
        headers={
            "Content-Disposition": f'attachment; filename="{job_id}.zip"',
            "Content-Length": str(len(data)),
        },
    )
