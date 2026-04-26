"""
SQL-backed dataset catalog repository (M4.E3).

Purpose:
    Persist :class:`DatasetRecord` rows in the ``datasets`` table for
    consumption by :class:`DatasetService`. This is the single layer
    that talks SQL for the dataset catalog entity.

Responsibilities:
    - find_by_ref(): SELECT a single row by its UNIQUE ``dataset_ref``.
    - save(): UPSERT a row (INSERT on miss, UPDATE on hit).
    - list_all(): SELECT every row, sorted by ``dataset_ref``.
    - list_known_refs(): SELECT only the ``dataset_ref`` column.
    - count(): SELECT COUNT(*) — cheap inventory probe for ``/health/details``.

Does NOT:
    - Drive ingestion (data-pipeline owns that).
    - Translate the storage record into the engine-facing
      :class:`ResolvedDataset` — :class:`DatasetService` does that.
    - commit() the session — request-scoped commits are the caller's
      responsibility (FastAPI's ``get_db`` handles it at request end).

Dependencies:
    - sqlalchemy.orm.Session (injected via constructor).
    - libs.contracts.models.Dataset: ORM model.
    - libs.contracts.interfaces.dataset_repository_interface:
      DatasetRecord, DatasetRepositoryError, DatasetRepositoryInterface.

Error conditions:
    - :class:`DatasetRepositoryError` is raised when SQLAlchemy reports
      any driver / integrity error. The inner exception is chained via
      ``raise from`` so operators see the full cause.

Example:
    repo = SqlDatasetRepository(db=session)
    record = repo.find_by_ref("fx-eurusd-15m-certified-v3")
    if record is None:
        raise DatasetNotFoundError("fx-eurusd-15m-certified-v3")
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any, cast

import structlog
from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from libs.contracts.interfaces.dataset_repository_interface import (
    BarInventoryAggregate,
    DatasetRecord,
    DatasetRepositoryError,
    DatasetRepositoryInterface,
    RecentRunRecord,
    StrategyUsageRecord,
)
from libs.contracts.models import CandleRecord, Dataset, ResearchRun, Strategy

logger = structlog.get_logger(__name__)


class SqlDatasetRepository(DatasetRepositoryInterface):
    """
    SQL-backed implementation of :class:`DatasetRepositoryInterface`.

    Responsibilities:
    - Translate ORM ``Dataset`` rows to/from the storage-level
      :class:`DatasetRecord` dataclass so the service layer never
      depends on SQLAlchemy.
    - Wrap every SQLAlchemy error in :class:`DatasetRepositoryError`
      so callers handle one consistent exception type.

    Does NOT:
    - Hold business logic.
    - Open or close transactions — the session lifetime is owned by
      the FastAPI ``get_db`` dependency.
    - Generate ULIDs — callers supply ``record.id``.
    """

    def __init__(self, db: Session) -> None:
        """
        Args:
            db: Request-scoped SQLAlchemy session. Not retained across
                requests; the caller ensures lifetime.
        """
        self._db = db

    # ------------------------------------------------------------------
    # Interface implementation
    # ------------------------------------------------------------------

    def find_by_ref(self, dataset_ref: str) -> DatasetRecord | None:
        """
        Return the row matching ``dataset_ref`` or ``None``.

        Args:
            dataset_ref: Catalog reference key.

        Returns:
            :class:`DatasetRecord` or ``None`` if no row matches.

        Raises:
            DatasetRepositoryError: On driver / connection failure.
        """
        try:
            stmt = select(Dataset).where(Dataset.dataset_ref == dataset_ref)
            row: Dataset | None = self._db.execute(stmt).scalar_one_or_none()
        except SQLAlchemyError as exc:
            logger.error(
                "dataset_repository.find_by_ref.failed",
                component="SqlDatasetRepository",
                operation="find_by_ref",
                dataset_ref=dataset_ref,
                error=str(exc),
                exc_info=True,
            )
            raise DatasetRepositoryError(f"Failed to look up dataset_ref={dataset_ref!r}") from exc

        if row is None:
            return None
        return _to_record(row)

    def save(self, record: DatasetRecord) -> DatasetRecord:
        """
        INSERT a new row or UPDATE the existing row in place.

        The dataset_ref column is UNIQUE; we use it as the natural key
        for upsert semantics. ``id`` and ``created_at`` are immutable
        once written.

        Args:
            record: The :class:`DatasetRecord` to persist.

        Returns:
            The persisted record, re-read from the session so any
            server-side defaults are populated.

        Raises:
            DatasetRepositoryError: On driver / integrity error.
        """
        try:
            stmt = select(Dataset).where(Dataset.dataset_ref == record.dataset_ref)
            existing: Dataset | None = self._db.execute(stmt).scalar_one_or_none()

            if existing is None:
                row = Dataset(
                    id=record.id,
                    dataset_ref=record.dataset_ref,
                    symbols=list(record.symbols),
                    timeframe=record.timeframe,
                    source=record.source,
                    version=record.version,
                    is_certified=record.is_certified,
                    created_by=record.created_by,
                )
                self._db.add(row)
            else:
                # UPDATE in place — preserve id + created_at, refresh
                # the rest. updated_at is bumped by TimestampMixin's
                # onupdate hook.
                existing.symbols = list(record.symbols)
                existing.timeframe = record.timeframe
                existing.source = record.source
                existing.version = record.version
                existing.is_certified = record.is_certified
                if record.created_by is not None:
                    existing.created_by = record.created_by
                row = existing

            self._db.flush()
            self._db.refresh(row)
        except SQLAlchemyError as exc:
            self._db.rollback()
            logger.error(
                "dataset_repository.save.failed",
                component="SqlDatasetRepository",
                operation="save",
                dataset_ref=record.dataset_ref,
                error=str(exc),
                exc_info=True,
            )
            raise DatasetRepositoryError(
                f"Failed to save dataset_ref={record.dataset_ref!r}"
            ) from exc

        logger.info(
            "dataset_repository.save.succeeded",
            component="SqlDatasetRepository",
            operation="save",
            dataset_ref=record.dataset_ref,
            result="success",
        )
        return _to_record(row)

    def list_all(self) -> list[DatasetRecord]:
        """
        Return every row, sorted by ``dataset_ref``.

        Returns:
            List of :class:`DatasetRecord`. Empty when the catalog is
            empty.

        Raises:
            DatasetRepositoryError: On driver failure.
        """
        try:
            stmt = select(Dataset).order_by(Dataset.dataset_ref.asc())
            rows = list(self._db.execute(stmt).scalars().all())
        except SQLAlchemyError as exc:
            logger.error(
                "dataset_repository.list_all.failed",
                component="SqlDatasetRepository",
                operation="list_all",
                error=str(exc),
                exc_info=True,
            )
            raise DatasetRepositoryError("Failed to list datasets") from exc

        return [_to_record(r) for r in rows]

    def list_known_refs(self) -> list[str]:
        """
        Return every ``dataset_ref`` in the catalog, sorted.

        Returns:
            Sorted list of strings. Empty when the catalog is empty.

        Raises:
            DatasetRepositoryError: On driver failure.
        """
        try:
            stmt = select(Dataset.dataset_ref).order_by(Dataset.dataset_ref.asc())
            refs = [str(r) for r in self._db.execute(stmt).scalars().all()]
        except SQLAlchemyError as exc:
            logger.error(
                "dataset_repository.list_known_refs.failed",
                component="SqlDatasetRepository",
                operation="list_known_refs",
                error=str(exc),
                exc_info=True,
            )
            raise DatasetRepositoryError("Failed to list dataset refs") from exc

        return refs

    def count(self) -> int:
        """
        Return the total number of rows in the ``datasets`` table.

        Implemented as a ``SELECT COUNT(*) FROM datasets`` aggregate so
        the database does the work — never load every row to count them.
        Used by the ``/health/details`` endpoint to surface catalog
        inventory cheaply.

        Returns:
            Non-negative integer row count. Zero when the catalog is
            empty.

        Raises:
            DatasetRepositoryError: On driver / connection failure.
        """
        try:
            stmt = select(func.count()).select_from(Dataset)
            total = int(self._db.execute(stmt).scalar_one())
        except SQLAlchemyError as exc:
            logger.error(
                "dataset_repository.count.failed",
                component="SqlDatasetRepository",
                operation="count",
                error=str(exc),
                exc_info=True,
            )
            raise DatasetRepositoryError("Failed to count datasets") from exc

        return total

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
        Return one page of catalog rows + the total filtered count.

        Filters are applied as SQL WHERE clauses so the database does
        the work — never load the whole catalog and slice in Python.
        Sort order is ``dataset_ref ASC`` so the alphabetical view stays
        stable across page boundaries.

        Args:
            limit: Page size.
            offset: Rows to skip (page index * page size).
            source: Optional exact-match filter on ``Dataset.source``.
            is_certified: Optional exact-match filter on the boolean
                column.
            q: Optional case-insensitive ILIKE substring search on
                ``Dataset.dataset_ref``.

        Returns:
            ``(rows, total_count)``.

        Raises:
            DatasetRepositoryError: On driver failure.
        """
        try:
            base = select(Dataset)
            if source is not None:
                base = base.where(Dataset.source == source)
            if is_certified is not None:
                base = base.where(Dataset.is_certified == is_certified)
            if q is not None and q.strip():
                # ``ilike`` is portable across Postgres + SQLite (SQLite
                # treats ``ilike`` as ``like`` with case-insensitive
                # default collation, which matches the contract).
                needle = f"%{q.strip().lower()}%"
                base = base.where(func.lower(Dataset.dataset_ref).like(needle))

            # Total count subquery — counts the FILTERED set, ignoring
            # limit/offset, so the UI knows how many pages exist.
            count_stmt = select(func.count()).select_from(base.subquery())
            total = int(self._db.execute(count_stmt).scalar_one())

            page_stmt = base.order_by(Dataset.dataset_ref.asc()).limit(limit).offset(offset)
            rows = list(self._db.execute(page_stmt).scalars().all())
        except SQLAlchemyError as exc:
            logger.error(
                "dataset_repository.list_paged.failed",
                component="SqlDatasetRepository",
                operation="list_paged",
                error=str(exc),
                exc_info=True,
            )
            raise DatasetRepositoryError("Failed to list paged datasets") from exc

        return [_to_record(r) for r in rows], total

    # ------------------------------------------------------------------
    # Detail-page projections (M4.E3 follow-up)
    # ------------------------------------------------------------------

    def get_bar_inventory(
        self,
        *,
        symbols: list[str],
        timeframe: str,
    ) -> list[BarInventoryAggregate]:
        """
        Aggregate :class:`CandleRecord` rows by symbol for the given
        timeframe.

        One ``GROUP BY symbol`` SELECT against the candle-records table
        filtered to ``symbol IN :symbols AND interval = :timeframe``.
        Symbols with no candle rows are returned with ``row_count=0``
        and ``min_ts=max_ts=None`` so the detail UI can render a
        per-symbol "no data ingested" badge consistently.
        """
        if not symbols:
            return []

        try:
            stmt = (
                select(
                    CandleRecord.symbol,
                    func.count(CandleRecord.id),
                    func.min(CandleRecord.timestamp),
                    func.max(CandleRecord.timestamp),
                )
                .where(CandleRecord.symbol.in_(list(symbols)))
                .where(CandleRecord.interval == timeframe)
                .group_by(CandleRecord.symbol)
            )
            rows = list(self._db.execute(stmt).all())
        except SQLAlchemyError as exc:
            logger.error(
                "dataset_repository.get_bar_inventory.failed",
                component="SqlDatasetRepository",
                operation="get_bar_inventory",
                timeframe=timeframe,
                symbols_count=len(symbols),
                error=str(exc),
                exc_info=True,
            )
            raise DatasetRepositoryError(
                f"Failed to aggregate bar inventory for timeframe={timeframe!r}"
            ) from exc

        # Index aggregates by symbol so we can fill zero rows for
        # symbols that returned no group.
        by_symbol: dict[str, tuple[int, datetime | None, datetime | None]] = {}
        for row in rows:
            symbol_value = str(row[0])
            count_value = int(row[1] or 0)
            min_value = cast(datetime | None, row[2])
            max_value = cast(datetime | None, row[3])
            by_symbol[symbol_value] = (count_value, min_value, max_value)

        out: list[BarInventoryAggregate] = []
        for symbol in sorted(symbols):
            agg = by_symbol.get(symbol)
            if agg is None:
                out.append(
                    BarInventoryAggregate(
                        symbol=symbol,
                        timeframe=timeframe,
                        row_count=0,
                        min_ts=None,
                        max_ts=None,
                    )
                )
            else:
                count_value, min_value, max_value = agg
                out.append(
                    BarInventoryAggregate(
                        symbol=symbol,
                        timeframe=timeframe,
                        row_count=count_value,
                        min_ts=min_value,
                        max_ts=max_value,
                    )
                )
        return out

    def get_strategies_using(
        self,
        dataset_ref: str,
        *,
        limit: int = 10,
    ) -> list[StrategyUsageRecord]:
        """
        Project distinct ``strategy_id`` values from research runs whose
        :attr:`ResearchRun.config_json` carries a matching
        ``data_selection.dataset_ref``.

        The ``config_json`` column is a JSON blob; portable JSON-path
        filtering (Postgres ``->>`` vs SQLite ``json_extract``) would
        fork the query. To keep the repository portable across the
        SQLite test path and the Postgres production path, this method
        SELECTs candidate runs ordered by ``completed_at DESC NULLS
        LAST`` (the natural recency ordering) and filters in Python.

        We bound the candidate fetch at ``max(limit * 50, 200)`` rows
        so the worst case (a busy strategy with hundreds of runs not
        matching this dataset) still terminates promptly. The bound is
        intentionally generous because filtering is cheap (a dict
        lookup on already-loaded JSON) and the alternative — exposing
        a SQL JSON path through a portable shim — is more brittle.
        """
        if not dataset_ref or limit <= 0:
            return []

        candidate_limit = max(limit * 50, 200)
        try:
            run_stmt = (
                select(
                    ResearchRun.id,
                    ResearchRun.strategy_id,
                    ResearchRun.config_json,
                    ResearchRun.completed_at,
                )
                .order_by(
                    ResearchRun.completed_at.desc().nullslast(),
                    ResearchRun.created_at.desc(),
                )
                .limit(candidate_limit)
            )
            run_rows = list(self._db.execute(run_stmt).all())
        except SQLAlchemyError as exc:
            logger.error(
                "dataset_repository.get_strategies_using.failed",
                component="SqlDatasetRepository",
                operation="get_strategies_using",
                dataset_ref=dataset_ref,
                error=str(exc),
                exc_info=True,
            )
            raise DatasetRepositoryError(
                f"Failed to query strategies for dataset_ref={dataset_ref!r}"
            ) from exc

        # Group: strategy_id -> most-recent completed_at across matching
        # runs.
        per_strategy: dict[str, datetime | None] = {}
        for row in run_rows:
            run_strategy_id = str(row[1])
            run_config = _coerce_config(row[2])
            if _config_dataset_ref(run_config) != dataset_ref:
                continue
            completed_at = cast(datetime | None, row[3])
            existing = per_strategy.get(run_strategy_id, _MISSING)
            if existing is _MISSING:
                per_strategy[run_strategy_id] = completed_at
                continue
            if completed_at is None:
                # Keep the existing value (may already be a real ts).
                continue
            existing_dt = cast(datetime | None, existing)
            if existing_dt is None or completed_at > existing_dt:
                per_strategy[run_strategy_id] = completed_at

        if not per_strategy:
            return []

        # Resolve display names with a single IN-clause SELECT.
        try:
            name_stmt = select(Strategy.id, Strategy.name).where(
                Strategy.id.in_(list(per_strategy.keys()))
            )
            names = {str(row[0]): str(row[1]) for row in self._db.execute(name_stmt).all()}
        except SQLAlchemyError as exc:
            logger.error(
                "dataset_repository.get_strategies_using.name_lookup_failed",
                component="SqlDatasetRepository",
                operation="get_strategies_using",
                dataset_ref=dataset_ref,
                error=str(exc),
                exc_info=True,
            )
            raise DatasetRepositoryError(
                f"Failed to resolve strategy names for dataset_ref={dataset_ref!r}"
            ) from exc

        # Sort: most-recent first, NULLs last, stable on strategy_id.
        def _sort_key(item: tuple[str, datetime | None]) -> tuple[int, float, str]:
            sid, last = item
            if last is None:
                return (1, 0.0, sid)
            return (0, -last.timestamp(), sid)

        ordered = sorted(per_strategy.items(), key=_sort_key)
        return [
            StrategyUsageRecord(
                strategy_id=sid,
                name=names.get(sid, ""),
                last_used_at=last,
            )
            for sid, last in ordered[:limit]
        ]

    def get_recent_runs(
        self,
        dataset_ref: str,
        *,
        limit: int = 10,
    ) -> list[RecentRunRecord]:
        """
        Return the most recent ``limit`` :class:`ResearchRun` rows whose
        ``config_json.data_selection.dataset_ref`` matches.

        Same Python-side JSON filter as :meth:`get_strategies_using`
        (see that docstring for the rationale on why we do not push the
        filter into SQL). Runs without a ``completed_at`` (still in
        flight) sort first so operators see active work at the top of
        the list.
        """
        if not dataset_ref or limit <= 0:
            return []

        candidate_limit = max(limit * 50, 200)
        try:
            stmt = (
                select(
                    ResearchRun.id,
                    ResearchRun.strategy_id,
                    ResearchRun.status,
                    ResearchRun.completed_at,
                    ResearchRun.config_json,
                    ResearchRun.created_at,
                )
                .order_by(
                    # NULLs first → still-running runs surface at the top
                    # of the recent-runs panel; completed runs follow in
                    # most-recent-first order.
                    ResearchRun.completed_at.desc().nullsfirst(),
                    ResearchRun.created_at.desc(),
                )
                .limit(candidate_limit)
            )
            rows = list(self._db.execute(stmt).all())
        except SQLAlchemyError as exc:
            logger.error(
                "dataset_repository.get_recent_runs.failed",
                component="SqlDatasetRepository",
                operation="get_recent_runs",
                dataset_ref=dataset_ref,
                error=str(exc),
                exc_info=True,
            )
            raise DatasetRepositoryError(
                f"Failed to query recent runs for dataset_ref={dataset_ref!r}"
            ) from exc

        out: list[RecentRunRecord] = []
        for row in rows:
            cfg = _coerce_config(row[4])
            if _config_dataset_ref(cfg) != dataset_ref:
                continue
            out.append(
                RecentRunRecord(
                    run_id=str(row[0]),
                    strategy_id=str(row[1]),
                    status=str(row[2]),
                    completed_at=cast(datetime | None, row[3]),
                )
            )
            if len(out) >= limit:
                break
        return out


