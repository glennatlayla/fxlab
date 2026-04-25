"""
Routes for /runs endpoints.
Thin handlers - no business logic.
"""

from __future__ import annotations

import re
from typing import Any

import structlog
from fastapi import APIRouter, Depends, HTTPException, Path, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from libs.contracts.experiment_plan import ExperimentPlan
from libs.strategy_ir.interfaces.dataset_resolver_interface import (
    DatasetNotFoundError,
    DatasetResolverInterface,
)
from services.api.auth import AuthenticatedUser, require_scope
from services.api.middleware.correlation import correlation_id_var

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
    try:
        record = service.submit_from_ir(
            strategy_id=payload.strategy_id,
            experiment_plan=payload.experiment_plan,
            resolved_dataset=resolved,
            user_id=user.user_id,
            correlation_id=corr_id,
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
