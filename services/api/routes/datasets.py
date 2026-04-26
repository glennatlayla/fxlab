"""
Admin dataset catalog routes (M4.E3 browse + register page).

Purpose:
    Expose CRUD endpoints for the M4.E3 :class:`DatasetService`
    backed by the ``datasets`` Postgres table. Powers the
    ``/admin/datasets`` admin browse + register page in the frontend.

Responsibilities:
    - GET /datasets/?page=&page_size=&source=&is_certified=&q=
        Paginated list of catalog rows with optional filters.
    - POST /datasets/
        Register a new dataset (or upsert existing). Returns 201 with
        the resolved row.
    - PATCH /datasets/{dataset_ref}
        Update is_certified and/or version on an existing row. 404 if
        the ref does not exist.
    - Audit log per request (operator visibility — admin sub-tree).

Does NOT:
    - Contain business logic (delegates to :class:`DatasetService`).
    - Touch SQL directly (the service owns the repo).
    - Cache responses — request-scoped sessions make caching unsafe.

Dependencies:
    - DatasetServiceInterface (injected via module-level setter, like
      the strategies router) — wired in services.api.main.
    - require_scope("admin:manage") for authorization (matches the
      existing admin sub-tree convention).

Error conditions:
    - 401: Missing or invalid authentication token.
    - 403: Caller lacks admin:manage scope.
    - 404: PATCH against an unknown dataset_ref.
    - 422: Request body fails Pydantic validation, or the PATCH body
      contains no fields to update.

Example:
    GET  /datasets/?page=1&page_size=20             → 200 PagedDatasets
    POST /datasets/  {dataset_ref, symbols, ...}    → 201 DatasetListItem
    PATCH /datasets/fx-eurusd-15m-certified-v3
          {"is_certified": true}                    → 200 DatasetListItem
"""

from __future__ import annotations

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, status
from pydantic import BaseModel, ConfigDict, Field

from libs.contracts.dataset import (
    DEFAULT_DATASET_LIST_PAGE_SIZE,
    MAX_DATASET_LIST_PAGE_SIZE,
    DatasetDetail,
    DatasetListItem,
    PagedDatasets,
)
from libs.strategy_ir.interfaces.dataset_service_interface import (
    DatasetNotFoundError,
    DatasetServiceInterface,
)
from services.api.auth import AuthenticatedUser, require_scope
from services.api.middleware.correlation import correlation_id_var

logger = structlog.get_logger(__name__)

router = APIRouter(prefix="/datasets", tags=["datasets"])


# ---------------------------------------------------------------------------
# Request schemas
# ---------------------------------------------------------------------------


class RegisterDatasetRequest(BaseModel):
    """
    Request payload for ``POST /datasets/``.

    Mirrors the :meth:`DatasetService.register_dataset` signature plus
    an optional ``is_certified`` flag (defaults to False on first
    insert; preserved on updates per the service contract).
    """

    model_config = ConfigDict(extra="forbid")

    dataset_ref: str = Field(..., min_length=1, max_length=128, description="Catalog ref key.")
    symbols: list[str] = Field(..., min_length=1, description="Symbols covered.")
    timeframe: str = Field(..., min_length=1, max_length=16, description="Bar resolution.")
    source: str = Field(..., min_length=1, max_length=64, description="Provenance tag.")
    version: str = Field(..., min_length=1, max_length=32, description="Catalog version.")
    is_certified: bool = Field(False, description="Initial certification flag.")


class UpdateDatasetRequest(BaseModel):
    """
    Request payload for ``PATCH /datasets/{dataset_ref}``.

    Both fields are optional so the admin UI can flip just the
    certification flag without resending the version. At least one
    field must be supplied or the request is rejected with 422.
    """

    model_config = ConfigDict(extra="forbid")

    is_certified: bool | None = Field(None, description="New certification flag.")
    version: str | None = Field(
        None, min_length=1, max_length=32, description="New catalog version."
    )


# ---------------------------------------------------------------------------
# Module-level DI for DatasetService
# ---------------------------------------------------------------------------

_dataset_service: DatasetServiceInterface | None = None


def set_dataset_service(service: DatasetServiceInterface | None) -> None:
    """
    Register the :class:`DatasetServiceInterface` instance for the route.

    Called during application bootstrap (``services.api.main``) and in
    tests. ``None`` is accepted so test teardown can reset the global.

    Args:
        service: The :class:`DatasetServiceInterface` implementation,
            or ``None`` to unset.
    """
    global _dataset_service
    _dataset_service = service


def get_dataset_service() -> DatasetServiceInterface:
    """
    FastAPI dependency: return the wired :class:`DatasetService`.

    Raises:
        HTTPException 503: If the service has not been wired (the API
            booted without the M4.E3 catalog wiring).
    """
    if _dataset_service is None:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="DatasetService not configured.",
        )
    return _dataset_service


