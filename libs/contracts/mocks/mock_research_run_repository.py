"""
In-memory mock research run repository for unit testing.

Purpose:
    Provide a thread-safe, in-memory implementation of
    ResearchRunRepositoryInterface for use in unit tests.
    Mirrors the behaviour of the SQL implementation without I/O.

Responsibilities:
    - CRUD for research run records in memory.
    - Status transition validation.
    - Introspection helpers for test assertions.

Does NOT:
    - Perform any I/O, database, or network operations.
    - Contain business logic beyond storage and retrieval.

Dependencies:
    - libs.contracts.interfaces.research_run_repository
    - libs.contracts.research_run

Example:
    repo = MockResearchRunRepository()
    repo.create(record)
    assert repo.count() == 1
    assert repo.get_by_id(record.id) is not None
"""

from __future__ import annotations

import threading
from datetime import datetime, timezone

from libs.contracts.errors import NotFoundError
from libs.contracts.interfaces.research_run_repository import (
    ResearchRunRepositoryInterface,
)
from libs.contracts.research_run import (
    InvalidStatusTransitionError,
    ResearchRunRecord,
    ResearchRunResult,
    ResearchRunStatus,
    validate_status_transition,
)


class MockResearchRunRepository(ResearchRunRepositoryInterface):
    """
    In-memory mock implementation of ResearchRunRepositoryInterface.

    Thread-safe via a reentrant lock. Suitable for unit tests only.
    All data is stored in a dict keyed by run ID.

    Introspection helpers:
        - count(): total records stored
        - get_all(): list all records
        - clear(): remove all records
    """

    def __init__(self) -> None:
        self._store: dict[str, ResearchRunRecord] = {}
        self._lock = threading.Lock()

    # ------------------------------------------------------------------
    # Interface methods
    # ------------------------------------------------------------------

    def create(self, record: ResearchRunRecord) -> ResearchRunRecord:
        """
        Store a new research run record.

        Args:
            record: The record to store.

        Returns:
            The stored record.

        Raises:
            ValueError: If a record with the same id already exists.
        """
        with self._lock:
            if record.id in self._store:
                raise ValueError(f"Research run {record.id} already exists")
            self._store[record.id] = record
            return record

    def get_by_id(self, run_id: str) -> ResearchRunRecord | None:
        """
        Retrieve a record by ID.

        Args:
            run_id: The ULID to look up.

        Returns:
            The record if found, None otherwise.
        """
        with self._lock:
            return self._store.get(run_id)

    def update_status(
        self,
        run_id: str,
        new_status: ResearchRunStatus,
        *,
        error_message: str | None = None,
    ) -> ResearchRunRecord:
        """
        Transition a run to a new status.

        Args:
            run_id: ULID of the run.
            new_status: Target status.
            error_message: Error message for FAILED transitions.

        Returns:
            The updated record.

        Raises:
            NotFoundError: If the run does not exist.
            InvalidStatusTransitionError: If the transition is invalid.
        """
        with self._lock:
            existing = self._store.get(run_id)
            if existing is None:
                raise NotFoundError(f"Research run {run_id} not found")

            if not validate_status_transition(existing.status, new_status):
                raise InvalidStatusTransitionError(existing.status, new_status)

            now = datetime.now(timezone.utc)
            update_fields: dict = {
                "status": new_status,
                "updated_at": now,
            }

            if new_status == ResearchRunStatus.RUNNING:
                update_fields["started_at"] = now
            elif new_status in (
                ResearchRunStatus.COMPLETED,
                ResearchRunStatus.FAILED,
                ResearchRunStatus.CANCELLED,
            ):
                update_fields["completed_at"] = now

            if error_message is not None:
                update_fields["error_message"] = error_message

            # Pydantic frozen model — reconstruct with updated fields
            updated = existing.model_copy(update=update_fields)
            self._store[run_id] = updated
            return updated

    def save_result(self, run_id: str, result: ResearchRunResult) -> ResearchRunRecord:
        """
        Attach a result to a run.

        Args:
            run_id: ULID of the run.
            result: The engine result to attach.

        Returns:
            The updated record.

        Raises:
            NotFoundError: If the run does not exist.
        """
        with self._lock:
            existing = self._store.get(run_id)
            if existing is None:
                raise NotFoundError(f"Research run {run_id} not found")

            updated = existing.model_copy(
                update={
                    "result": result,
                    "updated_at": datetime.now(timezone.utc),
                }
            )
            self._store[run_id] = updated
            return updated

    def list_by_strategy(
        self,
        strategy_id: str,
        *,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[ResearchRunRecord], int]:
        """
        List runs for a strategy with pagination.

        Args:
            strategy_id: Filter by strategy ULID.
            limit: Max records.
            offset: Pagination offset.

        Returns:
            Tuple of (records, total_count).
        """
        with self._lock:
            matches = [r for r in self._store.values() if r.config.strategy_id == strategy_id]
            # Sort by created_at descending (newest first)
            matches.sort(key=lambda r: r.created_at, reverse=True)
            total = len(matches)
            page = matches[offset : offset + limit]
            return page, total

    def list_by_user(
        self,
        user_id: str,
        *,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[ResearchRunRecord], int]:
        """
        List runs for a user with pagination.

        Args:
            user_id: Filter by user ULID.
            limit: Max records.
            offset: Pagination offset.

        Returns:
            Tuple of (records, total_count).
        """
        with self._lock:
            matches = [r for r in self._store.values() if r.created_by == user_id]
            matches.sort(key=lambda r: r.created_at, reverse=True)
            total = len(matches)
            page = matches[offset : offset + limit]
            return page, total

    def count_by_status(self, status: ResearchRunStatus | None = None) -> int:
        """
        Count records, optionally filtered by status.

        Args:
            status: If provided, count only matching records.

        Returns:
            The count.
        """
        with self._lock:
            if status is None:
                return len(self._store)
            return sum(1 for r in self._store.values() if r.status == status)

    # ------------------------------------------------------------------
    # Introspection helpers (test-only)
    # ------------------------------------------------------------------

    def count(self) -> int:
        """Return total number of stored records."""
        with self._lock:
            return len(self._store)

    def get_all(self) -> list[ResearchRunRecord]:
        """Return all stored records, sorted by created_at descending."""
        with self._lock:
            records = list(self._store.values())
            records.sort(key=lambda r: r.created_at, reverse=True)
            return records

    def clear(self) -> None:
        """Remove all stored records."""
        with self._lock:
            self._store.clear()
