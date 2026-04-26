"""
DatasetService — Postgres-backed implementation of
:class:`DatasetServiceInterface` (M4.E3).

Purpose:
    Translate a textual ``dataset_ref`` into a concrete
    :class:`ResolvedDataset`, persist registrations into the catalog,
    and expose the certification flag — all backed by the ``datasets``
    table via :class:`SqlDatasetRepository`.

Replaces:
    The M2.C2 :class:`InMemoryDatasetResolver`. The narrow
    :class:`DatasetResolverInterface` continues to work via
    :class:`CatalogBackedResolver`, the thin adapter that wraps a
    :class:`DatasetServiceInterface`.

Responsibilities:
    - lookup(): translate dataset_ref → :class:`ResolvedDataset`,
      raising :class:`DatasetNotFoundError` on miss.
    - list_known_refs(): proxy to the repository's cheap
      single-column SELECT.
    - register_dataset(): upsert a dataset entry. Generates a ULID
      for the row id on first insert and preserves it on subsequent
      updates.
    - is_certified(): boolean check used by the certification gate.
    - count(): cheap row-count probe used by ``/health/details``.

Does NOT:
    - Drive ingestion or candle storage.
    - Touch SQL directly — every database call goes through
      :class:`DatasetRepositoryInterface`.

Dependencies:
    - DatasetRepositoryInterface (injected): the persistence port.

Error conditions:
    - lookup raises :class:`DatasetNotFoundError` for unknown refs.
    - register_dataset raises :class:`ValueError` on empty/short
      arguments. Repository-level errors propagate as
      :class:`DatasetRepositoryError`.

Example:
    repo = SqlDatasetRepository(db=session)
    svc = DatasetService(repo=repo)
    svc.register_dataset(
        "fx-eurusd-15m-certified-v3",
        symbols=["EURUSD"],
        timeframe="15m",
        source="oanda",
        version="v3",
    )
    resolved = svc.lookup("fx-eurusd-15m-certified-v3")
"""

from __future__ import annotations

import structlog
import ulid

from libs.contracts.dataset import (
    BarInventoryRow,
    DatasetDetail,
    DatasetListItem,
    PagedDatasets,
    RecentRunRef,
    StrategyRef,
)
from libs.contracts.interfaces.dataset_repository_interface import (
    BarInventoryAggregate,
    DatasetRecord,
    DatasetRepositoryInterface,
    RecentRunRecord,
    StrategyUsageRecord,
)
from libs.strategy_ir.interfaces.dataset_service_interface import (
    DatasetNotFoundError,
    DatasetServiceInterface,
    ResolvedDataset,
)

logger = structlog.get_logger(__name__)


