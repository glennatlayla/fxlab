"""
Research run API routes.

Responsibilities:
- Expose research run lifecycle endpoints: submit, list, get detail,
  get result, cancel.
- Validate request payloads using Pydantic contracts.
- Delegate all business logic to ResearchRunService.
- Map domain errors to HTTP status codes.
- Enforce scope-based authorization.

Does NOT:
- Contain business logic or engine orchestration.
- Access the database directly.
- Manage engine lifecycle.

Dependencies:
- ResearchRunService (injected via module-level DI).
- libs.contracts.research_run: configs, records, DTOs.
- services.api.auth: require_scope for authorization.
- structlog for structured logging.

Error conditions:
- 401 Unauthorized: Missing or invalid authentication token.
- 403 Forbidden: Caller lacks required scope.
- 404 Not Found: run_id not found.
- 409 Conflict: run cannot be cancelled (invalid state transition).
- 422 Unprocessable Entity: invalid request payload.

Example:
    POST /research/runs
    {"config": {"run_type": "backtest", "strategy_id": "01H...", ...}}
    → 201 {"id": "01HRUN...", "status": "queued", ...}

    GET  /research/runs?strategy_id=01H...&limit=10&offset=0
    → 200 {"runs": [...], "total_count": 42}

    GET  /research/runs/{run_id}
    → 200 {"id": "01HRUN...", "status": "running", ...}

    GET  /research/runs/{run_id}/result
    → 200 {"summary_metrics": {...}, ...}

    DELETE /research/runs/{run_id}
    → 200 {"id": "01HRUN...", "status": "cancelled", ...}
"""

from __future__ import annotations

from typing import Any

import structlog
from fastapi import APIRouter, Depends, HTTPException, Path, Query, status
from fastapi.responses import JSONResponse

from libs.contracts.compact import ResearchRunCompact, ViewMode
from libs.contracts.errors import NotFoundError
from libs.contracts.interfaces.research_run_service import (
    ResearchRunServiceInterface,
)
from libs.contracts.research_run import (
    InvalidStatusTransitionError,
    SubmitResearchRunRequest,
)
from services.api.auth import AuthenticatedUser, require_scope
from services.api.middleware.correlation import correlation_id_var
from services.api.middleware.rate_limit import rate_limit

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/research", tags=["research"])


# ---------------------------------------------------------------------------
# Module-level DI for ResearchRunService
# ---------------------------------------------------------------------------

_research_run_service: ResearchRunServiceInterface | None = None


def set_research_run_service(service: ResearchRunServiceInterface) -> None:
    """
    Register the ResearchRunService instance for route injection.

    Called during application bootstrap or in test setup.

    Args:
        service: ResearchRunServiceInterface implementation.
    """
    global _research_run_service
    _research_run_service = service


def get_research_run_service() -> ResearchRunServiceInterface:
    """
    Retrieve the registered ResearchRunService.

    Returns:
        The registered ResearchRunServiceInterface implementation.

    Raises:
        HTTPException 503: If no service has been registered.
    """
    if _research_run_service is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Research run service not configured.",
        )
    return _research_run_service


# ---------------------------------------------------------------------------
# Helper: serialize a ResearchRunRecord to JSON-compatible dict
# ---------------------------------------------------------------------------


def _record_to_dict(record: Any) -> dict[str, Any]:
    """
    Serialize a ResearchRunRecord to a JSON-serializable dict.

    Uses Pydantic's model_dump with mode="json" for proper serialization
    of Decimal, datetime, and enum fields.

    Args:
        record: ResearchRunRecord instance.

    Returns:
        JSON-serializable dict.
    """
    return record.model_dump(mode="json")


# ---------------------------------------------------------------------------
# POST /research/runs — Submit a research run
# ---------------------------------------------------------------------------


