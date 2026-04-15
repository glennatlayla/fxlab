"""
Research run orchestration service.

Purpose:
    Coordinate research run submission, status management, cancellation,
    listing, and result retrieval. Acts as the single entry point for
    all research run business logic.

Responsibilities:
    - submit_run: generate ULID, create PENDING record, transition to QUEUED,
      log structured events.
    - get_run: delegate to repository for single-record retrieval.
    - cancel_run: validate the run is in a cancellable state
      (PENDING or QUEUED), transition to CANCELLED.
    - list_runs: paginated listing with strategy_id or user_id filters.
    - get_run_result: retrieve the result of a completed run; return None
      if the run does not exist or has no result yet.

Does NOT:
    - Execute research engines directly (engine dispatch is a separate
      worker concern — see services/worker/research/).
    - Access the database directly (delegates to repository).
    - Know about HTTP, FastAPI, or routing.

Dependencies:
    - ResearchRunRepositoryInterface (injected): persistence layer.
    - ulid: ULID generation for run IDs.
    - structlog: structured logging.

Error conditions:
    - cancel_run: NotFoundError if run_id missing,
      InvalidStatusTransitionError if run is in a non-cancellable state.
    - submit_run: ValidationError if config is invalid (Pydantic enforced).

Example:
    repo = SqlResearchRunRepository(db=session)
    service = ResearchRunService(repo=repo)
    record = service.submit_run(config, user_id="01HUSER...")
    result = service.get_run_result(record.id)
"""

from __future__ import annotations

import structlog
import ulid as _ulid

from libs.contracts.errors import NotFoundError
from libs.contracts.interfaces.research_run_repository import (
    ResearchRunRepositoryInterface,
)
from libs.contracts.interfaces.research_run_service import (
    ResearchRunServiceInterface,
)
from libs.contracts.research_run import (
    ResearchRunConfig,
    ResearchRunRecord,
    ResearchRunResult,
    ResearchRunStatus,
)

logger = structlog.get_logger(__name__)


class ResearchRunService(ResearchRunServiceInterface):
    """
    Concrete implementation of ResearchRunServiceInterface.

    Orchestrates the research run lifecycle: submission, queuing,
    cancellation, listing, and result retrieval. All persistence
    is delegated to the injected repository.

    Attributes:
        _repo: ResearchRunRepositoryInterface for data persistence.

    Example:
        service = ResearchRunService(repo=repo)
        record = service.submit_run(config, user_id="01HUSER...")
    """

    def __init__(self, repo: ResearchRunRepositoryInterface) -> None:
        self._repo = repo

    # ------------------------------------------------------------------
    # submit_run
    # ------------------------------------------------------------------

    def submit_run(
        self,
        config: ResearchRunConfig,
        user_id: str,
        *,
        correlation_id: str | None = None,
    ) -> ResearchRunRecord:
        """
        Submit a new research run for execution.

        Generates a ULID, creates a PENDING record in the repository,
        then immediately transitions to QUEUED (ready for engine pickup).

        Args:
            config: The research run configuration (run type, symbols, etc.).
            user_id: ULID of the user submitting the run.
            correlation_id: Optional request correlation ID for tracing.

        Returns:
            The created ResearchRunRecord in QUEUED status.

        Raises:
            ValidationError: If the config is invalid (enforced by Pydantic).

        Example:
            record = service.submit_run(config, user_id="01HUSER...")
            assert record.status == ResearchRunStatus.QUEUED
        """
        run_id = str(_ulid.ULID())

        record = ResearchRunRecord(
            id=run_id,
            config=config,
            status=ResearchRunStatus.PENDING,
            created_by=user_id,
        )

        self._repo.create(record)

        logger.info(
            "research_run.submitted",
            run_id=run_id,
            run_type=config.run_type.value,
            strategy_id=config.strategy_id,
            user_id=user_id,
            correlation_id=correlation_id,
            component="research_run_service",
        )

        # Transition to QUEUED — ready for engine pickup.
        queued_record = self._repo.update_status(run_id, ResearchRunStatus.QUEUED)

        logger.info(
            "research_run.queued",
            run_id=run_id,
            correlation_id=correlation_id,
            component="research_run_service",
        )

        return queued_record

    # ------------------------------------------------------------------
    # get_run
    # ------------------------------------------------------------------

    def get_run(self, run_id: str) -> ResearchRunRecord | None:
        """
        Retrieve a research run record by ID.

        Args:
            run_id: ULID of the research run.

        Returns:
            The record if found, None otherwise.

        Example:
            record = service.get_run("01HRUN...")
        """
        return self._repo.get_by_id(run_id)

    # ------------------------------------------------------------------
    # cancel_run
    # ------------------------------------------------------------------

    def cancel_run(
        self,
        run_id: str,
        *,
        correlation_id: str | None = None,
    ) -> ResearchRunRecord:
        """
        Cancel a research run that has not yet completed.

        Only PENDING and QUEUED runs can be cancelled. RUNNING and
        terminal states will raise InvalidStatusTransitionError.

        Args:
            run_id: ULID of the research run to cancel.
            correlation_id: Optional request correlation ID for tracing.

        Returns:
            The updated record with CANCELLED status.

        Raises:
            NotFoundError: If the run_id does not exist.
            InvalidStatusTransitionError: If the run is not cancellable.

        Example:
            cancelled = service.cancel_run("01HRUN...")
            assert cancelled.status == ResearchRunStatus.CANCELLED
        """
        # Retrieve to validate existence before transition.
        existing = self._repo.get_by_id(run_id)
        if existing is None:
            raise NotFoundError(f"Research run {run_id} not found")

        logger.info(
            "research_run.cancel_requested",
            run_id=run_id,
            current_status=existing.status.value,
            correlation_id=correlation_id,
            component="research_run_service",
        )

        # update_status validates the transition; raises
        # InvalidStatusTransitionError if illegal.
        cancelled = self._repo.update_status(run_id, ResearchRunStatus.CANCELLED)

        logger.info(
            "research_run.cancelled",
            run_id=run_id,
            correlation_id=correlation_id,
            component="research_run_service",
        )

        return cancelled

    # ------------------------------------------------------------------
    # list_runs
    # ------------------------------------------------------------------

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

        If strategy_id is provided, filters by strategy. If user_id is
        provided, filters by creating user. If neither is provided,
        returns runs filtered by user_id (defaults to returning empty
        since no filter means no match).

        Args:
            strategy_id: Filter by strategy ULID.
            user_id: Filter by creating user ULID.
            limit: Maximum records to return (default 50).
            offset: Pagination offset (default 0).

        Returns:
            Tuple of (records, total_count).

        Example:
            runs, total = service.list_runs(strategy_id="01HSTRAT...")
        """
        if strategy_id is not None:
            return self._repo.list_by_strategy(strategy_id, limit=limit, offset=offset)
        if user_id is not None:
            return self._repo.list_by_user(user_id, limit=limit, offset=offset)
        # No filter specified — return empty. The API layer should
        # require at least one filter to prevent unbounded queries.
        return [], 0

    # ------------------------------------------------------------------
    # get_run_result
    # ------------------------------------------------------------------

    def get_run_result(self, run_id: str) -> ResearchRunResult | None:
        """
        Retrieve the result of a completed research run.

        Args:
            run_id: ULID of the research run.

        Returns:
            The result if the run exists and has a result attached,
            None if the run does not exist or has no result yet.

        Example:
            result = service.get_run_result("01HRUN...")
            if result:
                print(result.summary_metrics)
        """
        record = self._repo.get_by_id(run_id)
        if record is None:
            return None
        return record.result