class DatasetService(DatasetServiceInterface):
    """
    Postgres-backed catalog service.

    Responsibilities:
    - Coordinate lookup / list / register / is_certified against the
      repository.
    - Convert :class:`DatasetRecord` (storage shape) into
      :class:`ResolvedDataset` (engine-facing shape).
    - Generate ULIDs for new catalog rows.

    Does NOT:
    - Cache results — request-scoped sessions make caching unsafe.
      An LRU layer can sit in front of this service if profiling
      shows lookup is hot.
    - Validate symbol strings beyond non-empty list.

    Dependencies:
    - :class:`DatasetRepositoryInterface` (injected via constructor).
    """

    def __init__(self, repo: DatasetRepositoryInterface) -> None:
        """
        Args:
            repo: Persistence port. In production wire the SQL
                implementation; in tests use the in-memory mock.
        """
        self._repo = repo

    # ------------------------------------------------------------------
    # DatasetServiceInterface
    # ------------------------------------------------------------------

    def lookup(self, dataset_ref: str) -> ResolvedDataset:
        """
        Translate ``dataset_ref`` into a :class:`ResolvedDataset`.

        Args:
            dataset_ref: Catalog reference string.

        Returns:
            Populated :class:`ResolvedDataset`.

        Raises:
            DatasetNotFoundError: If the reference is not registered.
        """
        if not dataset_ref:
            raise DatasetNotFoundError(dataset_ref)

        record = self._repo.find_by_ref(dataset_ref)
        if record is None:
            logger.warning(
                "dataset_service.lookup.miss",
                component="DatasetService",
                operation="lookup",
                dataset_ref=dataset_ref,
                result="not_found",
            )
            raise DatasetNotFoundError(dataset_ref)

        return _to_resolved(record)

    def list_known_refs(self) -> list[str]:
        """Return every registered ``dataset_ref``, sorted."""
        return self._repo.list_known_refs()

    def register_dataset(
        self,
        dataset_ref: str,
        *,
        symbols: list[str],
        timeframe: str,
        source: str,
        version: str,
    ) -> None:
        """
        Upsert a dataset entry in the catalog.

        On first call for a given ``dataset_ref``, INSERTs a new row
        with a freshly-generated ULID. On subsequent calls UPDATEs
        the row in place (preserving the ULID and ``created_at``).

        Args:
            dataset_ref: Opaque catalog reference string. Must be
                non-empty.
            symbols: Tradable symbols the dataset covers. Must be
                non-empty.
            timeframe: Bar resolution (``"15m"``, ``"1h"``, ``"4h"``,
                ``"1d"``).
            source: Provider tag (``"oanda"``, ``"alpaca"``,
                ``"synthetic"``...).
            version: Catalog version string.

        Raises:
            ValueError: On empty / blank arguments.
            DatasetRepositoryError: On persistence failure.
        """
        if not dataset_ref:
            raise ValueError("dataset_ref must be non-empty")
        if not symbols:
            raise ValueError("symbols must be non-empty")
        if not timeframe:
            raise ValueError("timeframe must be non-empty")
        if not source:
            raise ValueError("source must be non-empty")
        if not version:
            raise ValueError("version must be non-empty")

        existing = self._repo.find_by_ref(dataset_ref)
        if existing is None:
            row_id = str(ulid.ULID())
            record = DatasetRecord(
                id=row_id,
                dataset_ref=dataset_ref,
                symbols=list(symbols),
                timeframe=timeframe,
                source=source,
                version=version,
                # is_certified defaults to False on first insert; the
                # certification workflow (separate path) flips it.
                is_certified=False,
                created_by=None,
            )
        else:
            record = DatasetRecord(
                id=existing.id,
                dataset_ref=dataset_ref,
                symbols=list(symbols),
                timeframe=timeframe,
                source=source,
                version=version,
                # Preserve certification across re-registrations —
                # upgrading a dataset's metadata should not implicitly
                # de-certify it.
                is_certified=existing.is_certified,
                created_by=existing.created_by,
                created_at=existing.created_at,
            )

        self._repo.save(record)
        logger.info(
            "dataset_service.register_dataset.succeeded",
            component="DatasetService",
            operation="register_dataset",
            dataset_ref=dataset_ref,
            symbols_count=len(symbols),
            timeframe=timeframe,
            source=source,
            version=version,
            inserted=existing is None,
            result="success",
        )

    def is_certified(self, dataset_ref: str) -> bool:
        """
        Return whether ``dataset_ref`` has cleared the cert gate.

        Returns ``False`` for unknown references (callers that want to
        distinguish should call :meth:`lookup` first).
        """
        if not dataset_ref:
            return False
        record = self._repo.find_by_ref(dataset_ref)
        if record is None:
            return False
        return bool(record.is_certified)

    def list_paged(
        self,
        *,
        page: int,
        page_size: int,
        source_filter: str | None = None,
        is_certified: bool | None = None,
        q: str | None = None,
    ) -> PagedDatasets:
        """
        Return one page of catalog rows as a :class:`PagedDatasets`
        envelope (M4.E3 admin browse).

        Translates 1-based ``page`` into ``offset`` for the repository,
        delegates the SQL work, then projects the storage-layer
        :class:`DatasetRecord` instances into the wire-shape
        :class:`DatasetListItem`.

        Args:
            page: 1-based page index (validated by the route layer's
                ``ge=1`` query parameter).
            page_size: Datasets per page (validated by the route).
            source_filter: Optional exact-match filter on ``source``.
            is_certified: Optional certification flag filter.
            q: Optional case-insensitive substring search on
                ``dataset_ref``.

        Returns:
            :class:`PagedDatasets` ready for JSON serialisation.
        """
        offset = max(0, (page - 1) * page_size)
        records, total_count = self._repo.list_paged(
            limit=page_size,
            offset=offset,
            source=source_filter,
            is_certified=is_certified,
            q=q,
        )

        items = [_to_list_item(r) for r in records]
        # ceil(total / page_size) without importing math.
        total_pages = (total_count + page_size - 1) // page_size if page_size > 0 else 0

        result = PagedDatasets(
            datasets=items,
            page=page,
            page_size=page_size,
            total_count=total_count,
            total_pages=total_pages,
        )

        logger.debug(
            "dataset_service.list_paged.completed",
            component="DatasetService",
            operation="list_paged",
            page=page,
            page_size=page_size,
            returned=len(items),
            total_count=total_count,
            source_filter=source_filter,
            is_certified=is_certified,
            q=q,
        )

        return result

    def get_record(self, dataset_ref: str) -> DatasetListItem:
        """
        Return the full catalog row as a wire-shape :class:`DatasetListItem`.

        Used by the admin endpoints that need the full metadata
        (timeframe, source, version, timestamps).

        Raises:
            DatasetNotFoundError: If ``dataset_ref`` is not registered.
        """
        if not dataset_ref:
            raise DatasetNotFoundError(dataset_ref)
        record = self._repo.find_by_ref(dataset_ref)
        if record is None:
            raise DatasetNotFoundError(dataset_ref)
        return _to_list_item(record)

    def update_version(self, dataset_ref: str, *, version: str) -> None:
        """
        Update the ``version`` string on an existing dataset row.

        Preserves every other field. The row must already exist.

        Raises:
            DatasetNotFoundError: If the reference is not registered.
            ValueError: If ``version`` is empty.
        """
        if not dataset_ref:
            raise DatasetNotFoundError(dataset_ref)
        if not version:
            raise ValueError("version must be non-empty")

        existing = self._repo.find_by_ref(dataset_ref)
        if existing is None:
            logger.warning(
                "dataset_service.update_version.miss",
                component="DatasetService",
                operation="update_version",
                dataset_ref=dataset_ref,
                result="not_found",
            )
            raise DatasetNotFoundError(dataset_ref)

        updated = DatasetRecord(
            id=existing.id,
            dataset_ref=existing.dataset_ref,
            symbols=list(existing.symbols),
            timeframe=existing.timeframe,
            source=existing.source,
            version=version,
            is_certified=bool(existing.is_certified),
            created_by=existing.created_by,
            created_at=existing.created_at,
        )
        self._repo.save(updated)

        logger.info(
            "dataset_service.update_version.succeeded",
            component="DatasetService",
            operation="update_version",
            dataset_ref=dataset_ref,
            version=version,
            result="success",
        )

    def count(self) -> int:
        """
        Return the number of registered datasets in the catalog.

        Pure delegation to :meth:`DatasetRepositoryInterface.count`. The
        service layer adds no caching — request-scoped sessions make
        cached aggregates stale across operators registering new rows
        in parallel.

        Returns:
            Non-negative integer row count.

        Raises:
            DatasetRepositoryError: Propagated from the repository on
                driver / connection failure.
        """
        return self._repo.count()

    def get_detail(self, dataset_ref: str) -> DatasetDetail:
        """
        Return the rich :class:`DatasetDetail` envelope for the
        ``/admin/datasets/{ref}`` page.

        Orchestrates four repository calls (catalog row, bar inventory,
        strategies-using, recent runs) and projects the storage
        dataclasses into wire-shape Pydantic models.

        Args:
            dataset_ref: Catalog reference key.

        Returns:
            Populated :class:`DatasetDetail` ready for JSON
            serialisation.

        Raises:
            DatasetNotFoundError: If the reference is not registered.
        """
        if not dataset_ref:
            raise DatasetNotFoundError(dataset_ref)

        record = self._repo.find_by_ref(dataset_ref)
        if record is None:
            logger.warning(
                "dataset_service.get_detail.miss",
                component="DatasetService",
                operation="get_detail",
                dataset_ref=dataset_ref,
                result="not_found",
            )
            raise DatasetNotFoundError(dataset_ref)

        bar_aggregates = self._repo.get_bar_inventory(
            symbols=list(record.symbols),
            timeframe=record.timeframe,
        )
        strategies = self._repo.get_strategies_using(dataset_ref, limit=10)
        runs = self._repo.get_recent_runs(dataset_ref, limit=10)

        detail = DatasetDetail(
            dataset_ref=record.dataset_ref,
            dataset_id=record.id,
            symbols=list(record.symbols),
            timeframe=record.timeframe,
            source=record.source,
            version=record.version,
            is_certified=bool(record.is_certified),
            created_at=record.created_at.isoformat() if record.created_at else None,
            updated_at=record.updated_at.isoformat() if record.updated_at else None,
            bar_inventory=[_to_bar_row(a) for a in bar_aggregates],
            strategies_using=[_to_strategy_ref(s) for s in strategies],
            recent_runs=[_to_recent_run_ref(r) for r in runs],
        )

        logger.info(
            "dataset_service.get_detail.completed",
            component="DatasetService",
            operation="get_detail",
            dataset_ref=dataset_ref,
            symbols_count=len(record.symbols),
            inventory_rows=len(detail.bar_inventory),
            strategies_count=len(detail.strategies_using),
            recent_runs_count=len(detail.recent_runs),
            result="success",
        )
        return detail

    def update_certification(self, dataset_ref: str, *, is_certified: bool) -> None:
        """
        Flip the certification flag on an existing dataset row.

        Args:
            dataset_ref: Catalog reference key. Must already exist.
            is_certified: New value for the flag.

        Raises:
            DatasetNotFoundError: If the reference is not registered.
        """
        if not dataset_ref:
            raise DatasetNotFoundError(dataset_ref)

        existing = self._repo.find_by_ref(dataset_ref)
        if existing is None:
            logger.warning(
                "dataset_service.update_certification.miss",
                component="DatasetService",
                operation="update_certification",
                dataset_ref=dataset_ref,
                result="not_found",
            )
            raise DatasetNotFoundError(dataset_ref)

        updated = DatasetRecord(
            id=existing.id,
            dataset_ref=existing.dataset_ref,
            symbols=list(existing.symbols),
            timeframe=existing.timeframe,
            source=existing.source,
            version=existing.version,
            is_certified=bool(is_certified),
            created_by=existing.created_by,
            created_at=existing.created_at,
        )
        self._repo.save(updated)

        logger.info(
            "dataset_service.update_certification.succeeded",
            component="DatasetService",
            operation="update_certification",
            dataset_ref=dataset_ref,
            is_certified=bool(is_certified),
            result="success",
        )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _to_resolved(record: DatasetRecord) -> ResolvedDataset:
    """
    Translate a storage :class:`DatasetRecord` into the engine-facing
    :class:`ResolvedDataset` value object.

    The ``dataset_id`` field carries the catalog row's ULID — stable
    across renames of the human-readable ``dataset_ref``.
    """
    return ResolvedDataset(
        dataset_ref=record.dataset_ref,
        dataset_id=record.id,
        symbols=list(record.symbols),
    )


