"""
Research run repository interface.

Purpose:
    Define the port (abstract interface) for research run persistence.
    Concrete implementations (SQL, mock) implement this interface.

Responsibilities:
    - CRUD operations for research run records.
    - List/filter by strategy, user, and status.
    - Status transition with validation.

Does NOT:
    - Contain business logic or orchestration.
    - Know about specific database technologies.

Dependencies:
    - libs.contracts.research_run (ResearchRunRecord, ResearchRunStatus,
      ResearchRunResult)

Example:
    repo: ResearchRunRepositoryInterface = SqlResearchRunRepository(db)
    record = repo.create(record)
    record = repo.get_by_id("01HRUN...")
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from libs.contracts.research_run import (
    ResearchRunRecord,
    ResearchRunResult,
    ResearchRunStatus,
)


class ResearchRunRepositoryInterface(ABC):
    """
    Abstract interface for research run persistence.

    All methods raise NotFoundError if a referenced run_id does not exist
    (except create, which creates it).

    Concrete implementations must handle:
    - Thread-safe persistence
    - Status transition validation
    - Serialization of nested Pydantic models (config, result)
    """

    @abstractmethod
    def create(self, record: ResearchRunRecord) -> ResearchRunRecord:
        """
        Persist a new research run record.

        Args:
            record: The research run record to create. Must have a unique id.

        Returns:
            The persisted record (may include server-generated fields).

        Raises:
            ValueError: If a record with the same id already exists.
        """

    @abstractmethod
    def get_by_id(self, run_id: str) -> ResearchRunRecord | None:
        """
        Retrieve a research run record by its ULID.

        Args:
            run_id: The ULID of the research run.

        Returns:
            The record if found, None otherwise.
        """

    @abstractmethod
    def update_status(
        self,
        run_id: str,
        new_status: ResearchRunStatus,
        *,
        error_message: str | None = None,
    ) -> ResearchRunRecord:
        """
        Transition a research run to a new status.

        Args:
            run_id: The ULID of the research run to update.
            new_status: The target status.
            error_message: Optional error message for FAILED transitions.

        Returns:
            The updated record.

        Raises:
            NotFoundError: If the run_id does not exist.
            InvalidStatusTransitionError: If the transition is not valid.
        """

    @abstractmethod
    def save_result(self, run_id: str, result: ResearchRunResult) -> ResearchRunRecord:
        """
        Attach a result to a completed research run.

        Args:
            run_id: The ULID of the research run.
            result: The engine result to attach.

        Returns:
            The updated record with result attached.

        Raises:
            NotFoundError: If the run_id does not exist.
        """

    @abstractmethod
    def list_by_strategy(
        self,
        strategy_id: str,
        *,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[ResearchRunRecord], int]:
        """
        List research runs for a specific strategy.

        Args:
            strategy_id: Filter by this strategy ULID.
            limit: Maximum records to return.
            offset: Pagination offset.

        Returns:
            Tuple of (records, total_count).
        """

    @abstractmethod
    def list_by_user(
        self,
        user_id: str,
        *,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[ResearchRunRecord], int]:
        """
        List research runs created by a specific user.

        Args:
            user_id: Filter by this user ULID.
            limit: Maximum records to return.
            offset: Pagination offset.

        Returns:
            Tuple of (records, total_count).
        """

    @abstractmethod
    def list_by_strategy_id(
        self,
        *,
        strategy_id: str,
        page: int,
        page_size: int,
    ) -> tuple[list[ResearchRunRecord], int]:
        """
        Page research runs for a strategy and return the matching total count.

        Mirrors the M2.D5 ``SqlStrategyRepository.list_with_total`` shape so
        the route layer can build a ``StrategyRunsPage`` envelope without
        reaching into the repository's internals. Two queries hit the
        database — one ``count(*)`` over the filtered set, one bounded
        ``select`` for the page itself — sharing the same filter chain so
        ``total_count`` is always consistent with the page rows.

        Implementations MUST:
            * Order rows by ``created_at`` descending (newest first).
            * Treat ``page < 1`` as ``page = 1`` for offset purposes (the
              route layer enforces ``page >= 1`` in production but the
              repository must remain safe under direct tests).
            * Treat ``page_size < 1`` as a programmer error and surface
              it via Python's normal exception flow.

        Args:
            strategy_id: Filter by strategy ULID.
            page: 1-based page index.
            page_size: Maximum runs per page.

        Returns:
            Tuple of ``(records, total_count)`` — the page rows ordered
            newest first and the total count of rows matching the filter.
        """

    @abstractmethod
    def count_by_status(self, status: ResearchRunStatus | None = None) -> int:
        """
        Count research runs, optionally filtered by status.

        Args:
            status: If provided, count only runs with this status.
                If None, count all runs.

        Returns:
            The count of matching records.
        """
