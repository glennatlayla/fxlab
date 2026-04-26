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
from libs.contracts.run_results import (
    EquityCurveResponse,
    RunCancelResult,
    RunMetrics,
    StrategyRunsPage,
    TradeBlotterPage,
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

    # ------------------------------------------------------------------
    # Results sub-resources (M2.C3)
    # ------------------------------------------------------------------

    @abstractmethod
    def get_equity_curve(self, run_id: str) -> EquityCurveResponse:
        """
        Build the equity-curve sub-resource for a completed run.

        Args:
            run_id: ULID of the research run.

        Returns:
            EquityCurveResponse with samples ordered ascending by
            timestamp.

        Raises:
            NotFoundError: If no record exists for ``run_id``.
            RunNotCompletedError: If the run is not COMPLETED.
        """

    @abstractmethod
    def get_blotter(
        self,
        run_id: str,
        *,
        page: int = 1,
        page_size: int = 100,
    ) -> TradeBlotterPage:
        """
        Build a paginated trade-blotter page for a completed run.

        Trades MUST be sorted deterministically so identical queries
        return identical pages.

        Args:
            run_id: ULID of the research run.
            page: 1-based page index.
            page_size: Maximum trades per page.

        Returns:
            TradeBlotterPage. Pages beyond the last populated page
            return an empty ``trades`` list with totals still
            populated.

        Raises:
            NotFoundError: If no record exists for ``run_id``.
            RunNotCompletedError: If the run is not COMPLETED.
            ValueError: If ``page`` < 1 or ``page_size`` < 1.
        """

    @abstractmethod
    def list_runs_for_strategy(
        self,
        strategy_id: str,
        *,
        page: int,
        page_size: int,
    ) -> StrategyRunsPage:
        """
        Return one page of the recent-runs history for a given strategy.

        Powers the "Recent runs" section on the StrategyDetail page. The
        service projects the persistence-layer
        :class:`ResearchRunRecord` rows into the wire-shaped
        :class:`StrategyRunsPage` (status, timestamps, headline metrics)
        so the route layer can serialise them directly.

        Implementations MUST:
            * Order rows by ``created_at`` descending (newest first).
            * Populate ``total_count`` and ``total_pages`` even when the
              requested page is empty so the UI can disable the "Next"
              affordance without re-querying.
            * Default missing summary fields to ``None`` rather than
              fabricating zero values — consumers must be able to
              distinguish "engine produced 0" from "engine did not
              report this metric".

        Args:
            strategy_id: ULID of the strategy whose run history to fetch.
            page: 1-based page index.
            page_size: Maximum runs per page.

        Returns:
            :class:`StrategyRunsPage` — already validated against the
            response schema, ready to ``model_dump`` for JSON output.
        """

    @abstractmethod
    def get_metrics(self, run_id: str) -> RunMetrics:
        """
        Build the headline-metrics sub-resource for a completed run.

        Args:
            run_id: ULID of the research run.

        Returns:
            RunMetrics with all available fields populated.

        Raises:
            NotFoundError: If no record exists for ``run_id``.
            RunNotCompletedError: If the run is not COMPLETED.
        """

    @abstractmethod
    async def cancel_run_with_abort(
        self,
        run_id: str,
        *,
        requested_by: str,
        correlation_id: str | None = None,
    ) -> RunCancelResult:
        """
        Cancel a research run, aborting any in-flight executor task.

        Powers ``POST /runs/{run_id}/cancel``. Distinct from the legacy
        sync :meth:`cancel_run` (which only allows PENDING / QUEUED to
        terminate without touching the executor pool) because this
        method also tears down the in-flight asyncio task before writing
        the terminal CANCELLED row, so a RUNNING run can be aborted
        cleanly.

        Behaviour:
            * RUNNING — call :meth:`RunExecutorPool.cancel_run` to abort
              the in-flight task, then transition the row to CANCELLED.
            * PENDING / QUEUED — transition the row to CANCELLED
              directly; the pool reports no in-flight task and the
              service logs a debug entry (no abort needed).
            * COMPLETED / FAILED / CANCELLED — no-op; return
              ``cancelled=False`` with ``reason="terminal_state"``.

        Args:
            run_id: ULID of the research run to cancel.
            requested_by: ULID (or other identifier) of the operator
                requesting the cancel; surfaced in audit logs.
            correlation_id: Optional request correlation ID for tracing.

        Returns:
            :class:`RunCancelResult` describing the outcome.

        Raises:
            NotFoundError: If no record exists for ``run_id``.
        """
