"""
Dataset catalog contracts (M4.E3 admin browse + register page).

Purpose:
    Wire-level Pydantic schemas that the ``/datasets`` admin route
    (services/api/routes/datasets.py) returns to the frontend. Keeps
    HTTP-shape concerns out of the engine-facing
    :class:`ResolvedDataset` value object and the storage-shape
    :class:`DatasetRecord` dataclass.

Responsibilities:
    - :class:`DatasetListItem` — one row in the paginated catalogue
      table (every column the admin page renders).
    - :class:`PagedDatasets` — paginated envelope with ``page`` /
      ``page_size`` / ``total_count`` / ``total_pages`` mirroring the
      shape adopted by :mod:`libs.contracts.strategy.StrategyListPage`
      so the frontend reuses the same pagination component.

Does NOT:
    - Define the catalog table schema (that lives in
      :mod:`libs.contracts.models.Dataset` and the M4.E3 migration).
    - Define the engine-facing :class:`ResolvedDataset` (that lives in
      :mod:`libs.strategy_ir.interfaces.dataset_resolver_interface`).
    - Define the storage dataclass :class:`DatasetRecord` (that lives
      in :mod:`libs.contracts.interfaces.dataset_repository_interface`).

Dependencies:
    - pydantic v2 (BaseModel, ConfigDict, Field).

Example:
    page = PagedDatasets(
        datasets=[
            DatasetListItem(
                id="01HDATASET00000000000000001",
                dataset_ref="fx-eurusd-15m-certified-v3",
                symbols=["EURUSD"],
                timeframe="15m",
                source="oanda",
                version="v3",
                is_certified=True,
                created_by=None,
                created_at="2026-04-25T12:00:00+00:00",
                updated_at="2026-04-25T12:00:00+00:00",
            ),
        ],
        page=1,
        page_size=20,
        total_count=1,
        total_pages=1,
    )
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

#: Hard cap on ``page_size`` for the datasets list endpoint. Mirrors the
#: matching cap on :data:`libs.contracts.strategy.MAX_STRATEGY_LIST_PAGE_SIZE`
#: so the same UI pagination component renders both endpoints without
#: branching on different limits.
MAX_DATASET_LIST_PAGE_SIZE: int = 200

#: Default page size for the list endpoint when the caller does not specify
#: one. Mirrors the strategies endpoint default for consistency.
DEFAULT_DATASET_LIST_PAGE_SIZE: int = 20


class DatasetListItem(BaseModel):
    """
    A single row in the paginated datasets list.

    Pinned to the columns the M4.E3 admin browse page renders. Mirrors
    :class:`libs.contracts.interfaces.dataset_repository_interface.DatasetRecord`
    one-for-one but as a wire-friendly model with timestamps serialised
    as ISO-8601 strings (Pydantic's default encoding when the route
    constructs the model from a dataclass + ``str(dt)`` cast).

    Attributes:
        id: ULID primary key.
        dataset_ref: Catalog reference string (UNIQUE).
        symbols: Tradable symbols the dataset covers.
        timeframe: Bar resolution.
        source: Provider tag.
        version: Catalog version string.
        is_certified: True once the cert gate has cleared.
        created_by: ULID of the user who registered the dataset, or
            ``None`` for bootstrap-seeded entries.
        created_at: ISO-8601 timestamp of insert (or ``None`` if the
            row predates the timestamp mixin).
        updated_at: ISO-8601 timestamp of last update.

    Example:
        item = DatasetListItem(
            id="01HDATASET00000000000000001",
            dataset_ref="fx-eurusd-15m-certified-v3",
            symbols=["EURUSD"],
            timeframe="15m",
            source="oanda",
            version="v3",
            is_certified=True,
            created_by=None,
            created_at="2026-04-25T12:00:00+00:00",
            updated_at="2026-04-25T12:00:00+00:00",
        )
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    id: str = Field(..., min_length=1, description="Dataset row ULID.")
    dataset_ref: str = Field(..., min_length=1, description="Catalog reference key.")
    symbols: list[str] = Field(default_factory=list, description="Symbols covered.")
    timeframe: str = Field(..., min_length=1, description="Bar resolution.")
    source: str = Field(..., min_length=1, description="Provenance tag.")
    version: str = Field(..., min_length=1, description="Catalog version string.")
    is_certified: bool = Field(..., description="Certification flag.")
    created_by: str | None = Field(None, description="Creator ULID, or None for seeds.")
    created_at: str | None = Field(None, description="ISO-8601 insert timestamp.")
    updated_at: str | None = Field(None, description="ISO-8601 last-update timestamp.")


class PagedDatasets(BaseModel):
    """
    Response body for ``GET /datasets`` (M4.E3 admin browse page).

    Pagination contract mirrors :class:`StrategyListPage`:
        - ``page`` is 1-based.
        - ``page_size`` defaults to
          :data:`DEFAULT_DATASET_LIST_PAGE_SIZE` (20) and is capped at
          :data:`MAX_DATASET_LIST_PAGE_SIZE` (200); above the cap the
          route returns HTTP 422 (FastAPI's ``le`` validator).
        - Datasets are ordered by ``dataset_ref`` ascending so the
          alphabetical view stays stable across page boundaries.
        - Pages beyond the last populated page return an empty
          ``datasets`` list so the UI can detect the end of the dataset
          and disable the "Next" button.

    Attributes:
        datasets: The datasets on this page (may be empty).
        page: 1-based page index requested.
        page_size: Maximum datasets per page for this request.
        total_count: Total datasets matching the filters.
        total_pages: Ceiling of ``total_count / page_size`` (0 if no rows).

    Example:
        page = PagedDatasets(
            datasets=[item],
            page=1,
            page_size=20,
            total_count=1,
            total_pages=1,
        )
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    datasets: list[DatasetListItem] = Field(default_factory=list)
    page: int = Field(..., ge=1, description="1-based page index.")
    page_size: int = Field(
        ...,
        ge=1,
        le=MAX_DATASET_LIST_PAGE_SIZE,
        description="Datasets per page.",
    )
    total_count: int = Field(..., ge=0, description="Total matching datasets.")
    total_pages: int = Field(..., ge=0, description="Total pages at this page_size.")


__all__ = [
    "DEFAULT_DATASET_LIST_PAGE_SIZE",
    "MAX_DATASET_LIST_PAGE_SIZE",
    "DatasetListItem",
    "PagedDatasets",
]