# ---------------------------------------------------------------------------
# GET /datasets/ — paginated list
# ---------------------------------------------------------------------------


@router.get(
    "/",
    response_model=PagedDatasets,
    summary="List datasets (paginated, admin only)",
)
async def list_datasets(
    page: int = Query(1, ge=1, description="1-based page index."),
    page_size: int = Query(
        DEFAULT_DATASET_LIST_PAGE_SIZE,
        ge=1,
        le=MAX_DATASET_LIST_PAGE_SIZE,
        description="Datasets per page (1-200, default 20).",
    ),
    source: str | None = Query(
        None, max_length=64, description="Exact-match filter on provenance tag."
    ),
    is_certified: bool | None = Query(
        None, description="Exact-match filter on the certification flag."
    ),
    q: str | None = Query(
        None,
        max_length=128,
        description="Case-insensitive substring search on dataset_ref.",
    ),
    user: AuthenticatedUser = Depends(require_scope("admin:manage")),
    service: DatasetServiceInterface = Depends(get_dataset_service),
) -> PagedDatasets:
    """
    Return one page of catalog rows.

    Filters compose: every supplied parameter narrows the result set
    further. Page is 1-based; out-of-range pages return an empty
    ``datasets`` list with ``total_count`` / ``total_pages`` unchanged
    so the UI can detect the end of the dataset.

    Args:
        page: 1-based page index.
        page_size: Datasets per page (capped at 200).
        source: Optional exact-match filter on provenance tag.
        is_certified: Optional certification flag filter.
        q: Optional case-insensitive substring search on ``dataset_ref``.
        user: Authenticated user with ``admin:manage`` scope.
        service: Injected :class:`DatasetServiceInterface`.

    Returns:
        :class:`PagedDatasets` envelope.
    """
    corr_id = correlation_id_var.get("no-corr")
    result = service.list_paged(
        page=page,
        page_size=page_size,
        source_filter=source,
        is_certified=is_certified,
        q=q,
    )

    # Audit log per request — admin sub-tree convention.
    logger.info(
        "datasets.list.completed",
        operation="list_datasets",
        component="datasets",
        user_id=user.user_id,
        correlation_id=corr_id,
        page=page,
        page_size=page_size,
        source_filter=source,
        is_certified=is_certified,
        q=q,
        returned=len(result.datasets),
        total_count=result.total_count,
        result="success",
    )
    return result


# ---------------------------------------------------------------------------
# POST /datasets/ — register a new dataset
# ---------------------------------------------------------------------------


@router.post(
    "/",
    status_code=status.HTTP_201_CREATED,
    response_model=DatasetListItem,
    summary="Register a dataset (admin only)",
)
async def register_dataset(
    payload: RegisterDatasetRequest,
    user: AuthenticatedUser = Depends(require_scope("admin:manage")),
    service: DatasetServiceInterface = Depends(get_dataset_service),
) -> DatasetListItem:
    """
    Create or upsert a dataset entry in the catalog.

    Delegates to :meth:`DatasetService.register_dataset` (UPSERT
    semantics; preserves existing certification on re-register), then
    flips the certification flag if the caller supplied
    ``is_certified=True``.

    Args:
        payload: Validated :class:`RegisterDatasetRequest`.
        user: Authenticated user with ``admin:manage`` scope.
        service: Injected :class:`DatasetServiceInterface`.

    Returns:
        201 with a :class:`DatasetListItem` representing the persisted
        row (re-read from the catalog so server-side defaults like
        timestamps are populated).

    Raises:
        HTTPException 422: If the payload fails Pydantic validation
            (handled by FastAPI) or the service rejects empty fields.
    """
    corr_id = correlation_id_var.get("no-corr")
    try:
        service.register_dataset(
            payload.dataset_ref,
            symbols=list(payload.symbols),
            timeframe=payload.timeframe,
            source=payload.source,
            version=payload.version,
        )
    except ValueError as exc:
        # Service-side guards (empty arguments) → 422 with the message.
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc

    # If the caller asked for certification on registration, flip the
    # flag explicitly. The service preserves certification across
    # re-registers and defaults to False on first insert; the explicit
    # toggle covers both shapes.
    if payload.is_certified:
        try:
            service.update_certification(payload.dataset_ref, is_certified=True)
        except DatasetNotFoundError as exc:
            # Race: register succeeded but the row vanished before the
            # certification update — surface as 500 because the catalog
            # is in an inconsistent state.
            logger.error(
                "datasets.register.cert_race",
                dataset_ref=payload.dataset_ref,
                user_id=user.user_id,
                correlation_id=corr_id,
                component="datasets",
                operation="register_dataset",
                exc_info=True,
            )
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Dataset registered but certification update lost the row.",
            ) from exc

    # Re-read so the response carries the persisted row (including
    # server-generated timestamps + ULID).
    item = service.get_record(payload.dataset_ref)

    logger.info(
        "datasets.register.completed",
        operation="register_dataset",
        component="datasets",
        user_id=user.user_id,
        correlation_id=corr_id,
        dataset_ref=payload.dataset_ref,
        is_certified=item.is_certified,
        result="success",
    )
    return item


