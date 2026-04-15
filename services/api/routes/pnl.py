"""
P&L attribution and performance tracking API endpoints.

Responsibilities:
- Expose endpoints for P&L summary, timeseries, attribution, and comparison.
- Validate request parameters and query strings.
- Delegate all business logic to PnlAttributionService.
- Map domain errors to HTTP status codes.
- Enforce deployments:read scope on all endpoints.

Does NOT:
- Contain business logic or P&L calculations.
- Access the database directly.
- Manage broker lifecycle.

Dependencies:
- PnlAttributionServiceInterface (injected via module-level DI).
- services.api.auth: require_scope("deployments:read").
- structlog for structured logging.

Error conditions:
- 401 Unauthorized: Missing or invalid authentication token.
- 403 Forbidden: Caller lacks deployments:read scope.
- 404 Not Found: deployment_id does not exist.
- 422 Unprocessable Entity: invalid query parameters (date range, granularity).
- 500 Internal Server Error: unexpected service failure.

Example:
    GET  /pnl/{deployment_id}/summary         -> 200 (P&L summary)
    GET  /pnl/{deployment_id}/timeseries      -> 200 (timeseries data)
    GET  /pnl/{deployment_id}/attribution      -> 200 (per-symbol attribution)
    GET  /pnl/comparison?deployment_ids=X,Y   -> 200 (strategy comparison)
    POST /pnl/{deployment_id}/snapshot         -> 201 (snapshot persisted)
"""

from __future__ import annotations

from datetime import date

import structlog
from fastapi import APIRouter, Depends, HTTPException, Path, Query, status
from fastapi.responses import JSONResponse

from libs.contracts.errors import NotFoundError, ValidationError
from services.api.auth import AuthenticatedUser, require_scope
from services.api.middleware.correlation import correlation_id_var
from services.api.services.interfaces.pnl_attribution_service_interface import (
    PnlAttributionServiceInterface,
)

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/pnl", tags=["pnl"])


# ---------------------------------------------------------------------------
# Module-level dependency injection
# ---------------------------------------------------------------------------

_pnl_service: PnlAttributionServiceInterface | None = None


def set_pnl_attribution_service(
    service: PnlAttributionServiceInterface | None,
) -> None:
    """
    Wire the PnlAttributionService instance for P&L routes.

    Called at app startup to inject the service dependency.

    Args:
        service: PnlAttributionService instance, or None to reset.
    """
    global _pnl_service
    _pnl_service = service


def get_pnl_attribution_service() -> PnlAttributionServiceInterface:
    """
    FastAPI dependency: return the wired PnlAttributionService.

    Raises:
        HTTPException(503): If the service has not been configured.
    """
    if _pnl_service is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="P&L attribution service not configured.",
        )
    return _pnl_service


# ---------------------------------------------------------------------------
# GET /pnl/{deployment_id}/summary
# ---------------------------------------------------------------------------


@router.get(
    "/{deployment_id}/summary",
    summary="Get P&L summary for a deployment",
    status_code=status.HTTP_200_OK,
)
async def get_pnl_summary(
    deployment_id: str = Path(
        ...,
        description="Deployment ULID",
        min_length=1,
    ),
    user: AuthenticatedUser = Depends(require_scope("deployments:read")),
    service: PnlAttributionServiceInterface = Depends(get_pnl_attribution_service),
) -> JSONResponse:
    """
    Get aggregate P&L summary for a deployment.

    Returns realized/unrealized P&L, commissions, win rate, Sharpe ratio,
    max drawdown, and trade statistics.

    Returns:
        200: PnlSummary as JSON.

    Raises:
        404: Deployment not found.
    """
    corr_id = correlation_id_var.get("no-corr")
    logger.info(
        "pnl.summary.requested",
        deployment_id=deployment_id,
        user_id=user.user_id,
        correlation_id=corr_id,
        component="pnl_routes",
    )

    try:
        result = service.get_pnl_summary(deployment_id=deployment_id)
        return JSONResponse(status_code=200, content=result)
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        logger.error(
            "pnl.summary.error",
            deployment_id=deployment_id,
            error=str(exc),
            exc_info=True,
            component="pnl_routes",
        )
        raise HTTPException(
            status_code=500,
            detail="Internal server error",
        ) from exc


# ---------------------------------------------------------------------------
# GET /pnl/{deployment_id}/timeseries
# ---------------------------------------------------------------------------


