"""
Dataset catalog contracts (M4.E3 admin browse + register page; detail view).

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
    - :class:`BarInventoryRow` — one row in the per-symbol/timeframe
      bar-inventory section of the admin Detail page.
    - :class:`StrategyRef` — one row in the "Strategies using this
      dataset" section of the admin Detail page.
    - :class:`RecentRunRef` — one row in the "Recent runs" section of
      the admin Detail page.
    - :class:`DatasetDetail` — top-level envelope returned by the
      ``GET /datasets/{ref}/detail`` admin endpoint; powers the
      ``/admin/datasets/:ref`` page in the frontend.

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


# ---------------------------------------------------------------------------
# Dataset detail (M4.E3 follow-up — /admin/datasets/{ref} page)
# ---------------------------------------------------------------------------


class BarInventoryRow(BaseModel):
    """
    One row in the bar-inventory section of the dataset detail page.

    Aggregates :class:`libs.contracts.models.CandleRecord` rows for a
    single ``(symbol, timeframe)`` pair: count and the min/max bar
    timestamp the catalog has on hand for the dataset.

    Attributes:
        symbol: Symbol the row applies to (e.g. ``"EURUSD"``).
        timeframe: Bar resolution string (mirrors the dataset record's
            ``timeframe`` — every row in this dataset shares it, but it
            is repeated here so the table is self-describing).
        row_count: Number of candle bars stored for this pair.
            Non-negative; zero indicates the symbol is registered but no
            bars have been ingested yet.
        min_ts: ISO-8601 timestamp of the oldest bar, or ``None`` when
            ``row_count`` is zero.
        max_ts: ISO-8601 timestamp of the newest bar, or ``None`` when
            ``row_count`` is zero.

    Example:
        row = BarInventoryRow(
            symbol="EURUSD",
            timeframe="15m",
            row_count=12345,
            min_ts="2026-01-01T00:00:00",
            max_ts="2026-04-25T23:45:00",
        )
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    symbol: str = Field(..., min_length=1, description="Symbol the row applies to.")
    timeframe: str = Field(..., min_length=1, description="Bar resolution.")
    row_count: int = Field(..., ge=0, description="Number of bars stored.")
    min_ts: str | None = Field(None, description="ISO-8601 timestamp of oldest bar.")
    max_ts: str | None = Field(None, description="ISO-8601 timestamp of newest bar.")


class StrategyRef(BaseModel):
    """
    One row in the "Strategies using this dataset" section of the
    dataset detail page.

    Derived by walking :class:`libs.contracts.models.ResearchRun` rows
    whose ``config_json.data_selection.dataset_ref`` matches the dataset
    being inspected, projecting the distinct ``strategy_id`` set, then
    enriching each entry with the strategy's display name and the most
    recent run timestamp.

    Attributes:
        strategy_id: ULID primary key of the strategy.
        name: Human-readable strategy name (or ``""`` if the strategy
            row has been deleted but historical research runs still
            reference its id).
        last_used_at: ISO-8601 timestamp of the most recent
            ResearchRun.completed_at against this dataset for this
            strategy, or ``None`` if the only matching runs are still
            in flight.

    Example:
        ref = StrategyRef(
            strategy_id="01HSTRAT0000000000000001",
            name="EURUSD MACD Momentum",
            last_used_at="2026-04-25T14:30:00",
        )
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    strategy_id: str = Field(..., min_length=1, description="Strategy ULID.")
    name: str = Field("", description="Human-readable strategy name (may be empty).")
    last_used_at: str | None = Field(None, description="ISO-8601 timestamp of last completed run.")


class RecentRunRef(BaseModel):
    """
    One row in the "Recent runs" section of the dataset detail page.

    Each row is a :class:`libs.contracts.models.ResearchRun` whose
    ``config_json.data_selection.dataset_ref`` matches the dataset.

    Attributes:
        run_id: ULID primary key of the research run.
        strategy_id: ULID of the strategy the run targets.
        status: Lifecycle status string (``"pending"``, ``"queued"``,
            ``"running"``, ``"completed"``, ``"failed"``,
            ``"cancelled"``).
        completed_at: ISO-8601 timestamp of completion, or ``None`` when
            the run is still in flight.

    Example:
        ref = RecentRunRef(
            run_id="01HRUN00000000000000000001",
            strategy_id="01HSTRAT0000000000000001",
            status="completed",
            completed_at="2026-04-25T14:30:00",
        )
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    run_id: str = Field(..., min_length=1, description="ResearchRun ULID.")
    strategy_id: str = Field(..., min_length=1, description="Strategy ULID.")
    status: str = Field(..., min_length=1, description="Lifecycle status string.")
    completed_at: str | None = Field(None, description="ISO-8601 timestamp of completion.")


class DatasetDetail(BaseModel):
    """
    Response body for ``GET /datasets/{dataset_ref}/detail``.

    Top-level envelope rendered by the ``/admin/datasets/:ref`` page.
    The header fields mirror :class:`DatasetListItem` so the same
    pill / badge components can render either shape; the three list
    fields drill into per-symbol bar inventory, strategies that have
    consumed the dataset, and the most recent runs that referenced it.

    Attributes:
        dataset_ref: Catalog reference key (UNIQUE).
        dataset_id: ULID primary key of the dataset row.
        symbols: Tradable symbols the dataset covers.
        timeframe: Bar resolution string.
        source: Provenance tag.
        version: Catalog version string.
        is_certified: True once the cert gate has cleared.
        created_at: ISO-8601 timestamp of insert (or None).
        updated_at: ISO-8601 timestamp of last update (or None).
        bar_inventory: One row per ``(symbol, timeframe)`` covered by
            the dataset. Empty when no bars have been ingested.
        strategies_using: Top 10 strategies (by most-recent run) that
            have referenced this dataset_ref in a research run.
        recent_runs: Top 10 runs (by ``completed_at`` desc, NULLs last)
            that referenced this dataset_ref.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    dataset_ref: str = Field(..., min_length=1)
    dataset_id: str = Field(..., min_length=1)
    symbols: list[str] = Field(default_factory=list)
    timeframe: str = Field(..., min_length=1)
    source: str = Field(..., min_length=1)
    version: str = Field(..., min_length=1)
    is_certified: bool = Field(...)
    created_at: str | None = Field(None)
    updated_at: str | None = Field(None)
    bar_inventory: list[BarInventoryRow] = Field(default_factory=list)
    strategies_using: list[StrategyRef] = Field(default_factory=list)
    recent_runs: list[RecentRunRef] = Field(default_factory=list)


__all__ = [
    "DEFAULT_DATASET_LIST_PAGE_SIZE",
    "MAX_DATASET_LIST_PAGE_SIZE",
    "BarInventoryRow",
    "DatasetDetail",
    "DatasetListItem",
    "PagedDatasets",
    "RecentRunRef",
    "StrategyRef",
]