# ---------------------------------------------------------------------------
# PATCH /datasets/{dataset_ref} — update certification / version
# ---------------------------------------------------------------------------


@router.patch(
    "/{dataset_ref}",
    response_model=DatasetListItem,
    summary="Update dataset certification or version (admin only)",
)
async def update_dataset(
    dataset_ref: str,
    payload: UpdateDatasetRequest,
    user: AuthenticatedUser = Depends(require_scope("admin:manage")),
    service: DatasetServiceInterface = Depends(get_dataset_service),
) -> DatasetListItem:
    """
    Update is_certified and/or version on an existing dataset row.

    At least one of ``is_certified`` / ``version`` must be supplied;
    a request with both fields ``None`` is rejected with 422 because
    the operation would be a no-op.

    Args:
        dataset_ref: Catalog reference key from the URL path.
        payload: Validated :class:`UpdateDatasetRequest`.
        user: Authenticated user with ``admin:manage`` scope.
        service: Injected :class:`DatasetServiceInterface`.

    Returns:
        200 with the updated :class:`DatasetListItem`.

    Raises:
        HTTPException 404: If ``dataset_ref`` is not registered.
        HTTPException 422: If both fields are ``None`` (nothing to do).
    """
    corr_id = correlation_id_var.get("no-corr")

    if payload.is_certified is None and payload.version is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="At least one of 'is_certified' or 'version' must be supplied.",
        )

    # Apply updates in order (version first so the certification log
    # line carries the latest version). Each update fires its own
    # DatasetNotFoundError if the row vanished mid-request.
    try:
        if payload.version is not None:
            service.update_version(dataset_ref, version=payload.version)
        if payload.is_certified is not None:
            service.update_certification(dataset_ref, is_certified=payload.is_certified)
    except DatasetNotFoundError as exc:
        logger.warning(
            "datasets.update.not_found",
            dataset_ref=dataset_ref,
            user_id=user.user_id,
            correlation_id=corr_id,
            component="datasets",
            operation="update_dataset",
        )
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Dataset '{dataset_ref}' not registered.",
        ) from exc
    except ValueError as exc:
        # update_version raises ValueError on empty version; Pydantic
        # already rejects min_length=1 so this is a defence-in-depth
        # path that surfaces as 422.
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=str(exc),
        ) from exc

    item = service.get_record(dataset_ref)

    logger.info(
        "datasets.update.completed",
        operation="update_dataset",
        component="datasets",
        user_id=user.user_id,
        correlation_id=corr_id,
        dataset_ref=dataset_ref,
        is_certified=item.is_certified,
        version=item.version,
        result="success",
    )
    return item


# ---------------------------------------------------------------------------
# GET /datasets/{dataset_ref}/detail — admin detail page
# ---------------------------------------------------------------------------


@router.get(
    "/{dataset_ref}/detail",
    response_model=DatasetDetail,
    summary="Dataset detail (admin only)",
)
async def dataset_detail(
    dataset_ref: str,
    user: AuthenticatedUser = Depends(require_scope("admin:manage")),
    service: DatasetServiceInterface = Depends(get_dataset_service),
) -> DatasetDetail:
    """
    Return the rich :class:`DatasetDetail` envelope for the
    ``/admin/datasets/:ref`` page.

    Args:
        dataset_ref: Catalog reference key from the URL path.
        user: Authenticated user with ``admin:manage`` scope.
        service: Injected :class:`DatasetServiceInterface`.

    Returns:
        200 with a :class:`DatasetDetail`.

    Raises:
        HTTPException 404: If ``dataset_ref`` is not registered.
    """
    corr_id = correlation_id_var.get("no-corr")
    try:
        detail = service.get_detail(dataset_ref)
    except DatasetNotFoundError as exc:
        logger.warning(
            "datasets.detail.not_found",
            dataset_ref=dataset_ref,
            user_id=user.user_id,
            correlation_id=corr_id,
            component="datasets",
            operation="dataset_detail",
        )
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Dataset '{dataset_ref}' not registered.",
        ) from exc

    logger.info(
        "datasets.detail.completed",
        operation="dataset_detail",
        component="datasets",
        user_id=user.user_id,
        correlation_id=corr_id,
        dataset_ref=dataset_ref,
        inventory_rows=len(detail.bar_inventory),
        strategies_count=len(detail.strategies_using),
        recent_runs_count=len(detail.recent_runs),
        result="success",
    )
    return detail


__all__ = [
    "RegisterDatasetRequest",
    "UpdateDatasetRequest",
    "dataset_detail",
    "get_dataset_service",
    "router",
    "set_dataset_service",
]
