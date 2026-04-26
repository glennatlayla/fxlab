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

from dataclasses import replace
from datetime import UTC, datetime

from libs.contracts.interfaces.dataset_repository_interface import (
    DatasetRecord,
    DatasetRepositoryInterface,
)


class MockDatasetRepository(DatasetRepositoryInterface):
    """
    In-memory implementation of :class:`DatasetRepositoryInterface`.

    Thread-safety: not thread-safe. Use only in synchronous unit tests.
    """

    def __init__(self) -> None:
        # Keyed by dataset_ref so find_by_ref / save / list operations
        # are O(1)/O(N) without requiring a sort on the in-memory rows.
        self._store: dict[str, DatasetRecord] = {}

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

    # ------------------------------------------------------------------
    # Test introspection helpers
    # ------------------------------------------------------------------

    def clear(self) -> None:
        """Remove every record. Intended for fixture teardown."""
        self._store.clear()
