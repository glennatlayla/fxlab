"""
Routes for /runs endpoints.
Thin handlers - no business logic.
"""

from __future__ import annotations

import re
from typing import Any

import structlog
from fastapi import APIRouter, Depends, HTTPException, Path, Query, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from libs.contracts.errors import NotFoundError
from libs.contracts.experiment_plan import ExperimentPlan
from libs.contracts.run_results import (
    DEFAULT_BLOTTER_PAGE_SIZE,
    MAX_BLOTTER_PAGE_SIZE,
    EquityCurveResponse,
    RunMetrics,
    TradeBlotterPage,
)
from libs.strategy_ir.interfaces.dataset_resolver_interface import (
    DatasetNotFoundError,
    DatasetResolverInterface,
)
from services.api.auth import AuthenticatedUser, require_scope
from services.api.middleware.correlation import correlation_id_var
from services.api.services.research_run_service import RunNotCompletedError

logger = structlog.get_logger()

router = APIRouter(prefix="/runs", tags=["runs"])

# ULID format: 26 alphanumeric characters (Crockford's Base32)
ULID_PATTERN = re.compile(r"^[0-9A-HJKMNP-TV-Z]{26}$", re.IGNORECASE)


def is_valid_ulid(value: str) -> bool:
    """Validate ULID format."""
    return bool(ULID_PATTERN.match(value))


# ===========================================================================
# M2.C2: POST /runs/from-ir
# ---------------------------------------------------------------------------
# This block (request model, DI helpers, handler) is owned by M2.C2.
# A sibling tranche M2.C3 will append GET /runs/{id}/results/* handlers
# BELOW this block to avoid merge conflict. Do not interleave.
# ===========================================================================