@router.post(
    "/runs",
    status_code=status.HTTP_201_CREATED,
    summary="Submit a new research run",
)
async def submit_research_run(
    payload: SubmitResearchRunRequest,
    user: AuthenticatedUser = Depends(require_scope("operator:write")),
    service: ResearchRunServiceInterface = Depends(get_research_run_service),
    _rate_check: None = Depends(
        rate_limit(max_requests=5, window_seconds=60, scope="run_submission")
    ),
) -> JSONResponse:
    """
    Submit a new research run for execution.

    Creates a PENDING record and transitions to QUEUED for engine pickup.

    Args:
        payload: SubmitResearchRunRequest with run configuration.
        user: Authenticated user with operator:write scope.
        service: Injected ResearchRunService.

    Returns:
        201 JSONResponse with the created ResearchRunRecord.

    Example:
        POST /research/runs
        {"config": {"run_type": "backtest", "strategy_id": "01H...", ...}}
        → 201 {"id": "01HRUN...", "status": "queued", ...}
    """
    corr_id = correlation_id_var.get("no-corr")

    logger.info(
        "research.runs.submit.called",
        run_type=payload.config.run_type.value,
        strategy_id=payload.config.strategy_id,
        user_id=user.user_id,
        correlation_id=corr_id,
        component="research_routes",
    )

    record = service.submit_run(
        config=payload.config,
        user_id=user.user_id,
        correlation_id=corr_id,
    )

    logger.info(
        "research.runs.submit.completed",
        run_id=record.id,
        status=record.status.value,
        correlation_id=corr_id,
        component="research_routes",
    )

    return JSONResponse(
        content=_record_to_dict(record),
        status_code=status.HTTP_201_CREATED,
    )


# ---------------------------------------------------------------------------
# GET /research/runs — List research runs
# ---------------------------------------------------------------------------


@router.get(
    "/runs",
    summary="List research runs",
)
async def list_research_runs(
    strategy_id: str | None = Query(None, description="Filter by strategy ULID"),
    user_id: str | None = Query(None, description="Filter by user ULID"),
    limit: int = Query(50, ge=1, le=200, description="Page size"),
    offset: int = Query(0, ge=0, description="Page offset"),
    view: ViewMode = Query(ViewMode.FULL, description="Response detail level: 'full' or 'compact'"),
    user: AuthenticatedUser = Depends(require_scope("operator:read")),
    service: ResearchRunServiceInterface = Depends(get_research_run_service),
) -> JSONResponse:
    """
    List research runs with optional filtering, pagination, and view mode.

    At least one filter (strategy_id or user_id) should be provided.
    Without a filter, returns an empty result.

    Supports compact view for mobile clients: ?view=compact returns lightweight
    representations omitting nested config objects and large result arrays.

    Args:
        strategy_id: Optional filter by strategy ULID.
        user_id: Optional filter by user ULID.
        limit: Maximum results per page (1-200, default 50).
        offset: Number of results to skip.
        view: Response detail level ('full' for complete records, 'compact' for mobile).
        user: Authenticated user with operator:read scope.
        service: Injected ResearchRunService.

    Returns:
        200 JSONResponse with runs list and total_count.
        - If view=full: includes full ResearchRunRecord objects with config and result.
        - If view=compact: includes lightweight ResearchRunCompact objects.

    Example:
        GET /research/runs?strategy_id=01H...&view=compact
        → {"runs": [{"id": "01H...", "status": "completed", ...}], "total_count": 42}
    """
    corr_id = correlation_id_var.get("no-corr")

    records, total = service.list_runs(
        strategy_id=strategy_id,
        user_id=user_id,
        limit=limit,
        offset=offset,
    )

    logger.debug(
        "research.runs.list.completed",
        count=len(records),
        total=total,
        view_mode=view.value,
        correlation_id=corr_id,
        component="research_routes",
    )

    if view == ViewMode.COMPACT:
        runs_data = [ResearchRunCompact.from_full(r).model_dump(mode="json") for r in records]
    else:
        runs_data = [_record_to_dict(r) for r in records]

    return JSONResponse(
        content={
            "runs": runs_data,
            "total_count": total,
        }
    )


# ---------------------------------------------------------------------------
# GET /research/runs/{run_id} — Get run detail
# ---------------------------------------------------------------------------