@router.get(
    "/{deployment_id}/timeseries",
    summary="Get P&L timeseries for a deployment",
    status_code=status.HTTP_200_OK,
)
async def get_pnl_timeseries(
    deployment_id: str = Path(
        ...,
        description="Deployment ULID",
        min_length=1,
    ),
    date_from: str = Query(
        ...,
        description="Start date (YYYY-MM-DD, inclusive)",
    ),
    date_to: str = Query(
        ...,
        description="End date (YYYY-MM-DD, inclusive)",
    ),
    granularity: str = Query(
        default="daily",
        description="Aggregation: daily, weekly, or monthly",
    ),
    user: AuthenticatedUser = Depends(require_scope("deployments:read")),
    service: PnlAttributionServiceInterface = Depends(get_pnl_attribution_service),
) -> JSONResponse:
    """
    Get P&L timeseries data for equity curve rendering.

    Returns data points with cumulative P&L, daily change, and drawdown.

    Returns:
        200: List of PnlTimeseriesPoint as JSON.

    Raises:
        404: Deployment not found.
        422: Invalid date range or granularity.
    """
    corr_id = correlation_id_var.get("no-corr")
    logger.info(
        "pnl.timeseries.requested",
        deployment_id=deployment_id,
        date_from=date_from,
        date_to=date_to,
        granularity=granularity,
        user_id=user.user_id,
        correlation_id=corr_id,
        component="pnl_routes",
    )

    # Parse dates
    try:
        parsed_from = date.fromisoformat(date_from)
        parsed_to = date.fromisoformat(date_to)
    except ValueError as exc:
        raise HTTPException(
            status_code=422,
            detail=f"Invalid date format: {exc}. Use YYYY-MM-DD.",
        ) from exc

    try:
        result = service.get_pnl_timeseries(
            deployment_id=deployment_id,
            date_from=parsed_from,
            date_to=parsed_to,
            granularity=granularity,
        )
        return JSONResponse(status_code=200, content=result)
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        logger.error(
            "pnl.timeseries.error",
            deployment_id=deployment_id,
            error=str(exc),
            exc_info=True,
            component="pnl_routes",
        )
        raise HTTPException(
            status_code=500,
            detail="Internal server error",
        ) from exc


# ---------------------------------------------------------------------------
# GET /pnl/{deployment_id}/attribution
# ---------------------------------------------------------------------------


@router.get(
    "/{deployment_id}/attribution",
    summary="Get per-symbol P&L attribution",
    status_code=status.HTTP_200_OK,
)
async def get_pnl_attribution(
    deployment_id: str = Path(
        ...,
        description="Deployment ULID",
        min_length=1,
    ),
    date_from: str | None = Query(
        default=None,
        description="Optional start date (YYYY-MM-DD)",
    ),
    date_to: str | None = Query(
        default=None,
        description="Optional end date (YYYY-MM-DD)",
    ),
    user: AuthenticatedUser = Depends(require_scope("deployments:read")),
    service: PnlAttributionServiceInterface = Depends(get_pnl_attribution_service),
) -> JSONResponse:
    """
    Get per-symbol P&L attribution for a deployment.

    Shows which instruments contribute most to the strategy's returns.

    Returns:
        200: PnlAttributionReport as JSON.

    Raises:
        404: Deployment not found.
    """
    corr_id = correlation_id_var.get("no-corr")
    logger.info(
        "pnl.attribution.requested",
        deployment_id=deployment_id,
        user_id=user.user_id,
        correlation_id=corr_id,
        component="pnl_routes",
    )

    # Parse optional dates
    parsed_from: date | None = None
    parsed_to: date | None = None
    try:
        if date_from:
            parsed_from = date.fromisoformat(date_from)
        if date_to:
            parsed_to = date.fromisoformat(date_to)
    except ValueError as exc:
        raise HTTPException(
            status_code=422,
            detail=f"Invalid date format: {exc}. Use YYYY-MM-DD.",
        ) from exc

    try:
        result = service.get_attribution(
            deployment_id=deployment_id,
            date_from=parsed_from,
            date_to=parsed_to,
        )
        return JSONResponse(status_code=200, content=result)
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        logger.error(
            "pnl.attribution.error",
            deployment_id=deployment_id,
            error=str(exc),
            exc_info=True,
            component="pnl_routes",
        )
        raise HTTPException(
            status_code=500,
            detail="Internal server error",
        ) from exc