class _FromIrRequest(BaseModel):
    """
    Request body for ``POST /runs/from-ir``.

    Strict + frozen so any future drift on the wire surfaces as a
    400-level error rather than being silently ignored. Mirrors the
    bar set by :class:`libs.contracts.strategy_ir.StrategyIR` and
    :class:`libs.contracts.experiment_plan.ExperimentPlan`.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    strategy_id: str = Field(..., min_length=1, description="Strategy ULID")
    experiment_plan: ExperimentPlan


# ---------------------------------------------------------------------------
# Module-level DI for ResearchRunService and DatasetResolver
# ---------------------------------------------------------------------------

# These are populated at app bootstrap (or in test fixtures) via the
# ``set_*`` helpers below. The route uses Depends() to fetch them so
# unit tests can inject mocks per request.

from services.api.services.research_run_service import ResearchRunService  # noqa: E402

_research_run_service: ResearchRunService | None = None
_dataset_resolver: DatasetResolverInterface | None = None


def set_research_run_service(service: ResearchRunService) -> None:
    """
    Register the :class:`ResearchRunService` instance for route
    injection.

    Called during application bootstrap or in test setup.

    Args:
        service: Concrete :class:`ResearchRunService` instance (the
            ``submit_from_ir`` method is not part of the abstract
            :class:`ResearchRunServiceInterface`, so we pin the
            concrete type here).
    """
    global _research_run_service
    _research_run_service = service


def set_dataset_resolver(resolver: DatasetResolverInterface) -> None:
    """
    Register the :class:`DatasetResolverInterface` instance for route
    injection.

    M2.C2 wires :class:`InMemoryDatasetResolver`; M4.E3 will swap in
    the catalog-backed :class:`DatasetService` without touching this
    file.

    Args:
        resolver: Any :class:`DatasetResolverInterface` implementation.
    """
    global _dataset_resolver
    _dataset_resolver = resolver


def get_research_run_service() -> ResearchRunService:
    """
    Retrieve the registered :class:`ResearchRunService`.

    Returns:
        The registered service instance.

    Raises:
        HTTPException 503: If no service has been registered.
    """
    if _research_run_service is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Research run service not configured.",
        )
    return _research_run_service


def get_dataset_resolver() -> DatasetResolverInterface:
    """
    Retrieve the registered :class:`DatasetResolverInterface`.

    Returns:
        The registered resolver instance.

    Raises:
        HTTPException 503: If no resolver has been registered.
    """
    if _dataset_resolver is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Dataset resolver not configured.",
        )
    return _dataset_resolver


# ---------------------------------------------------------------------------
# POST /runs/from-ir
# ---------------------------------------------------------------------------


@router.post(
    "/from-ir",
    status_code=status.HTTP_201_CREATED,
    summary="Submit a research run derived from an experiment plan",
)
async def submit_run_from_ir(
    payload: _FromIrRequest,
    defer_execution: int = Query(
        default=0,
        ge=0,
        le=1,
        description=(
            "When 1, queue the run only (legacy M2.C2 behaviour) instead of "
            "executing the synthetic backtest synchronously. Defaults to 0 "
            "so the M2.C3 GET /runs/{id}/results/* endpoints return real "
            "data immediately after this call."
        ),
    ),
    user: AuthenticatedUser = Depends(require_scope("runs:write")),
    service: ResearchRunService = Depends(get_research_run_service),
    resolver: DatasetResolverInterface = Depends(get_dataset_resolver),
) -> JSONResponse:
    """
    Submit a new research run from a parsed experiment plan.

    Flow:
        1. Validate the request body (handled by Pydantic).
        2. Resolve ``experiment_plan.data_selection.dataset_ref`` via
           the injected :class:`DatasetResolverInterface`. Missing
           refs raise 404.
        3. Delegate to
           :meth:`ResearchRunService.submit_from_ir` which builds the
           :class:`ResearchRunConfig` and queues the run.
        4. Return ``201 Created`` with the new ``run_id`` and the
           full record body for callers that want to poll status
           immediately.

    Args:
        payload: Request body with ``strategy_id`` + ``experiment_plan``.
        user: Authenticated user with ``runs:write`` scope.
        service: Injected :class:`ResearchRunService`.
        resolver: Injected :class:`DatasetResolverInterface`.

    Returns:
        201 :class:`JSONResponse` with the created research-run
        record. The ``run_id`` field at the top of the body matches
        ``id`` for backward compatibility with any callers expecting
        a flat shape.

    Raises:
        HTTPException 404: If ``dataset_ref`` is unknown to the
            resolver.
        HTTPException 422: If the experiment plan fails Pydantic
            validation (FastAPI handles this automatically before
            this body runs).
    """
    corr_id = correlation_id_var.get("no-corr")

    logger.info(
        "runs.from_ir.entry",
        strategy_id=payload.strategy_id,
        dataset_ref=payload.experiment_plan.data_selection.dataset_ref,
        plan_strategy_name=payload.experiment_plan.strategy_ref.strategy_name,
        user_id=user.user_id,
        correlation_id=corr_id,
        component="runs",
    )

    # Step 1: resolve the dataset_ref. A miss is a caller error (typo
    # in plan or unregistered dataset), so we surface 404 with the
    # original ref so the client can correct it.
    try:
        resolved = resolver.resolve(payload.experiment_plan.data_selection.dataset_ref)
    except DatasetNotFoundError as exc:
        logger.warning(
            "runs.from_ir.dataset_not_found",
            dataset_ref=exc.dataset_ref,
            correlation_id=corr_id,
            component="runs",
        )
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Dataset reference not found: {exc.dataset_ref}",
        ) from exc

    # Step 2: hand off to the service. ResearchRunConfig validation
    # surfaces here as Pydantic ValidationError -- map to 422 so
    # the wire shape matches FastAPI's other validation responses.
    # auto_execute defaults to True so the M2.C3 GET endpoints return
    # real blotter / equity / metrics data immediately. ?defer_execution=1
    # opts out for callers that want to dispatch execution themselves.
    try:
        record = service.submit_from_ir(
            strategy_id=payload.strategy_id,
            experiment_plan=payload.experiment_plan,
            resolved_dataset=resolved,
            user_id=user.user_id,
            correlation_id=corr_id,
            auto_execute=defer_execution == 0,
        )
    except ValidationError as exc:
        logger.warning(
            "runs.from_ir.config_validation_failed",
            strategy_id=payload.strategy_id,
            correlation_id=corr_id,
            component="runs",
            error=str(exc),
        )
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Invalid run config derived from experiment plan: {exc}",
        ) from exc
    except Exception as exc:
        # Auto-execute can raise FXLabError (or any other) when the
        # executor fails. The service has already persisted FAILED on
        # the run row before re-raising; we surface 500 with the message
        # so the caller can decide whether to retry, re-queue, or drop.
        logger.error(
            "runs.from_ir.execution_failed",
            strategy_id=payload.strategy_id,
            correlation_id=corr_id,
            component="runs",
            error=str(exc),
            exc_info=True,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Backtest execution failed: {exc}",
        ) from exc

    logger.info(
        "runs.from_ir.success",
        run_id=record.id,
        strategy_id=payload.strategy_id,
        status=record.status.value,
        correlation_id=corr_id,
        component="runs",
    )

    body: dict[str, Any] = record.model_dump(mode="json")
    body["run_id"] = record.id
    return JSONResponse(content=body, status_code=status.HTTP_201_CREATED)


# ===========================================================================
# M2.C3 SLOT: GET /runs/{run_id}/results/* handlers go BELOW this line.
# Sibling tranche M2.C3 owns the section below; M2.C2 owns the section above.
# ===========================================================================


@router.get("/{run_id}/results")
async def get_run_results_endpoint(
    run_id: str = Path(..., description="Run ULID"),
    user: AuthenticatedUser = Depends(require_scope("exports:read")),
) -> dict[str, Any]:
    """
    Retrieve results for a completed run.

    Returns:
        Run results with metrics and artifacts

    Raises:
        HTTPException: 400 for invalid ULID format, 404 if run not found
    """
    corr_id = correlation_id_var.get("no-corr")
    logger.info("get_run_results.entry", run_id=run_id, correlation_id=corr_id, component="runs")

    # Validate ULID format
    if not is_valid_ulid(run_id):
        logger.warning(
            "get_run_results.invalid_ulid", run_id=run_id, correlation_id=corr_id, component="runs"
        )
        raise HTTPException(status_code=422, detail="Invalid ULID format")

    # Import here to allow mocking in tests
    from services.api.main import get_run_results

    # Retrieve results — surface service errors as 500
    try:
        results = get_run_results(run_id)
    except Exception as exc:
        logger.error(
            "get_run_results.error",
            run_id=run_id,
            error=str(exc),
            exc_info=True,
            correlation_id=corr_id,
            component="runs",
        )
        raise HTTPException(status_code=500, detail="Internal server error")

    if results is None:
        logger.warning(
            "get_run_results.not_found", run_id=run_id, correlation_id=corr_id, component="runs"
        )
        raise HTTPException(status_code=404, detail="Run not found")

    logger.info("get_run_results.success", run_id=run_id, correlation_id=corr_id, component="runs")
    return results


# ---------------------------------------------------------------------------
# M2.C3: results sub-resources
# ---------------------------------------------------------------------------
#
# Three schema-locked GET endpoints layered over the same
# ``ResearchRunService`` used by ``POST /runs/from-ir``. They share a
# common error contract:
#
#     * 422 — invalid ULID format, or ``page_size`` exceeds the cap.
#     * 404 — run does not exist.
#     * 409 — run exists but is not COMPLETED (no result body yet).
#     * 503 — the service has not been wired into the route module.
#     * 500 — anything else (logged with ``exc_info``).
#
# Auth uses ``exports:read`` to match the existing
# ``GET /runs/{run_id}/results`` handler above; both the ``operator``
# and ``viewer`` roles already carry that scope so the new endpoints
# don't broaden access beyond what the parent endpoint already allows.


def _validate_run_id_or_422(run_id: str, *, operation: str, corr_id: str) -> None:
    """
    Reject malformed run IDs with HTTP 422 before we touch the service.

    Centralised so all three sub-resources behave identically and the
    log line carries the operation name for triage.

    Args:
        run_id: Path parameter to validate.
        operation: Snake-case name of the calling endpoint, used in
            the structured log line.
        corr_id: Request correlation ID.

    Raises:
        HTTPException 422: If ``run_id`` is not a valid ULID.
    """
    if not is_valid_ulid(run_id):
        logger.warning(
            f"{operation}.invalid_ulid",
            run_id=run_id,
            correlation_id=corr_id,
            component="runs",
        )
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Invalid ULID format",
        )


def _map_service_errors(
    exc: Exception, *, run_id: str, operation: str, corr_id: str
) -> HTTPException:
    """
    Translate a service-layer exception into the wire-format HTTPException.

    ``NotFoundError`` -> 404, ``RunNotCompletedError`` -> 409, everything
    else -> 500. The 500 branch is logged with ``exc_info`` so the
    underlying error survives in the log even though the response body
    is generic.

    Args:
        exc: Exception raised by the service call.
        run_id: ULID being queried (for log context).
        operation: Snake-case operation name (for log context).
        corr_id: Request correlation ID.

    Returns:
        Fully-populated HTTPException ready to ``raise``.
    """
    if isinstance(exc, NotFoundError):
        logger.warning(
            f"{operation}.not_found",
            run_id=run_id,
            correlation_id=corr_id,
            component="runs",
        )
        return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))

    if isinstance(exc, RunNotCompletedError):
        logger.warning(
            f"{operation}.not_completed",
            run_id=run_id,
            run_status=exc.status.value,
            correlation_id=corr_id,
            component="runs",
        )
        return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))

    logger.error(
        f"{operation}.error",
        run_id=run_id,
        error=str(exc),
        exc_info=True,
        correlation_id=corr_id,
        component="runs",
    )
    return HTTPException(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        detail="Internal server error",
    )


@router.get(
    "/{run_id}/results/equity-curve",
    response_model=EquityCurveResponse,
    summary="Equity curve for a completed run",
)
async def get_run_equity_curve_endpoint(
    run_id: str = Path(..., description="Run ULID"),
    user: AuthenticatedUser = Depends(require_scope("exports:read")),
    service: ResearchRunService = Depends(get_research_run_service),
) -> EquityCurveResponse:
    """
    Return the equity curve sub-resource for a completed run.

    Args:
        run_id: ULID of the research run.
        user: Authenticated caller with ``exports:read`` scope.
        service: Injected :class:`ResearchRunService`.

    Returns:
        :class:`EquityCurveResponse` with samples ordered ascending by
        timestamp.

    Raises:
        HTTPException 422: Invalid ULID format.
        HTTPException 404: Run does not exist.
        HTTPException 409: Run exists but has not COMPLETED.
    """
    corr_id = correlation_id_var.get("no-corr")
    logger.info(
        "get_run_equity_curve.entry",
        run_id=run_id,
        user_id=user.user_id,
        correlation_id=corr_id,
        component="runs",
    )

    _validate_run_id_or_422(run_id, operation="get_run_equity_curve", corr_id=corr_id)

    try:
        response = service.get_equity_curve(run_id)
    except Exception as exc:  # noqa: BLE001 — re-raised via _map_service_errors
        raise _map_service_errors(
            exc, run_id=run_id, operation="get_run_equity_curve", corr_id=corr_id
        ) from exc

    logger.info(
        "get_run_equity_curve.success",
        run_id=run_id,
        point_count=response.point_count,
        correlation_id=corr_id,
        component="runs",
    )
    return response


@router.get(
    "/{run_id}/results/blotter",
    response_model=TradeBlotterPage,
    summary="Trade blotter (paginated) for a completed run",
)
async def get_run_blotter_endpoint(
    run_id: str = Path(..., description="Run ULID"),
    page: int = Query(default=1, ge=1, description="1-based page index."),
    page_size: int = Query(
        default=DEFAULT_BLOTTER_PAGE_SIZE,
        ge=1,
        le=MAX_BLOTTER_PAGE_SIZE,
        description=(
            f"Trades per page (default {DEFAULT_BLOTTER_PAGE_SIZE}, max {MAX_BLOTTER_PAGE_SIZE})."
        ),
    ),
    user: AuthenticatedUser = Depends(require_scope("exports:read")),
    service: ResearchRunService = Depends(get_research_run_service),
) -> TradeBlotterPage:
    """
    Return one page of the trade blotter for a completed run.

    Pagination contract:
        * ``page`` is 1-based.
        * ``page_size`` defaults to ``DEFAULT_BLOTTER_PAGE_SIZE`` and is
          capped at ``MAX_BLOTTER_PAGE_SIZE``; values above the cap
          surface as 422 (FastAPI's default ``le`` validator).
        * Trades are sorted ascending by ``(timestamp, trade_id)`` so
          identical queries return identical pages.
        * Out-of-range pages (``page > total_pages``) return an empty
          ``trades`` list with ``total_count`` and ``total_pages`` still
          populated so callers can detect the end of the dataset.

    Args:
        run_id: ULID of the research run.
        page: 1-based page index.
        page_size: Trades per page (validated by FastAPI).
        user: Authenticated caller with ``exports:read`` scope.
        service: Injected :class:`ResearchRunService`.

    Returns:
        :class:`TradeBlotterPage` for the requested page.

    Raises:
        HTTPException 422: Invalid ULID format or page_size out of bounds.
        HTTPException 404: Run does not exist.
        HTTPException 409: Run exists but has not COMPLETED.
    """
    corr_id = correlation_id_var.get("no-corr")
    logger.info(
        "get_run_blotter.entry",
        run_id=run_id,
        page=page,
        page_size=page_size,
        user_id=user.user_id,
        correlation_id=corr_id,
        component="runs",
    )

    _validate_run_id_or_422(run_id, operation="get_run_blotter", corr_id=corr_id)

    try:
        response = service.get_blotter(run_id, page=page, page_size=page_size)
    except Exception as exc:  # noqa: BLE001 — re-raised via _map_service_errors
        raise _map_service_errors(
            exc, run_id=run_id, operation="get_run_blotter", corr_id=corr_id
        ) from exc

    logger.info(
        "get_run_blotter.success",
        run_id=run_id,
        page=page,
        page_size=page_size,
        total_count=response.total_count,
        total_pages=response.total_pages,
        returned=len(response.trades),
        correlation_id=corr_id,
        component="runs",
    )
    return response


@router.get(
    "/{run_id}/results/metrics",
    response_model=RunMetrics,
    summary="Headline metrics for a completed run",
)
async def get_run_metrics_endpoint(
    run_id: str = Path(..., description="Run ULID"),
    user: AuthenticatedUser = Depends(require_scope("exports:read")),
    service: ResearchRunService = Depends(get_research_run_service),
) -> RunMetrics:
    """
    Return the headline-metrics sub-resource for a completed run.

    Args:
        run_id: ULID of the research run.
        user: Authenticated caller with ``exports:read`` scope.
        service: Injected :class:`ResearchRunService`.

    Returns:
        :class:`RunMetrics` with all available fields populated.

    Raises:
        HTTPException 422: Invalid ULID format.
        HTTPException 404: Run does not exist.
        HTTPException 409: Run exists but has not COMPLETED.
    """
    corr_id = correlation_id_var.get("no-corr")
    logger.info(
        "get_run_metrics.entry",
        run_id=run_id,
        user_id=user.user_id,
        correlation_id=corr_id,
        component="runs",
    )

    _validate_run_id_or_422(run_id, operation="get_run_metrics", corr_id=corr_id)

    try:
        response = service.get_metrics(run_id)
    except Exception as exc:  # noqa: BLE001 — re-raised via _map_service_errors
        raise _map_service_errors(
            exc, run_id=run_id, operation="get_run_metrics", corr_id=corr_id
        ) from exc

    logger.info(
        "get_run_metrics.success",
        run_id=run_id,
        total_trades=response.total_trades,
        correlation_id=corr_id,
        component="runs",
    )
    return response
