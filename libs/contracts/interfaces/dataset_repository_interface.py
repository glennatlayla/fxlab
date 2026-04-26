"""
DatasetRepositoryInterface — port for dataset catalog persistence (M4.E3).

Purpose:
    Define the contract every dataset repository implementation must
    honour so the M4.E3 :class:`DatasetService` depends on an
    abstraction (not on SQLAlchemy or any other concrete storage).

Responsibilities:
    - find_by_ref(): lookup a single dataset by its ``dataset_ref`` key.
    - save(): upsert a dataset record. Returns the saved record so the
      caller can read back any database-side defaults (timestamps).
    - list_all(): enumerate every dataset record (admin / operator
      tooling).
    - list_known_refs(): enumerate just the ``dataset_ref`` keys, sorted
      (the cheap path consumed by ops endpoints).

Does NOT:
    - Mutate dataset payloads.
    - Drive ingestion or candle storage (that is the data-pipeline's
      responsibility).
    - Evaluate certification semantics — the service consumes
      ``is_certified`` directly.

Dependencies:
    - libs.contracts.market_data: ResolvedDataset value object — but
      this interface returns the storage-level dataclass below, not
      the wire model. The service layer is responsible for translating
      the storage record into the engine-facing
      :class:`ResolvedDataset`.

Error conditions:
    - find_by_ref returns ``None`` when the dataset_ref is absent (the
      service layer translates this into the typed
      :class:`DatasetNotFoundError` for upstream callers).
    - save raises :class:`DatasetRepositoryError` when the underlying
      store rejects the write (driver error, constraint violation).

Example:
    repo = SqlDatasetRepository(db=session)
    record = repo.find_by_ref("fx-eurusd-15m-certified-v3")
    if record is None:
        raise DatasetNotFoundError("fx-eurusd-15m-certified-v3")
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime


@dataclass(frozen=True)
class BarInventoryAggregate:
    """
    Repository-level snapshot of one ``(symbol, timeframe)`` aggregate
    over the candle-records table.

    Returned by :meth:`DatasetRepositoryInterface.get_bar_inventory` so
    the service layer can project storage rows into the wire-shape
    :class:`libs.contracts.dataset.BarInventoryRow` without leaking
    SQLAlchemy types.

    Attributes:
        symbol: Symbol the row applies to.
        timeframe: Bar resolution (e.g. ``"15m"``, ``"1h"``).
        row_count: Number of candle rows for the pair (>= 0).
        min_ts: Oldest bar timestamp, or ``None`` when the pair has no
            bars yet.
        max_ts: Newest bar timestamp, or ``None`` when the pair has no
            bars yet.
    """

    symbol: str
    timeframe: str
    row_count: int = 0
    min_ts: datetime | None = None
    max_ts: datetime | None = None


@dataclass(frozen=True)
class StrategyUsageRecord:
    """
    Repository-level snapshot of a strategy that has consumed the
    dataset via at least one research run.

    Attributes:
        strategy_id: ULID of the strategy.
        name: Strategy display name (``""`` when the strategy row no
            longer exists; historical research runs may outlive their
            strategies).
        last_used_at: Most recent ``completed_at`` across the matching
            research runs, or ``None`` when no completed run exists yet.
    """

    strategy_id: str
    name: str = ""
    last_used_at: datetime | None = None


@dataclass(frozen=True)
class RecentRunRecord:
    """
    Repository-level snapshot of a research run that referenced the
    dataset.

    Attributes:
        run_id: ULID of the research run.
        strategy_id: ULID of the strategy the run targets.
        status: Lifecycle status string (``"pending"``, ``"queued"``,
            ``"running"``, ``"completed"``, ``"failed"``,
            ``"cancelled"``).
        completed_at: Completion timestamp, or ``None`` for in-flight
            runs.
    """

    run_id: str
    strategy_id: str
    status: str
    completed_at: datetime | None = None


class DatasetRepositoryError(Exception):
    """
    Raised when the repository cannot satisfy a request for any reason
    other than caller error (network failure, DB outage, integrity
    violation).

    Service-layer callers should treat this as a 5xx-class failure.
    """


@dataclass(frozen=True)
class DatasetRecord:
    """
    Storage-level snapshot of a row in the ``datasets`` catalog table.

    Returned by :class:`DatasetRepositoryInterface` implementations.
    The service layer converts this into the engine-facing
    :class:`ResolvedDataset` value object before returning to callers.

    Attributes:
        id: ULID primary key.
        dataset_ref: Catalog reference string (UNIQUE).
        symbols: Tradable symbols the dataset covers.
        timeframe: Bar resolution.
        source: Provider tag (``"oanda"``, ``"alpaca"``,
            ``"synthetic"``...).
        version: Catalog version string.
        is_certified: True once the cert gate has cleared.
        created_by: ULID of the user who created the entry, or ``None``
            for bootstrap-seeded entries.
        created_at: Insert timestamp (server default ``now()``).
        updated_at: Last-update timestamp.
    """

    id: str
    dataset_ref: str
    symbols: list[str] = field(default_factory=list)
    timeframe: str = ""
    source: str = ""
    version: str = ""
    is_certified: bool = False
    created_by: str | None = None
    created_at: datetime | None = None
    updated_at: datetime | None = None


class DatasetRepositoryInterface(ABC):
    """
    Abstract port for dataset-catalog persistence.

    Implementations:
        - :class:`services.api.repositories.sql_dataset_repository.SqlDatasetRepository`
          (production, Postgres-backed).
        - :class:`libs.contracts.mocks.mock_dataset_repository.MockDatasetRepository`
          (unit tests, in-memory).
    """

    @abstractmethod
    def find_by_ref(self, dataset_ref: str) -> DatasetRecord | None:
        """
        Look up a dataset record by its catalog reference key.

        Args:
            dataset_ref: Opaque catalog reference string.

        Returns:
            The matching :class:`DatasetRecord` or ``None`` if no row
            exists for ``dataset_ref``.

        Raises:
            DatasetRepositoryError: On transport / driver failure.
        """
        ...

    @abstractmethod
    def save(self, record: DatasetRecord) -> DatasetRecord:
        """
        INSERT or UPDATE a dataset row.

        Behaviour:
            - If no row exists for ``record.dataset_ref``, INSERT.
            - If a row exists, UPDATE every field except ``id`` and
              ``created_at`` (those are immutable). ``updated_at`` is
              refreshed by the implementation.

        Args:
            record: The :class:`DatasetRecord` to persist.

        Returns:
            The persisted record, re-read from the database so any
            server-side defaults (timestamps) are populated.

        Raises:
            DatasetRepositoryError: On driver / integrity error.
        """
        ...

    @abstractmethod
    def list_all(self) -> list[DatasetRecord]:
        """
        Return every catalog row, sorted by ``dataset_ref``.

        Returns:
            List of :class:`DatasetRecord`. Empty when the catalog is
            empty.

        Raises:
            DatasetRepositoryError: On driver failure.
        """
        ...

    @abstractmethod
    def list_known_refs(self) -> list[str]:
        """
        Return every ``dataset_ref`` in the catalog, sorted.

        Cheaper than :meth:`list_all` because the implementation only
        SELECTs a single column — used by ops endpoints.

        Returns:
            Sorted list of strings. Empty when the catalog is empty.

        Raises:
            DatasetRepositoryError: On driver failure.
        """
        ...

    @abstractmethod
    def count(self) -> int:
        """
        Return the total number of rows in the dataset catalog.

        Cheaper than :meth:`list_all` because the implementation only
        executes a ``SELECT COUNT(*)`` aggregate — used by the
        ``/health/details`` endpoint to surface catalog inventory at a
        glance without materialising any rows.

        Returns:
            Non-negative integer row count. Zero when the catalog is
            empty.

        Raises:
            DatasetRepositoryError: On driver / connection failure.
        """
        ...

    @abstractmethod
    def list_paged(
        self,
        *,
        limit: int,
        offset: int,
        source: str | None = None,
        is_certified: bool | None = None,
        q: str | None = None,
    ) -> tuple[list[DatasetRecord], int]:
        """
        Return a single page of catalog rows + the total filtered count.

        Used by the admin browse endpoint. The optional filters compose:
        every non-None argument narrows the result set further.

        Args:
            limit: Maximum rows to return (page size).
            offset: Number of rows to skip (page index * page size).
            source: Optional exact-match filter on ``source``.
            is_certified: Optional exact-match filter on ``is_certified``.
            q: Optional case-insensitive substring search on
                ``dataset_ref`` (the only human-readable identifier).

        Returns:
            Tuple ``(rows, total_count)`` where ``rows`` is the paginated
            slice (sorted by ``dataset_ref`` ascending) and ``total_count``
            is the total number of rows matching the filters (used by the
            UI to compute total pages).

        Raises:
            DatasetRepositoryError: On driver failure.
        """
        ...

    @abstractmethod
    def get_bar_inventory(
        self,
        *,
        symbols: list[str],
        timeframe: str,
    ) -> list[BarInventoryAggregate]:
        """
        Return one aggregate per ``(symbol, timeframe)`` over the
        candle-records table.

        The dataset catalog has no foreign key into the candle store
        (the bar table predates the catalog and is keyed on
        ``(symbol, interval, timestamp)``). Joining is left to the
        repository: implementations issue a single
        ``GROUP BY symbol`` query against the candle-record table
        filtered by the dataset's ``symbols`` array and ``timeframe``.

        For symbols with zero rows in the bar table, the implementation
        SHOULD include a :class:`BarInventoryAggregate` with
        ``row_count=0``, ``min_ts=None``, ``max_ts=None`` so the
        operator UI can show a "no data ingested" badge for that symbol.

        Args:
            symbols: Symbols the dataset covers. Each becomes one row in
                the result (whether or not bars exist).
            timeframe: Bar resolution string (mirrors
                :attr:`DatasetRecord.timeframe`).

        Returns:
            One :class:`BarInventoryAggregate` per input symbol, sorted
            by symbol ascending. Empty when ``symbols`` is empty.

        Raises:
            DatasetRepositoryError: On driver / connection failure.
        """
        ...

    @abstractmethod
    def get_strategies_using(
        self,
        dataset_ref: str,
        *,
        limit: int = 10,
    ) -> list[StrategyUsageRecord]:
        """
        Return the top ``limit`` strategies that have referenced
        ``dataset_ref`` in a research run, sorted by the most recent
        completed run timestamp (descending; NULLs last).

        Linkage: research runs persist their config as JSON in
        :attr:`ResearchRun.config_json`; the dataset reference lives at
        ``data_selection.dataset_ref`` inside that blob. The repository
        is responsible for materialising the strategy display name from
        the ``strategies`` table when present.

        Args:
            dataset_ref: Catalog reference key.
            limit: Maximum strategies to return (defaults to 10).

        Returns:
            List of :class:`StrategyUsageRecord` (length 0..limit).
            Empty when the dataset has never been referenced.

        Raises:
            DatasetRepositoryError: On driver / connection failure.
        """
        ...

    @abstractmethod
    def get_recent_runs(
        self,
        dataset_ref: str,
        *,
        limit: int = 10,
    ) -> list[RecentRunRecord]:
        """
        Return the most recent ``limit`` research runs that referenced
        ``dataset_ref``, ordered by ``completed_at`` descending (NULLs
        first so still-running runs surface at the top of the list).

        Args:
            dataset_ref: Catalog reference key.
            limit: Maximum runs to return (defaults to 10).

        Returns:
            List of :class:`RecentRunRecord` (length 0..limit).

        Raises:
            DatasetRepositoryError: On driver / connection failure.
        """
        ...


__all__ = [
    "BarInventoryAggregate",
    "DatasetRecord",
    "DatasetRepositoryError",
    "DatasetRepositoryInterface",
    "RecentRunRecord",
    "StrategyUsageRecord",
]
