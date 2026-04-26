"""
MockDatasetRepository — in-memory DatasetRepositoryInterface for unit tests.

Purpose:
    Provide a fast, fully-controllable in-memory fake of
    :class:`DatasetRepositoryInterface` so service-layer unit tests
    can exercise :class:`DatasetService` without spinning up SQLite
    or Postgres.

Responsibilities:
    - Hold a ``dataset_ref -> DatasetRecord`` map.
    - Implement find_by_ref / save / list_all / list_known_refs / count
      with the same contract as the SQL adapter.
    - Provide ``clear()`` introspection helper for test setup/teardown.

Does NOT:
    - Touch any database, file system, or network resource.
    - Validate record shape beyond what the dataclass enforces.

Dependencies:
    - libs.contracts.interfaces.dataset_repository_interface.

Error conditions:
    - None — the in-memory store cannot fail under normal use. Tests
      that need to verify error-handling paths should patch the mock's
      methods directly.

Example:
    repo = MockDatasetRepository()
    repo.save(DatasetRecord(
        id="01HDATASET00000000000000001",
        dataset_ref="fx-eurusd-15m-certified-v3",
        symbols=["EURUSD"],
        timeframe="15m",
        source="oanda",
        version="v3",
        is_certified=True,
    ))
    assert repo.list_known_refs() == ["fx-eurusd-15m-certified-v3"]
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import UTC, datetime

from libs.contracts.interfaces.dataset_repository_interface import (
    BarInventoryAggregate,
    DatasetRecord,
    DatasetRepositoryInterface,
    RecentRunRecord,
    StrategyUsageRecord,
)


@dataclass(frozen=True)
class _MockBarRow:
    """
    Test-only fixture row representing one ``(symbol, timeframe, ts)``
    candle bar in the mock repository. Test code seeds rows via
    :meth:`MockDatasetRepository.seed_bars` so :meth:`get_bar_inventory`
    has data to aggregate.
    """

    symbol: str
    timeframe: str
    ts: datetime


@dataclass
class _MockRunRow:
    """
    Test-only fixture row representing one research run in the mock
    repository, used by :meth:`get_strategies_using` and
    :meth:`get_recent_runs`. Seeded via
    :meth:`MockDatasetRepository.seed_run`.
    """

    run_id: str
    strategy_id: str
    strategy_name: str
    dataset_ref: str
    status: str
    completed_at: datetime | None = None
    created_at: datetime = field(default_factory=lambda: datetime.now(UTC).replace(tzinfo=None))


class MockDatasetRepository(DatasetRepositoryInterface):
    """
    In-memory implementation of :class:`DatasetRepositoryInterface`.

    Thread-safety: not thread-safe. Use only in synchronous unit tests.
    """

    def __init__(self) -> None:
        # Keyed by dataset_ref so find_by_ref / save / list operations
        # are O(1)/O(N) without requiring a sort on the in-memory rows.
        self._store: dict[str, DatasetRecord] = {}
        # Optional fixture stores that back :meth:`get_bar_inventory`,
        # :meth:`get_strategies_using` and :meth:`get_recent_runs`. Tests
        # populate these via the seed_* helpers below; production code
        # never reaches the mock so these stay empty in the SQL path.
        self._bar_rows: list[_MockBarRow] = []
        self._run_rows: list[_MockRunRow] = []

    # ------------------------------------------------------------------
    # Interface implementation
    # ------------------------------------------------------------------

    def find_by_ref(self, dataset_ref: str) -> DatasetRecord | None:
        """Return the matching record or ``None``."""
        return self._store.get(dataset_ref)

    def save(self, record: DatasetRecord) -> DatasetRecord:
        """
        INSERT or UPDATE the record keyed by ``record.dataset_ref``.

        Stamps ``updated_at`` (and ``created_at`` on first insert) with
        the current UTC time so callers see populated timestamps even
        without a real database.
        """
        now = datetime.now(UTC).replace(tzinfo=None)
        existing = self._store.get(record.dataset_ref)
        if existing is None:
            stamped = replace(
                record,
                created_at=record.created_at or now,
                updated_at=record.updated_at or now,
            )
        else:
            stamped = replace(
                record,
                # Preserve immutable fields from the existing row.
                id=existing.id,
                created_at=existing.created_at,
                updated_at=now,
            )
        self._store[record.dataset_ref] = stamped
        return stamped

    def list_all(self) -> list[DatasetRecord]:
        """Return every record, sorted by ``dataset_ref``."""
        return [self._store[ref] for ref in sorted(self._store.keys())]

    def list_known_refs(self) -> list[str]:
        """Return every registered ``dataset_ref``, sorted."""
        return sorted(self._store.keys())

    def count(self) -> int:
        """
        Return the number of stored records.

        Mirrors :meth:`SqlDatasetRepository.count` so unit tests of the
        ``/health/details`` route can swap the repos transparently.
        """
        return len(self._store)

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
        Return a paginated slice of the in-memory store + total count.

        Filters compose: ``source``, ``is_certified``, and ``q`` are
        applied before pagination. ``q`` is a case-insensitive substring
        match against ``dataset_ref``. Results are sorted by
        ``dataset_ref`` ascending so test assertions are deterministic.
        """
        rows = [self._store[ref] for ref in sorted(self._store.keys())]
        if source is not None:
            rows = [r for r in rows if r.source == source]
        if is_certified is not None:
            rows = [r for r in rows if bool(r.is_certified) is bool(is_certified)]
        if q is not None and q.strip():
            needle = q.strip().lower()
            rows = [r for r in rows if needle in r.dataset_ref.lower()]
        total = len(rows)
        # Defensive bounds — pagination params are validated upstream
        # but the mock should not crash if a test passes negative values.
        start = max(0, offset)
        end = start + max(0, limit)
        return rows[start:end], total

    def get_bar_inventory(
        self,
        *,
        symbols: list[str],
        timeframe: str,
    ) -> list[BarInventoryAggregate]:
        """
        Aggregate the in-memory bar fixtures by symbol for the given
        timeframe. Symbols with no rows produce a zero-count aggregate
        so the contract matches the SQL implementation's "include every
        requested symbol" guarantee.
        """
        out: list[BarInventoryAggregate] = []
        for symbol in sorted(symbols):
            matching = [
                r for r in self._bar_rows if r.symbol == symbol and r.timeframe == timeframe
            ]
            if not matching:
                out.append(
                    BarInventoryAggregate(
                        symbol=symbol,
                        timeframe=timeframe,
                        row_count=0,
                        min_ts=None,
                        max_ts=None,
                    )
                )
                continue
            timestamps = [r.ts for r in matching]
            out.append(
                BarInventoryAggregate(
                    symbol=symbol,
                    timeframe=timeframe,
                    row_count=len(matching),
                    min_ts=min(timestamps),
                    max_ts=max(timestamps),
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
        Project distinct ``strategy_id`` values from seeded run fixtures
        whose ``dataset_ref`` matches, sorted by ``last_used_at`` desc
        (None last). Each strategy_id appears at most once.
        """
        if not dataset_ref or limit <= 0:
            return []
        matching = [r for r in self._run_rows if r.dataset_ref == dataset_ref]
        if not matching:
            return []

        # Group by strategy_id; track the most recent completed_at and
        # the canonical name (last-write-wins so tests can update names
        # via repeated seed_run calls without exploding distinct rows).
        grouped: dict[str, tuple[str, datetime | None]] = {}
        for run in matching:
            existing = grouped.get(run.strategy_id)
            if existing is None:
                grouped[run.strategy_id] = (run.strategy_name, run.completed_at)
                continue
            existing_name, existing_last = existing
            new_last = existing_last
            if run.completed_at is not None and (
                existing_last is None or run.completed_at > existing_last
            ):
                new_last = run.completed_at
            grouped[run.strategy_id] = (
                run.strategy_name or existing_name,
                new_last,
            )

        # Sort: NULLs last, then most-recent first. Stable on strategy_id
        # to keep test assertions deterministic.
        def _sort_key(item: tuple[str, tuple[str, datetime | None]]) -> tuple[int, float, str]:
            sid, (_, last) = item
            if last is None:
                return (1, 0.0, sid)
            return (0, -last.timestamp(), sid)

        ordered = sorted(grouped.items(), key=_sort_key)
        return [
            StrategyUsageRecord(
                strategy_id=sid,
                name=name,
                last_used_at=last,
            )
            for sid, (name, last) in ordered[:limit]
        ]

    def get_recent_runs(
        self,
        dataset_ref: str,
        *,
        limit: int = 10,
    ) -> list[RecentRunRecord]:
        """
        Return the most recent ``limit`` seeded runs for ``dataset_ref``,
        ordered by ``completed_at`` desc with NULLs surfacing first
        (still-running runs at the top).
        """
        if not dataset_ref or limit <= 0:
            return []
        matching = [r for r in self._run_rows if r.dataset_ref == dataset_ref]
        if not matching:
            return []

        def _sort_key(run: _MockRunRow) -> tuple[int, float, float]:
            # NULL completed_at first (still running), then most-recent
            # completed first. Tie-break on created_at so seeding order
            # is deterministic in tests.
            if run.completed_at is None:
                return (0, 0.0, -run.created_at.timestamp())
            return (1, -run.completed_at.timestamp(), -run.created_at.timestamp())

        ordered = sorted(matching, key=_sort_key)
        return [
            RecentRunRecord(
                run_id=r.run_id,
                strategy_id=r.strategy_id,
                status=r.status,
                completed_at=r.completed_at,
            )
            for r in ordered[:limit]
        ]

    # ------------------------------------------------------------------
    # Test introspection helpers
    # ------------------------------------------------------------------

    def clear(self) -> None:
        """Remove every record. Intended for fixture teardown."""
        self._store.clear()
        self._bar_rows.clear()
        self._run_rows.clear()

    def seed_bars(
        self,
        *,
        symbol: str,
        timeframe: str,
        timestamps: list[datetime],
    ) -> None:
        """
        Seed bar fixtures for unit tests of :meth:`get_bar_inventory`.

        Args:
            symbol: Symbol the bars belong to.
            timeframe: Bar resolution string (must match the dataset).
            timestamps: One datetime per bar to seed.
        """
        for ts in timestamps:
            self._bar_rows.append(_MockBarRow(symbol=symbol, timeframe=timeframe, ts=ts))

    def seed_run(
        self,
        *,
        run_id: str,
        strategy_id: str,
        strategy_name: str,
        dataset_ref: str,
        status: str,
        completed_at: datetime | None = None,
    ) -> None:
        """
        Seed a research-run fixture for unit tests of
        :meth:`get_strategies_using` and :meth:`get_recent_runs`.

        Args:
            run_id: ULID of the run.
            strategy_id: ULID of the strategy.
            strategy_name: Display name (mirrors the strategies table).
            dataset_ref: Catalog reference the run targets.
            status: Lifecycle status string.
            completed_at: Completion timestamp (None for in-flight).
        """
        self._run_rows.append(
            _MockRunRow(
                run_id=run_id,
                strategy_id=strategy_id,
                strategy_name=strategy_name,
                dataset_ref=dataset_ref,
                status=status,
                completed_at=completed_at,
            )
        )