# ---------------------------------------------------------------------------
# Translation helpers
# ---------------------------------------------------------------------------


# Sentinel distinct from ``None`` so :meth:`get_strategies_using` can
# distinguish "key not seen yet" from "key seen, value is None".
_MISSING: Any = object()


def _coerce_config(raw: Any) -> dict[str, Any]:
    """
    Coerce the polymorphic ``config_json`` column into a dict.

    The SQLAlchemy ``JSON`` column type returns the parsed Python value
    when both Postgres and SQLite drivers are used, but defensive code
    in production has been observed to write the column as a JSON string
    on a few legacy paths. This helper handles both.
    """
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str):
        try:
            decoded = json.loads(raw)
        except (TypeError, ValueError):
            return {}
        if isinstance(decoded, dict):
            return decoded
    return {}


def _config_dataset_ref(cfg: dict[str, Any]) -> str | None:
    """
    Extract ``data_selection.dataset_ref`` from a research-run config
    blob, or return ``None`` if either key is missing.
    """
    selection = cfg.get("data_selection")
    if not isinstance(selection, dict):
        return None
    ref = selection.get("dataset_ref")
    if isinstance(ref, str):
        return ref
    return None


def _to_record(row: Dataset) -> DatasetRecord:
    """
    Convert an ORM ``Dataset`` row to a storage-level
    :class:`DatasetRecord`.

    Defensive about ``symbols`` because JSON columns can round-trip as
    ``None`` on engines that do not enforce NOT NULL on JSON.
    """
    raw_symbols = row.symbols
    if raw_symbols is None:
        symbols: list[str] = []
    elif isinstance(raw_symbols, list):
        symbols = [str(s) for s in raw_symbols]
    else:
        # Defensive — JSON column shape is enforced by the contract,
        # but coerce anything else into the empty list rather than
        # leaking a non-list shape into the service layer.
        symbols = []

    return DatasetRecord(
        id=str(row.id),
        dataset_ref=str(row.dataset_ref),
        symbols=symbols,
        timeframe=str(row.timeframe),
        source=str(row.source),
        version=str(row.version),
        is_certified=bool(row.is_certified),
        created_by=str(row.created_by) if row.created_by is not None else None,
        # Cast: SQLAlchemy's typed Column descriptor reports as Column[datetime]
        # to mypy, but at runtime the row attribute is the materialised value.
        created_at=cast(datetime | None, row.created_at),
        updated_at=cast(datetime | None, row.updated_at),
    )


__all__ = [
    "SqlDatasetRepository",
]
