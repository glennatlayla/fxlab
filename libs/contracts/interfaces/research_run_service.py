"""
Research run service interface.

Purpose:
    Define the port (abstract interface) for research run orchestration.
    The service layer owns the business logic for submitting, executing,
    cancelling, and retrieving research runs.

Responsibilities:
    - submit_run: validate config, create record, dispatch to engine.
    - get_run: retrieve by ID.
    - cancel_run: transition PENDING/QUEUED → CANCELLED.
    - list_runs: paginated listing with filters.
    - get_run_result: retrieve completed result.

Does NOT:
    - Perform direct I/O or database access (delegates to repository).
    - Know about HTTP, frameworks, or routing.

Dependencies:
    - libs.contracts.research_run (ResearchRunRecord, ResearchRunConfig, etc.)

Example:
    service: ResearchRunServiceInterface = ResearchRunService(repo=repo, ...)
    record = service.submit_run(config, user_id="01HUSER...")
    result = service.get_run_result(record.id)
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from libs.contracts.research_run import (
    ResearchRunConfig,
    ResearchRunRecord,
    ResearchRunResult,
)


class ResearchRunServiceInterface(ABC):
    """
    Abstract interface for research run orchestration.

    Implementations coordinate between the repository (persistence),
    the research engines (backtest, walk-forward, Monte Carlo), and
    the status lifecycle.
    """

    @abstractmethod
    def submit_run(
        self,
        config: ResearchRunConfig,
        user_id: str,
        *,
        correlation_id: str | None = None,
    ) -> ResearchRunRecord:
        """
        Submit a new research run for execution.

        Creates a PENDING record, validates the configuration, and
        dispatches to the appropriate engine.

        Args:
            config: The research run configuration.
            user_id: ULID of the user submitting the run.
            correlation_id: Optional request correlation ID for tracing.

        Returns:
            The created ResearchRunRecord in PENDING or QUEUED status.

        Raises:
            ValidationError: If the config is invalid for the selected run type.
        """

    @abstractmethod
    def get_run(self, run_id: str) -> ResearchRunRecord | None:
        """
        Retrieve a research run record by ID.

        Args:
            run_id: ULID of the research run.

        Returns:
            The record if found, None otherwise.
        """

    @abstractmethod
    def cancel_run(
        self,
        run_id: str,
        *,
        correlation_id: str | None = None,
    ) -> ResearchRunRecord:
        """
        Cancel a research run that has not yet completed.

        Only PENDING and QUEUED runs can be cancelled.

        Args:
            run_id: ULID of the research run to cancel.
            correlation_id: Optional request correlation ID for tracing.

        Returns:
            The updated record with CANCELLED status.

        Raises:
            NotFoundError: If the run_id does not exist.
            InvalidStatusTransitionError: If the run is already terminal.
        """

    @abstractmethod
    def list_runs(
        self,
        *,
        strategy_id: str | None = None,
        user_id: str | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> tuple[list[ResearchRunRecord], int]:
        """
        List research runs with optional filters and pagination.

        Args:
            strategy_id: Filter by strategy ULID.
            user_id: Filter by creating user ULID.
            limit: Maximum records to return.
            offset: Pagination offset.

        Returns:
            Tuple of (records, total_count).
        """

    @abstractmethod
    def get_run_result(self, run_id: str) -> ResearchRunResult | None:
        """
        Retrieve the result of a completed research run.

        Args:
            run_id: ULID of the research run.

        Returns:
            The result if the run is COMPLETED, None if not found or
            not yet completed.
        """