# ---------------------------------------------------------------------------
# GET /pnl/comparison
# ---------------------------------------------------------------------------


@router.get(
    "/comparison",
    summary="Compare P&L across multiple deployments",
    status_code=status.HTTP_200_OK,
)
async def get_pnl_comparison(
    deployment_ids: str = Query(
        ...,
        description="Comma-separated deployment ULIDs",
    ),
    date_from: str | None = Query(
        default=None,
        description="Optional start date (YYYY-MM-DD)",
    ),
    date_to: str | None = Query(
        default=None,
        description="Optional end date (YYYY-MM-DD)",
    ),
    user: AuthenticatedUser = Depends(require_scope("deployments:read")),
    service: PnlAttributionServiceInterface = Depends(get_pnl_attribution_service),
) -> JSONResponse:
    """
    Compare P&L metrics across multiple deployments.

    Accepts deployment_ids as comma-separated string for GET-friendly URLs.

    Returns:
        200: PnlComparisonReport as JSON.

    Raises:
        422: Empty deployment_ids or invalid dates.
    """
    corr_id = correlation_id_var.get("no-corr")

    # Parse deployment IDs
    ids_list = [d.strip() for d in deployment_ids.split(",") if d.strip()]

    logger.info(
        "pnl.comparison.requested",
        deployment_count=len(ids_list),
        user_id=user.user_id,
        correlation_id=corr_id,
        component="pnl_routes",
    )

    if not ids_list:
        raise HTTPException(
            status_code=422,
            detail="deployment_ids must contain at least one ULID.",
        )

    # Parse optional dates
    parsed_from: date | None = None
    parsed_to: date | None = None
    try:
        if date_from:
            parsed_from = date.fromisoformat(date_from)
        if date_to:
            parsed_to = date.fromisoformat(date_to)
    except ValueError as exc:
        raise HTTPException(
            status_code=422,
            detail=f"Invalid date format: {exc}. Use YYYY-MM-DD.",
        ) from exc

    try:
        result = service.get_comparison(
            deployment_ids=ids_list,
            date_from=parsed_from,
            date_to=parsed_to,
        )
        return JSONResponse(status_code=200, content=result)
    except ValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:
        logger.error(
            "pnl.comparison.error",
            error=str(exc),
            exc_info=True,
            component="pnl_routes",
        )
        raise HTTPException(
            status_code=500,
            detail="Internal server error",
        ) from exc


# ---------------------------------------------------------------------------
# POST /pnl/{deployment_id}/snapshot
# ---------------------------------------------------------------------------


@router.post(
    "/{deployment_id}/snapshot",
    summary="Take a daily P&L snapshot",
    status_code=status.HTTP_201_CREATED,
)
async def take_pnl_snapshot(
    deployment_id: str = Path(
        ...,
        description="Deployment ULID",
        min_length=1,
    ),
    snapshot_date: str = Query(
        ...,
        description="Snapshot date (YYYY-MM-DD)",
    ),
    user: AuthenticatedUser = Depends(require_scope("deployments:read")),
    service: PnlAttributionServiceInterface = Depends(get_pnl_attribution_service),
) -> JSONResponse:
    """
    Persist a daily P&L snapshot for a deployment.

    Uses upsert semantics — calling twice for the same date updates the
    existing record.

    Returns:
        201: Persisted PnlSnapshot as JSON.

    Raises:
        404: Deployment not found.
        422: Invalid date format.
    """
    corr_id = correlation_id_var.get("no-corr")
    logger.info(
        "pnl.snapshot.requested",
        deployment_id=deployment_id,
        snapshot_date=snapshot_date,
        user_id=user.user_id,
        correlation_id=corr_id,
        component="pnl_routes",
    )

    try:
        parsed_date = date.fromisoformat(snapshot_date)
    except ValueError as exc:
        raise HTTPException(
            status_code=422,
            detail=f"Invalid date format: {exc}. Use YYYY-MM-DD.",
        ) from exc

    try:
        result = service.take_snapshot(
            deployment_id=deployment_id,
            snapshot_date=parsed_date,
        )
        return JSONResponse(status_code=201, content=result)
    except NotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except Exception as exc:
        logger.error(
            "pnl.snapshot.error",
            deployment_id=deployment_id,
            error=str(exc),
            exc_info=True,
            component="pnl_routes",
        )
        raise HTTPException(
            status_code=500,
            detail="Internal server error",
        ) from exc
