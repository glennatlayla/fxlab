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

from collections.abc import Callable
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import TYPE_CHECKING, Any

import structlog
import ulid as _ulid

from libs.contracts.errors import FXLabError, NotFoundError
from libs.contracts.experiment_plan import ExperimentPlan
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
    ResearchRunType,
)
from libs.contracts.run_results import (
    EquityCurvePoint,
    EquityCurveResponse,
    RunMetrics,
    RunSummaryItem,
    RunSummaryMetrics,
    StrategyRunsPage,
    TradeBlotterEntry,
    TradeBlotterPage,
)
from libs.strategy_ir.interfaces.dataset_resolver_interface import (
    ResolvedDataset,
)

if TYPE_CHECKING:  # pragma: no cover -- typing-only import to avoid cycle
    from services.api.services.run_executor_pool import RunExecutorPool
    from services.api.services.synthetic_backtest_executor import (
        SyntheticBacktestExecutor,
    )

#: Type alias for the IR-loader callable injected into the service.
#: Given a strategy ULID, returns the parsed IR dict (the same shape
#: the executor expects). Raising ``NotFoundError`` is the expected way
#: to signal a missing strategy.
IRLoader = Callable[[str], dict[str, Any]]


class RunNotCompletedError(FXLabError):
    """
    Raised when a results sub-resource is requested for a run that exists
    but has not yet COMPLETED.

    The route layer maps this to HTTP 409 Conflict so callers can
    distinguish "run does not exist" (404) from "run exists but its
    results are not ready yet" (409).

    Attributes:
        run_id: ULID of the run that was queried.
        status: Current status of the run.
    """

    def __init__(self, run_id: str, status: ResearchRunStatus) -> None:
        super().__init__(
            f"Research run {run_id} is in status {status.value}; results are only available "
            f"once the run has completed."
        )
        self.run_id = run_id
        self.status = status


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

    def __init__(
        self,
        repo: ResearchRunRepositoryInterface,
        *,
        executor: SyntheticBacktestExecutor | None = None,
        ir_loader: IRLoader | None = None,
        executor_pool: RunExecutorPool | None = None,
    ) -> None:
        """
        Construct the service.

        Args:
            repo: Persistence layer.
            executor: Optional :class:`SyntheticBacktestExecutor`. When
                provided alongside ``ir_loader``, calls to
                :meth:`submit_from_ir` with ``auto_execute=True``
                (the default) will run the backtest synchronously and
                attach the result to the run record before returning.
                When ``None``, ``auto_execute`` falls back to QUEUED-only
                behaviour (the legacy M2.C2 contract).
            ir_loader: Optional callable that resolves a ``strategy_id``
                to a parsed IR dict. Required for auto-execute to work.
                Typically a thin closure around
                :meth:`StrategyService.get_strategy` that returns the
                ``parsed_code`` field.
            executor_pool: Optional :class:`RunExecutorPool`. When wired,
                :meth:`submit_from_ir` with ``auto_execute=False`` will
                queue the run AND submit it to the pool for background
                execution -- the route layer maps that to HTTP 202
                Accepted. When ``None``, ``auto_execute=False`` keeps
                the legacy M2.C2 contract: queue only, no execution.
        """
        self._repo = repo
        self._executor = executor
        self._ir_loader = ir_loader
        self._executor_pool = executor_pool

    @property
    def executor_pool(self) -> RunExecutorPool | None:
        """
        Read-only accessor for the optional background pool.

        Tests use this to await pool drain after a deferred submission;
        production code does not need it.
        """
        return self._executor_pool

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
    # submit_from_ir (M2.C2)
    # ------------------------------------------------------------------

    def submit_from_ir(
        self,
        strategy_id: str,
        experiment_plan: ExperimentPlan,
        resolved_dataset: ResolvedDataset,
        user_id: str,
        *,
        correlation_id: str | None = None,
        auto_execute: bool = True,
    ) -> ResearchRunRecord:
        """
        Submit a research run derived from a parsed ExperimentPlan.

        This is the M2.C2 entry point used by ``POST /runs/from-ir``.
        It maps the experiment plan's data-selection block to a
        :class:`ResearchRunConfig`, then delegates to
        :meth:`submit_run` so the standard PENDING -> QUEUED transition
        and structured logging are preserved.

        Run-type selection rule for this tranche: if
        ``plan.validation.walk_forward.enabled`` is True we submit a
        ``WALK_FORWARD`` run, otherwise a plain ``BACKTEST``. The
        engine-config bodies (BacktestConfig / WalkForwardConfig) are
        intentionally left ``None`` here -- a future tranche will
        translate the plan's validation block into the concrete
        engine configs. The acceptance test in this tranche only
        requires that the run is created, queued, and routed to the
        correct engine type.

        Args:
            strategy_id: ULID of the strategy this plan targets.
            experiment_plan: Parsed and validated
                :class:`ExperimentPlan` (caller owns parsing).
            resolved_dataset: Output of
                :meth:`DatasetResolverInterface.resolve` for
                ``experiment_plan.data_selection.dataset_ref``.
                Caller owns the resolution step so a missing dataset
                surfaces as HTTP 404 in the route layer.
            user_id: ULID of the user submitting the run.
            correlation_id: Optional request correlation ID.
            auto_execute: When True (default) and both
                ``executor`` + ``ir_loader`` were provided to
                :meth:`__init__`, run the synthetic backtest
                synchronously after queuing the run -- transition
                QUEUED -> RUNNING -> COMPLETED (or FAILED) and attach
                the populated :class:`ResearchRunResult` so the M2.C3
                ``GET /runs/{id}/results/*`` endpoints immediately
                return real data. Set to False (or pass
                ``defer_execution=1`` from the route) to keep the
                legacy M2.C2 QUEUED-only behaviour, e.g. for callers
                that own their own execution dispatch.

        Returns:
            The created :class:`ResearchRunRecord`. When
            ``auto_execute`` and the executor are both wired the
            returned record carries ``status=COMPLETED`` and a
            populated ``result``. Otherwise ``status=QUEUED`` and
            ``result=None``.

        Raises:
            FXLabError: When ``auto_execute=True`` but the executor
                raises during the run. The run record is transitioned
                to FAILED with the error message persisted before
                this exception propagates so callers (and the route's
                500 handler) can rely on the persisted FAILED state.

        Example::

            record = service.submit_from_ir(
                strategy_id="01HSTRAT...",
                experiment_plan=plan,
                resolved_dataset=resolver.resolve(plan.data_selection.dataset_ref),
                user_id="01HUSER...",
            )
            assert record.status == ResearchRunStatus.COMPLETED
        """
        # Walk-forward gets routed to its own engine; otherwise treat
        # the plan as a single backtest. We never silently downgrade --
        # if the plan asks for walk-forward we honour it.
        if experiment_plan.validation.walk_forward.enabled:
            run_type = ResearchRunType.WALK_FORWARD
        else:
            run_type = ResearchRunType.BACKTEST

        # Metadata pins enough of the plan for downstream audit /
        # readiness reports to find the originating artifact without
        # re-parsing the full plan body. The full plan body itself is
        # not embedded here -- it lives in the strategy + plan
        # repositories owned by Tracks A and E.
        metadata: dict[str, object] = {
            "source": "experiment_plan",
            "experiment_plan_strategy_name": (experiment_plan.strategy_ref.strategy_name),
            "experiment_plan_strategy_version": (experiment_plan.strategy_ref.strategy_version),
            "experiment_plan_dataset_ref": (experiment_plan.data_selection.dataset_ref),
            "experiment_plan_dataset_id": resolved_dataset.dataset_id,
            "experiment_plan_random_seed": (experiment_plan.run_metadata.random_seed),
            "experiment_plan_run_purpose": (experiment_plan.run_metadata.run_purpose),
        }

        # Engine-config bodies (BacktestConfig / WalkForwardConfig /
        # MonteCarloConfig) are intentionally left ``None`` at this
        # tranche. A future tranche translates the plan's validation
        # block into the concrete engine configs (see method docstring).
        # ``strategy_version_id`` is None because ``ResearchRunConfig``
        # documents that as "latest version if omitted" -- the
        # experiment_plan's ``strategy_ref.strategy_version`` is a
        # semver-style label, not the ULID this field expects, so we
        # let the downstream resolver pick the latest version.
        # ``signal_strategy_id`` mirrors ``strategy_id`` because at
        # this tranche every IR-derived run uses the strategy's own
        # signal pipeline (see WalkForwardConfig docstring example
        # which uses the same pattern).
        config = ResearchRunConfig(
            run_type=run_type,
            strategy_id=strategy_id,
            strategy_version_id=None,
            signal_strategy_id=strategy_id,
            symbols=resolved_dataset.symbols,
            initial_equity=Decimal("100000"),
            backtest_config=None,
            walk_forward_config=None,
            monte_carlo_config=None,
            metadata=metadata,
        )

        logger.info(
            "research_run.submit_from_ir.called",
            strategy_id=strategy_id,
            dataset_ref=experiment_plan.data_selection.dataset_ref,
            dataset_id=resolved_dataset.dataset_id,
            symbol_count=len(resolved_dataset.symbols),
            run_type=run_type.value,
            user_id=user_id,
            correlation_id=correlation_id,
            auto_execute=auto_execute,
            executor_wired=self._executor is not None,
            component="research_run_service",
        )

        queued = self.submit_run(config, user_id, correlation_id=correlation_id)

        # Deferred-execution path: when the caller explicitly opted out
        # of synchronous execution AND the pool is wired, hand the run
        # off so it actually runs in the background. Without the pool,
        # the legacy QUEUED-only contract is preserved (caller owns
        # dispatch). Without ir_loader the worker cannot build a
        # request, so we degrade to QUEUED-only there too.
        if not auto_execute:
            if self._executor_pool is not None and self._ir_loader is not None:
                from services.api.services.run_executor_pool import (
                    build_submission,
                )

                self._executor_pool.submit(
                    build_submission(
                        run_id=queued.id,
                        strategy_id=strategy_id,
                        experiment_plan=experiment_plan,
                        resolved_dataset=resolved_dataset,
                        correlation_id=correlation_id,
                    )
                )
                logger.info(
                    "research_run.submit_from_ir.deferred_to_pool",
                    run_id=queued.id,
                    strategy_id=strategy_id,
                    correlation_id=correlation_id,
                    component="research_run_service",
                )
            else:
                logger.info(
                    "research_run.submit_from_ir.deferred_no_pool",
                    run_id=queued.id,
                    strategy_id=strategy_id,
                    pool_wired=self._executor_pool is not None,
                    ir_loader_wired=self._ir_loader is not None,
                    correlation_id=correlation_id,
                    component="research_run_service",
                    detail="defer_execution requested but background pool "
                    "and/or ir_loader unwired; run remains QUEUED for "
                    "external dispatch.",
                )
            return queued

        # Auto-execute path: only fires when explicitly requested AND
        # both the executor and the IR loader were injected. We do not
        # silently swap to QUEUED-only when the executor is missing;
        # instead we log loudly so an operator can spot misconfiguration.
        if self._executor is None or self._ir_loader is None:
            logger.warning(
                "research_run.submit_from_ir.auto_execute_skipped",
                run_id=queued.id,
                strategy_id=strategy_id,
                executor_wired=self._executor is not None,
                ir_loader_wired=self._ir_loader is not None,
                correlation_id=correlation_id,
                component="research_run_service",
                detail="auto_execute=True but executor or ir_loader is unwired; "
                "run remains QUEUED.",
            )
            return queued

        return self._execute_synchronously(
            run_id=queued.id,
            strategy_id=strategy_id,
            experiment_plan=experiment_plan,
            resolved_dataset=resolved_dataset,
            correlation_id=correlation_id,
        )

    # ------------------------------------------------------------------
    # _execute_synchronously (M2.D3 wire-up of the M3.X1 executor)
    # ------------------------------------------------------------------

    def _execute_synchronously(
        self,
        *,
        run_id: str,
        strategy_id: str,
        experiment_plan: ExperimentPlan,
        resolved_dataset: ResolvedDataset,
        correlation_id: str | None,
    ) -> ResearchRunRecord:
        """
        Run the synthetic backtest in the calling thread and persist
        the result onto the run record.

        Lifecycle:
            QUEUED -> RUNNING (started_at stamped)
                   -> COMPLETED (completed_at stamped + result attached)
                   on success.
            QUEUED -> RUNNING -> FAILED (error_message persisted) on
                   any executor exception.

        Args:
            run_id: ULID returned by :meth:`submit_run`.
            strategy_id: ULID used to fetch the IR via
                ``self._ir_loader``.
            experiment_plan: Source of the seed and the holdout split
                window the executor will replay over.
            resolved_dataset: Source of the symbol set the executor
                will trade against.
            correlation_id: Propagated through every log line.

        Returns:
            The persisted record with terminal status (COMPLETED or
            FAILED). On FAILED we still RETURN the record (rather than
            raising) so the route layer can decide whether to translate
            the persisted error into HTTP 500 or surface the run id and
            let the client poll. Today the route translates a FAILED
            run into HTTP 500; if the executor itself raised, we
            re-raise the wrapped error after persisting FAILED.

        Raises:
            FXLabError: when the executor raised. The run row is
                already in FAILED state; the route's exception handler
                surfaces this as HTTP 500 with the error message.
        """
        # Local imports defer the executor's heavyweight strategy_ir
        # imports until this method is actually called -- keeps cold
        # service construction cheap and avoids the import cycle with
        # services.cli.run_synthetic_backtest.
        from services.api.services.synthetic_backtest_executor import (
            SyntheticBacktestError,
            SyntheticBacktestRequest,
        )

        assert self._executor is not None  # noqa: S101 -- guarded by caller
        assert self._ir_loader is not None  # noqa: S101 -- guarded by caller

        # 1. Transition QUEUED -> RUNNING. The repository stamps
        #    started_at automatically on this transition (see
        #    SqlResearchRunRepository.update_status).
        try:
            self._repo.update_status(run_id, ResearchRunStatus.RUNNING)
        except Exception as exc:  # pragma: no cover -- defensive
            # If we cannot even transition to RUNNING, leave the row in
            # QUEUED and surface the error. Tests for this branch live
            # in the repo, not the service.
            logger.error(
                "research_run.execute.queued_to_running_failed",
                run_id=run_id,
                error=str(exc),
                exc_info=True,
                component="research_run_service",
            )
            raise

        # 2. Fetch the IR + build the executor request from the
        #    experiment plan and resolved dataset.
        try:
            ir_dict = self._ir_loader(strategy_id)
        except Exception as exc:
            return self._mark_failed(
                run_id,
                f"failed to load IR for strategy {strategy_id}: {type(exc).__name__}: {exc}",
                correlation_id=correlation_id,
                exc=exc,
            )

        symbols = list(resolved_dataset.symbols)
        seed = experiment_plan.run_metadata.random_seed
        # Window: prefer the holdout split (most recent / smallest), then
        # out-of-sample, then in-sample. Synthetic-data backtests do not
        # benefit from longer-than-needed windows so we pick the smallest
        # configured window the plan declares.
        start_d, end_d = self._select_replay_window(experiment_plan)

        # Timeframe: read from the IR's data_requirements.primary_timeframe
        # via the executor's normalisation table; we pass the raw IR
        # value here and let the executor translate.
        timeframe = self._extract_primary_timeframe(ir_dict)

        request = SyntheticBacktestRequest(
            strategy_ir_dict=ir_dict,
            symbols=symbols,
            timeframe=timeframe,
            start=start_d,
            end=end_d,
            seed=seed,
            starting_balance=Decimal("100000"),
            deployment_id=f"run-{run_id}",
        )

        # 3. Execute. Wrap every executor exception in our typed
        #    FXLabError for the route's 500 path; persist FAILED before
        #    re-raising.
        try:
            backtest_result = self._executor.execute(request)
        except SyntheticBacktestError as exc:
            failed_record = self._mark_failed(
                run_id,
                f"backtest execution failed: {exc}",
                correlation_id=correlation_id,
                exc=exc,
            )
            raise FXLabError(str(exc)) from exc
        except Exception as exc:
            # Any non-SyntheticBacktestError is a programming error
            # (the executor should have wrapped it). Persist FAILED so
            # the row reflects reality, then re-raise.
            failed_record = self._mark_failed(
                run_id,
                f"backtest execution raised unexpectedly: {type(exc).__name__}: {exc}",
                correlation_id=correlation_id,
                exc=exc,
            )
            del failed_record
            raise

        # 4. Build the ResearchRunResult and persist it.
        result = ResearchRunResult(
            backtest_result=backtest_result,
            summary_metrics={
                "total_return_pct": str(backtest_result.total_return_pct),
                "max_drawdown_pct": str(backtest_result.max_drawdown_pct),
                "sharpe_ratio": str(backtest_result.sharpe_ratio),
                "win_rate": str(backtest_result.win_rate),
                "profit_factor": str(backtest_result.profit_factor),
                "total_trades": backtest_result.total_trades,
                "final_equity": str(backtest_result.final_equity),
                "bars_processed": backtest_result.bars_processed,
            },
            completed_at=datetime.now(timezone.utc),
        )
        self._repo.save_result(run_id, result)
        completed = self._repo.update_status(run_id, ResearchRunStatus.COMPLETED)

        logger.info(
            "research_run.execute.completed",
            run_id=run_id,
            strategy_id=strategy_id,
            trade_count=backtest_result.total_trades,
            equity_points=len(backtest_result.equity_curve),
            total_return_pct=str(backtest_result.total_return_pct),
            correlation_id=correlation_id,
            component="research_run_service",
        )

        return completed

    @staticmethod
    def _select_replay_window(plan: ExperimentPlan) -> tuple[date, date]:
        """
        Pick the (start, end) date pair the synthetic backtest will
        replay over.

        Selection rule: prefer the holdout split (the most recent /
        most relevant window for a smoke test); fall back to
        out_of_sample then in_sample. Each split is a string pair on
        the IR -- we parse YYYY-MM-DD here.

        If parsing fails (the IR carries malformed dates), fall back
        to the last 60 days ending today so the executor still has a
        valid window. This is defensive, not policy: a production
        engine config will surface the error instead.
        """
        for split_name in ("holdout", "out_of_sample", "in_sample"):
            split = getattr(plan.splits, split_name, None)
            if split is None:
                continue
            try:
                start = datetime.strptime(split.start, "%Y-%m-%d").date()
                end = datetime.strptime(split.end, "%Y-%m-%d").date()
            except ValueError:
                continue
            if end >= start:
                return start, end
        fallback_end = datetime.now(timezone.utc).date()
        fallback_start = fallback_end - timedelta(days=60)
        return fallback_start, fallback_end

    @staticmethod
    def _extract_primary_timeframe(ir_dict: dict[str, Any]) -> str:
        """
        Pull ``data_requirements.primary_timeframe`` out of the raw IR
        dict. Falls back to ``"H1"`` (the synthetic provider's most
        common pair) when the field is missing -- the executor will
        raise SyntheticBacktestError if the value is not in its
        normalisation table, so a wrong fallback fails loudly rather
        than producing silent wrong output.
        """
        data_req = ir_dict.get("data_requirements", {})
        if isinstance(data_req, dict):
            tf = data_req.get("primary_timeframe")
            if isinstance(tf, str) and tf:
                return tf
        return "H1"

    def _mark_failed(
        self,
        run_id: str,
        error_message: str,
        *,
        correlation_id: str | None,
        exc: Exception,
    ) -> ResearchRunRecord:
        """
        Persist a FAILED transition + error_message and log the cause.

        Args:
            run_id: The ULID to mark FAILED.
            error_message: Operator-readable cause for the run row.
            correlation_id: Propagated to the log line.
            exc: The exception that triggered the failure; logged with
                ``exc_info`` so the stack trace survives in structured
                logs.

        Returns:
            The persisted record after the transition. The caller may
            re-raise for HTTP 500 propagation.
        """
        logger.error(
            "research_run.execute.failed",
            run_id=run_id,
            error=error_message,
            exc_info=exc,
            correlation_id=correlation_id,
            component="research_run_service",
        )
        return self._repo.update_status(
            run_id, ResearchRunStatus.FAILED, error_message=error_message
        )

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

    # ------------------------------------------------------------------
    # Results sub-resources (M2.C3)
    # ------------------------------------------------------------------
    #
    # These three methods feed the GET /runs/{run_id}/results/* endpoints.
    # Each one performs the same triage:
    #
    #     1. Look up the record via the repository.
    #     2. Raise NotFoundError if the record is missing.
    #     3. Raise RunNotCompletedError if the run hasn't finished — we
    #        prefer 409 over 404 here so the frontend can distinguish
    #        "wrong id" from "not ready yet".
    #     4. Project the engine result into the wire-shaped DTO.
    #
    # The projection logic is intentionally local: we never mutate the
    # ResearchRunRecord and never persist the projected DTO. This keeps
    # the service stateless w.r.t. these reads (no caching, no race).

    def get_equity_curve(self, run_id: str) -> EquityCurveResponse:
        """
        Build the equity-curve sub-resource for a completed run.

        The engine result carries equity points in two places:
            * ``signal_summary.equity_curve_points`` — the M9 extension,
              already in (timestamp, equity) shape.
            * ``backtest_result.equity_curve`` — a list of
              :class:`BacktestBar` objects from which we extract
              ``timestamp`` and ``equity`` per bar.
        We prefer the M9 extension because it's the canonical source
        when present; we fall back to the bar-derived series so older
        results still produce a usable curve.

        Args:
            run_id: ULID of the research run.

        Returns:
            EquityCurveResponse with samples ordered ascending by
            timestamp.

        Raises:
            NotFoundError: If no record exists for ``run_id``.
            RunNotCompletedError: If the run is not COMPLETED.
        """
        record = self._require_completed_record(run_id)
        result = record.result
        # _require_completed_record() guarantees a non-None result,
        # but the type checker can't see across raises so re-assert.
        assert result is not None  # noqa: S101 — invariant guard

        points: list[EquityCurvePoint] = []
        backtest_result = result.backtest_result
        if backtest_result is not None:
            summary = backtest_result.signal_summary
            if summary is not None and summary.equity_curve_points:
                points = [
                    EquityCurvePoint(timestamp=p.timestamp, equity=p.equity)
                    for p in summary.equity_curve_points
                ]
            elif backtest_result.equity_curve:
                points = [
                    EquityCurvePoint(timestamp=bar.timestamp, equity=bar.equity)
                    for bar in backtest_result.equity_curve
                ]

        # Stable sort so a future engine that emits out-of-order points
        # still yields a deterministic wire response.
        points.sort(key=lambda p: p.timestamp)

        logger.info(
            "research_run.equity_curve.served",
            run_id=run_id,
            point_count=len(points),
            component="research_run_service",
        )

        return EquityCurveResponse(
            run_id=run_id,
            point_count=len(points),
            points=points,
        )

    def get_blotter(
        self,
        run_id: str,
        *,
        page: int = 1,
        page_size: int = 100,
    ) -> TradeBlotterPage:
        """
        Build a paginated trade-blotter page for a completed run.

        Trades are sourced from ``backtest_result.trades`` and assigned
        a stable ``trade_id`` of ``trade-{index:06d}`` derived from
        their position in the ordered trade list. They are then sorted
        ascending by ``(timestamp, trade_id)`` so identical queries
        always produce identical pages — the precondition for the
        frontend's "load page N" pattern.

        Args:
            run_id: ULID of the research run.
            page: 1-based page index.
            page_size: Maximum trades per page (caller is responsible
                for enforcing the upper bound; this method does NOT
                clamp because the route returns 422 instead).

        Returns:
            TradeBlotterPage. Pages beyond ``total_pages`` return an
            empty ``trades`` list with the totals still populated.

        Raises:
            NotFoundError: If no record exists for ``run_id``.
            RunNotCompletedError: If the run is not COMPLETED.
            ValueError: If ``page`` < 1 or ``page_size`` < 1 (defence
                in depth — the route validates first).
        """
        if page < 1:
            raise ValueError("page must be >= 1")
        if page_size < 1:
            raise ValueError("page_size must be >= 1")

        record = self._require_completed_record(run_id)
        result = record.result
        assert result is not None  # noqa: S101 — invariant guard

        # Project trades into wire-shape entries with a stable trade_id.
        # The index-based ID is deterministic w.r.t. the engine's
        # ordering, which is the only ordering we trust pre-sort.
        entries: list[TradeBlotterEntry] = []
        backtest_result = result.backtest_result
        if backtest_result is not None:
            for index, trade in enumerate(backtest_result.trades):
                entries.append(
                    TradeBlotterEntry(
                        trade_id=f"trade-{index:06d}",
                        timestamp=trade.timestamp,
                        symbol=trade.symbol,
                        side=trade.side,
                        quantity=trade.quantity,
                        price=trade.price,
                        commission=trade.commission,
                        slippage=trade.slippage,
                    )
                )

        entries.sort(key=lambda e: (e.timestamp, e.trade_id))

        total_count = len(entries)
        total_pages = (total_count + page_size - 1) // page_size if total_count else 0

        start = (page - 1) * page_size
        end = start + page_size
        page_entries = entries[start:end]

        logger.info(
            "research_run.blotter.served",
            run_id=run_id,
            page=page,
            page_size=page_size,
            total_count=total_count,
            total_pages=total_pages,
            returned=len(page_entries),
            component="research_run_service",
        )

        return TradeBlotterPage(
            run_id=run_id,
            page=page,
            page_size=page_size,
            total_count=total_count,
            total_pages=total_pages,
            trades=page_entries,
        )

    def get_metrics(self, run_id: str) -> RunMetrics:
        """
        Build the headline-metrics sub-resource for a completed run.

        Pulls the explicit fields (Sharpe, drawdown, etc.) from
        ``backtest_result`` when available and passes
        ``summary_metrics`` through verbatim so engine-specific keys
        survive.

        Args:
            run_id: ULID of the research run.

        Returns:
            RunMetrics with all available fields populated; absent
            fields stay None rather than being defaulted to zero so
            consumers can tell "engine produced 0" from "engine did not
            report this metric".

        Raises:
            NotFoundError: If no record exists for ``run_id``.
            RunNotCompletedError: If the run is not COMPLETED.
        """
        record = self._require_completed_record(run_id)
        result = record.result
        assert result is not None  # noqa: S101 — invariant guard

        backtest_result = result.backtest_result

        if backtest_result is not None:
            metrics = RunMetrics(
                run_id=run_id,
                completed_at=result.completed_at,
                total_return_pct=backtest_result.total_return_pct,
                annualized_return_pct=backtest_result.annualized_return_pct,
                max_drawdown_pct=backtest_result.max_drawdown_pct,
                sharpe_ratio=backtest_result.sharpe_ratio,
                total_trades=backtest_result.total_trades,
                win_rate=backtest_result.win_rate,
                profit_factor=backtest_result.profit_factor,
                final_equity=backtest_result.final_equity,
                bars_processed=backtest_result.bars_processed,
                summary_metrics=dict(result.summary_metrics),
            )
        else:
            # Walk-forward / Monte-Carlo / Composite runs may not have
            # a backtest_result; surface the summary_metrics so the
            # endpoint still returns a meaningful payload.
            metrics = RunMetrics(
                run_id=run_id,
                completed_at=result.completed_at,
                summary_metrics=dict(result.summary_metrics),
            )

        logger.info(
            "research_run.metrics.served",
            run_id=run_id,
            has_backtest_result=backtest_result is not None,
            summary_metric_keys=len(result.summary_metrics),
            component="research_run_service",
        )

        return metrics

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _require_completed_record(self, run_id: str) -> ResearchRunRecord:
        """
        Look up a run and verify it is COMPLETED with a result body.

        Centralises the triage used by every results sub-resource so
        the error semantics stay identical across endpoints.

        Args:
            run_id: ULID of the research run.

        Returns:
            The ResearchRunRecord with a non-None ``result`` field.

        Raises:
            NotFoundError: If no record exists for ``run_id``.
            RunNotCompletedError: If the run is not COMPLETED, or is
                COMPLETED but missing a result body (treated the same
                way because callers cannot distinguish the two).
        """
        record = self._repo.get_by_id(run_id)
        if record is None:
            raise NotFoundError(f"Research run {run_id} not found")

        if record.status != ResearchRunStatus.COMPLETED or record.result is None:
            raise RunNotCompletedError(run_id, record.status)

        return record

    # ------------------------------------------------------------------
    # list_runs_for_strategy (StrategyDetail recent-runs section)
    # ------------------------------------------------------------------
    #
    # Method intentionally appended at the END of the class to minimise
    # merge friction with the sibling tranche modifying the run-executor
    # bootstrap above. Do not interleave with the existing methods.

    def list_runs_for_strategy(
        self,
        strategy_id: str,
        *,
        page: int,
        page_size: int,
    ) -> StrategyRunsPage:
        """
        Return one page of the recent-runs history for a given strategy.

        Wraps :meth:`ResearchRunRepositoryInterface.list_by_strategy_id`
        and projects the persistence-layer
        :class:`ResearchRunRecord` rows into the wire-shaped
        :class:`StrategyRunsPage` value object the route serialises.

        Args:
            strategy_id: ULID of the strategy whose runs to list.
            page: 1-based page index (validated by the route layer).
            page_size: Maximum runs per page (capped by the route layer).

        Returns:
            :class:`StrategyRunsPage` — already validated against the
            response schema, ready to ``model_dump`` for JSON output.

        Example:
            page = service.list_runs_for_strategy(
                "01HSTRAT0000000000000001",
                page=1,
                page_size=20,
            )
            assert page.runs[0].id.startswith("01H")
        """
        records, total_count = self._repo.list_by_strategy_id(
            strategy_id=strategy_id,
            page=page,
            page_size=page_size,
        )

        items: list[RunSummaryItem] = [
            RunSummaryItem(
                id=record.id,
                status=record.status.value,
                started_at=record.started_at,
                completed_at=record.completed_at,
                summary_metrics=self._project_summary_metrics(record),
            )
            for record in records
        ]

        # ceil(total_count / page_size) without importing math.
        total_pages = (total_count + page_size - 1) // page_size if page_size > 0 else 0

        result = StrategyRunsPage(
            runs=items,
            page=page,
            page_size=page_size,
            total_count=total_count,
            total_pages=total_pages,
        )

        logger.info(
            "research_run.list_for_strategy.completed",
            strategy_id=strategy_id,
            page=page,
            page_size=page_size,
            returned=len(items),
            total_count=total_count,
            component="research_run_service",
            operation="list_runs_for_strategy",
        )

        return result

    @staticmethod
    def _project_summary_metrics(record: ResearchRunRecord) -> RunSummaryMetrics:
        """
        Build the compact summary surfaced on the recent-runs row.

        Selection rule: prefer the explicit ``backtest_result`` fields
        (most accurate, typed Decimal), then fall back to the
        ``summary_metrics`` flat map (engine-specific keys), then
        leave fields ``None`` so consumers can distinguish "engine
        produced 0" from "engine did not report this metric".

        Args:
            record: The persisted research run record.

        Returns:
            :class:`RunSummaryMetrics`. For runs without a populated
            ``result`` (PENDING / QUEUED / RUNNING / FAILED-without-
            result) every field is ``None`` and ``trade_count`` is 0.
        """
        result = record.result
        if result is None:
            return RunSummaryMetrics()

        backtest_result = result.backtest_result
        if backtest_result is not None:
            return RunSummaryMetrics(
                total_return_pct=backtest_result.total_return_pct,
                sharpe_ratio=backtest_result.sharpe_ratio,
                win_rate=backtest_result.win_rate,
                trade_count=backtest_result.total_trades,
            )

        # No backtest_result body — try the flat summary_metrics map.
        # Engine-specific keys vary; we read the four canonical names the
        # synchronous executor emits (see _execute_synchronously above)
        # and accept either string or numeric values.
        flat = result.summary_metrics or {}

        def _to_decimal(value: object) -> Decimal | None:
            if value is None:
                return None
            try:
                return Decimal(str(value))
            except (ArithmeticError, ValueError):
                return None

        def _to_int(value: object) -> int:
            if value is None:
                return 0
            try:
                # ``int(Decimal(...))`` truncates the fractional part —
                # backtest engines never emit a fractional trade count
                # so truncation is harmless and avoids ValueError on
                # "42.0" inputs.
                return int(Decimal(str(value)))
            except (ArithmeticError, ValueError):
                return 0

        return RunSummaryMetrics(
            total_return_pct=_to_decimal(flat.get("total_return_pct")),
            sharpe_ratio=_to_decimal(flat.get("sharpe_ratio")),
            win_rate=_to_decimal(flat.get("win_rate")),
            trade_count=_to_int(flat.get("total_trades") or flat.get("trade_count")),
        )