def _to_list_item(record: DatasetRecord) -> DatasetListItem:
    """
    Translate a storage :class:`DatasetRecord` into the wire-shape
    :class:`DatasetListItem` returned by the M4.E3 admin browse
    endpoint.

    Timestamps are serialised via ``isoformat()`` so the JSON payload
    carries ISO-8601 strings (Pydantic does not coerce ``datetime``
    fields to strings on a ``str``-typed field, so we do it here).
    """
    return DatasetListItem(
        id=record.id,
        dataset_ref=record.dataset_ref,
        symbols=list(record.symbols),
        timeframe=record.timeframe,
        source=record.source,
        version=record.version,
        is_certified=bool(record.is_certified),
        created_by=record.created_by,
        created_at=record.created_at.isoformat() if record.created_at else None,
        updated_at=record.updated_at.isoformat() if record.updated_at else None,
    )


def _to_bar_row(aggregate: BarInventoryAggregate) -> BarInventoryRow:
    """
    Translate a storage :class:`BarInventoryAggregate` into the
    wire-shape :class:`BarInventoryRow`.
    """
    return BarInventoryRow(
        symbol=aggregate.symbol,
        timeframe=aggregate.timeframe,
        row_count=aggregate.row_count,
        min_ts=aggregate.min_ts.isoformat() if aggregate.min_ts else None,
        max_ts=aggregate.max_ts.isoformat() if aggregate.max_ts else None,
    )


def _to_strategy_ref(usage: StrategyUsageRecord) -> StrategyRef:
    """
    Translate a storage :class:`StrategyUsageRecord` into the
    wire-shape :class:`StrategyRef`.
    """
    return StrategyRef(
        strategy_id=usage.strategy_id,
        name=usage.name,
        last_used_at=usage.last_used_at.isoformat() if usage.last_used_at else None,
    )


def _to_recent_run_ref(run: RecentRunRecord) -> RecentRunRef:
    """
    Translate a storage :class:`RecentRunRecord` into the wire-shape
    :class:`RecentRunRef`.
    """
    return RecentRunRef(
        run_id=run.run_id,
        strategy_id=run.strategy_id,
        status=run.status,
        completed_at=run.completed_at.isoformat() if run.completed_at else None,
    )


__all__ = [
    "DatasetService",
]