@router.get(
    "/runs/{run_id}",
    summary="Get research run by ID",
)
async def get_research_run(
    run_id: str = Path(..., description="Research run ULID"),
    view: ViewMode = Query(ViewMode.FULL, description="Response detail level: 'full' or 'compact'"),
    user: AuthenticatedUser = Depends(require_scope("operator:read")),
    service: ResearchRunServiceInterface = Depends(get_research_run_service),
) -> JSONResponse:
    """
    Retrieve a research run by its ULID with optional compact view.

    Supports compact view for mobile clients: ?view=compact returns lightweight
    representation omitting nested config objects and result arrays.

    Args:
        run_id: ULID of the research run.
        view: Response detail level ('full' for complete record, 'compact' for mobile).
        user: Authenticated user with operator:read scope.
        service: Injected ResearchRunService.

    Returns:
        200 JSONResponse with the run record (full or compact).
        - If view=full: includes full ResearchRunRecord with config and result.
        - If view=compact: includes lightweight ResearchRunCompact representation.

    Raises:
        HTTPException 404: If run does not exist.

    Example:
        GET /research/runs/01HRUN...?view=compact
        → {"id": "01HRUN...", "status": "completed", ...}
    """
    corr_id = correlation_id_var.get("no-corr")

    record = service.get_run(run_id)
    if record is None:
        logger.warning(
            "research.runs.get.not_found",
            run_id=run_id,
            correlation_id=corr_id,
            component="research_routes",
        )
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Research run {run_id} not found",
        )

    logger.debug(
        "research.runs.get.completed",
        run_id=run_id,
        status=record.status.value,
        view_mode=view.value,
        correlation_id=corr_id,
        component="research_routes",
    )

    if view == ViewMode.COMPACT:
        content = ResearchRunCompact.from_full(record).model_dump(mode="json")
    else:
        content = _record_to_dict(record)

    return JSONResponse(content=content)


# ---------------------------------------------------------------------------
# GET /research/runs/{run_id}/result — Get run result
# ---------------------------------------------------------------------------


@router.get(
    "/runs/{run_id}/result",
    summary="Get research run result",
)
async def get_research_run_result(
    run_id: str = Path(..., description="Research run ULID"),
    user: AuthenticatedUser = Depends(require_scope("operator:read")),
    service: ResearchRunServiceInterface = Depends(get_research_run_service),
) -> JSONResponse:
    """
    Retrieve the result of a completed research run.

    Returns the engine result including summary metrics.

    Args:
        run_id: ULID of the research run.
        user: Authenticated user with operator:read scope.
        service: Injected ResearchRunService.

    Returns:
        200 JSONResponse with the run result.

    Raises:
        HTTPException 404: If run or result does not exist.
    """
    corr_id = correlation_id_var.get("no-corr")

    result = service.get_run_result(run_id)
    if result is None:
        logger.warning(
            "research.runs.result.not_found",
            run_id=run_id,
            correlation_id=corr_id,
            component="research_routes",
        )
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Result for research run {run_id} not found",
        )

    logger.debug(
        "research.runs.result.completed",
        run_id=run_id,
        correlation_id=corr_id,
        component="research_routes",
    )

    return JSONResponse(content=result.model_dump(mode="json"))


# ---------------------------------------------------------------------------
# DELETE /research/runs/{run_id} — Cancel a research run
# ---------------------------------------------------------------------------


@router.delete(
    "/runs/{run_id}",
    summary="Cancel a research run",
)
async def cancel_research_run(
    run_id: str = Path(..., description="Research run ULID"),
    user: AuthenticatedUser = Depends(require_scope("operator:write")),
    service: ResearchRunServiceInterface = Depends(get_research_run_service),
) -> JSONResponse:
    """
    Cancel a pending or queued research run.

    Only runs in PENDING or QUEUED status can be cancelled.
    RUNNING and terminal runs return 409 Conflict.

    Args:
        run_id: ULID of the research run to cancel.
        user: Authenticated user with operator:write scope.
        service: Injected ResearchRunService.

    Returns:
        200 JSONResponse with the cancelled run record.

    Raises:
        HTTPException 404: If run does not exist.
        HTTPException 409: If run is in a non-cancellable state.
    """
    corr_id = correlation_id_var.get("no-corr")

    logger.info(
        "research.runs.cancel.called",
        run_id=run_id,
        user_id=user.user_id,
        correlation_id=corr_id,
        component="research_routes",
    )

    try:
        record = service.cancel_run(run_id, correlation_id=corr_id)
    except NotFoundError:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Research run {run_id} not found",
        )
    except InvalidStatusTransitionError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"Cannot cancel run: {exc}",
        )

    logger.info(
        "research.runs.cancel.completed",
        run_id=run_id,
        correlation_id=corr_id,
        component="research_routes",
    )

    return JSONResponse(content=_record_to_dict(record))
