"""
In-process background pool that drives QUEUED research runs through the
synthetic backtest executor.

Purpose:
    Make ``POST /runs/from-ir?defer_execution=1`` honour its own promise:
    when the route returns 202 Accepted with a QUEUED run, an asyncio
    task in this pool picks the run up, transitions it through
    QUEUED -> RUNNING -> COMPLETED (or FAILED), and persists the
    resulting :class:`ResearchRunResult` so the M2.C3 GET sub-resources
    can serve real data once the caller polls back.

    The synchronous path
    (``POST /runs/from-ir`` without ``defer_execution=1``) is unchanged:
    :class:`ResearchRunService.submit_from_ir` still runs the executor
    inline on the request thread. This pool is ONLY consulted when the
    caller explicitly defers execution.

Concurrency model:
    asyncio task pool, bounded by an :class:`asyncio.Semaphore`. The
    backtest executor itself is CPU-bound and blocking, so each task
    dispatches the actual ``execute()`` call onto the default thread pool
    via :func:`asyncio.to_thread` -- this gives us true parallelism
    without blocking the FastAPI event loop and without requiring a
    second process. Default ``max_concurrent_runs=4`` matches the
    original spec; the operator can tune it via the
    ``RUN_EXECUTOR_POOL_CONCURRENCY`` env var when wiring (see
    ``services/api/main.py``).

    This is deliberately in-process for now. When run volume justifies
    it, the swap path is:
        1. Replace :meth:`RunExecutorPool.submit` with an enqueue to a
           Celery / Redis Queue / RQ broker.
        2. Run :class:`RunExecutionWorker.execute` inside the worker
           process; it already takes a run_id and looks everything else
           up via injected services, so its body is portable as-is.
        3. Drop the asyncio scaffolding here -- the worker process
           handles concurrency externally.

Recovery semantics:
    NOT implemented. Recovering QUEUED runs from a prior crash on
    startup would require the pool to know about strategy IRs and the
    dataset resolver, which couples this module tightly to bootstrap
    wiring. The current contract is: a crash drops in-flight QUEUED runs
    on the floor; operators re-submit. Documented here so the trade-off
    is explicit; revisit when we adopt a real broker (Celery/RQ).

Responsibilities:
    - Hold a bounded set of in-flight asyncio tasks, one per submitted
      run id.
    - Dispatch each run via :class:`RunExecutionWorker.execute`, which
      owns the full QUEUED -> RUNNING -> COMPLETED lifecycle.
    - Provide :meth:`wait_for_idle` so test fixtures can deterministically
      block until every submitted run has finished.

Does NOT:
    - Persist its own state. Run state lives entirely on the
      :class:`ResearchRunRecord` rows; the pool just keeps a soft
      in-memory tracker of which run ids are in flight so it can refuse
      duplicates and so :meth:`wait_for_idle` can join them.
    - Run executors itself. It delegates to the injected
      :class:`RunExecutionWorker`.
    - Catch worker exceptions silently. Worker failures are logged with
      ``exc_info`` and the run row is transitioned to FAILED by the
      worker before the exception is swallowed by the pool (the user
      polls GET /runs/{id} to see the failure).

Dependencies:
    - :class:`RunExecutionWorker` (injected): owns the per-run
      orchestration -- loading IR, building the executor request,
      transitioning status, persisting the result.

Example::

    pool = RunExecutorPool(worker=worker, max_concurrent_runs=4)
    pool.submit(run_id="01H...")
    await pool.wait_for_idle()
    record = service.get_run("01H...")
    assert record.status == ResearchRunStatus.COMPLETED
"""

from __future__ import annotations

import asyncio
import threading
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from typing import TYPE_CHECKING, Any

import structlog

from libs.contracts.errors import FXLabError
from libs.contracts.experiment_plan import ExperimentPlan
from libs.contracts.interfaces.research_run_repository import (
    ResearchRunRepositoryInterface,
)
from libs.contracts.research_run import ResearchRunResult, ResearchRunStatus
from libs.strategy_ir.interfaces.dataset_resolver_interface import (
    ResolvedDataset,
)

if TYPE_CHECKING:  # pragma: no cover -- typing-only import
    from collections.abc import Callable

    from services.api.services.synthetic_backtest_executor import (
        SyntheticBacktestExecutor,
    )

logger = structlog.get_logger(__name__)


#: Default upper bound on concurrent in-flight runs. Picked to match the
#: spec; safely below the default thread-pool limit so executor blocking
#: never starves the rest of the app.
DEFAULT_MAX_CONCURRENT_RUNS = 4


# ---------------------------------------------------------------------------
# RunExecutionWorker
# ---------------------------------------------------------------------------


class RunExecutionWorker:
    """
    Per-run orchestrator that owns the QUEUED -> RUNNING -> COMPLETED
    lifecycle for one deferred research run.

    This class mirrors the synchronous code path inside
    :meth:`ResearchRunService._execute_synchronously`, but is reachable
    from the background pool by run_id alone. It re-uses the same window
    selection + timeframe extraction helpers so deferred and synchronous
    runs produce byte-identical results for the same seed + plan + IR.

    Responsibilities:
        - Load the run record via the injected repository.
        - Re-hydrate the experiment plan + resolved dataset associated
          with the run (in this tranche the plan is supplied at submit
          time and stashed on the worker context, NOT re-loaded from
          the run row, because there is no plan repository yet).
        - Build the :class:`SyntheticBacktestRequest` using the same
          window-selection + IR-loader rules the synchronous path uses.
        - Invoke the executor, persist the result, and transition the
          run row to a terminal status.

    Does NOT:
        - Mutate the supplied :class:`ExperimentPlan` or
          :class:`ResolvedDataset`.
        - Catch :class:`Exception` and silently drop it. Any unexpected
          executor exception is wrapped in :class:`FXLabError` after the
          run row is transitioned to FAILED.

    Dependencies:
        - :class:`ResearchRunRepositoryInterface` (injected): persistence.
        - :class:`SyntheticBacktestExecutor` (injected): the engine.
        - ``ir_loader`` callable (injected): same shape used by
          :class:`ResearchRunService` -- given a strategy_id, return the
          parsed IR dict.

    Raises:
        FXLabError: when the executor raises. The run row is left in
            FAILED state with ``error_message`` populated before this
            propagates.

    Example::

        worker = RunExecutionWorker(
            repo=repo,
            executor=SyntheticBacktestExecutor(),
            ir_loader=lambda sid: parsed_ir_for(sid),
        )
        worker.execute(
            run_id="01H...",
            strategy_id="01H...",
            experiment_plan=plan,
            resolved_dataset=resolved,
            correlation_id="req-...",
        )
    """

    def __init__(
        self,
        *,
        repo: ResearchRunRepositoryInterface,
        executor: SyntheticBacktestExecutor,
        ir_loader: Callable[[str], dict[str, Any]],
    ) -> None:
        """
        Construct the worker.

        Args:
            repo: Persistence layer for run-record reads/writes.
            executor: Synthetic backtest engine used to produce the
                :class:`BacktestResult` body.
            ir_loader: Callable resolving a strategy_id to the parsed IR
                dict expected by the executor. Mirrors
                :attr:`ResearchRunService._ir_loader` so the same
                bootstrap closure feeds both code paths.
        """
        self._repo = repo
        self._executor = executor
        self._ir_loader = ir_loader

    def execute(
        self,
        *,
        run_id: str,
        strategy_id: str,
        experiment_plan: ExperimentPlan,
        resolved_dataset: ResolvedDataset,
        correlation_id: str | None,
    ) -> None:
        """
        Drive one run through the full lifecycle on the calling thread.

        Lifecycle:
            QUEUED -> RUNNING (started_at stamped)
                   -> COMPLETED (completed_at stamped + result attached)
                   on success.
            QUEUED -> RUNNING -> FAILED (error_message persisted) on
                   any executor exception.

        Args:
            run_id: ULID returned by ``submit_from_ir``.
            strategy_id: Strategy ULID; used by the IR loader.
            experiment_plan: Plan body; source of seed + replay window.
            resolved_dataset: Source of the symbol set.
            correlation_id: Propagated through every log line.
        """
        # Local imports keep cold construction cheap and avoid the
        # services.cli import cycle that the executor depends on.
        from services.api.services.research_run_service import (
            ResearchRunService,
        )
        from services.api.services.synthetic_backtest_executor import (
            SyntheticBacktestError,
            SyntheticBacktestRequest,
        )

        logger.info(
            "research_run.worker.start",
            run_id=run_id,
            strategy_id=strategy_id,
            correlation_id=correlation_id,
            component="run_executor_pool",
        )

        # 1. QUEUED -> RUNNING.
        try:
            self._repo.update_status(run_id, ResearchRunStatus.RUNNING)
        except Exception as exc:
            logger.error(
                "research_run.worker.queued_to_running_failed",
                run_id=run_id,
                error=str(exc),
                exc_info=True,
                correlation_id=correlation_id,
                component="run_executor_pool",
            )
            # Cannot transition out of QUEUED. There is nothing to mark
            # FAILED here -- update_status was the failing call. Re-raise
            # so the pool can log the failure; the run row stays QUEUED
            # so a later operator-driven retry can pick it up.
            raise

        # 2. Resolve IR + build request (same rules as the sync path).
        try:
            ir_dict = self._ir_loader(strategy_id)
        except Exception as exc:
            self._mark_failed(
                run_id,
                f"failed to load IR for strategy {strategy_id}: {type(exc).__name__}: {exc}",
                correlation_id=correlation_id,
                exc=exc,
            )
            return

        symbols = list(resolved_dataset.symbols)
        seed = experiment_plan.run_metadata.random_seed
        start_d, end_d = ResearchRunService._select_replay_window(experiment_plan)
        timeframe = ResearchRunService._extract_primary_timeframe(ir_dict)

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

        # 3. Execute. Wrap every executor exception so the run row is
        #    FAILED before propagation. The pool layer logs and swallows.
        try:
            backtest_result = self._executor.execute(request)
        except SyntheticBacktestError as exc:
            self._mark_failed(
                run_id,
                f"backtest execution failed: {exc}",
                correlation_id=correlation_id,
                exc=exc,
            )
            raise FXLabError(str(exc)) from exc
        except Exception as exc:
            self._mark_failed(
                run_id,
                f"backtest execution raised unexpectedly: {type(exc).__name__}: {exc}",
                correlation_id=correlation_id,
                exc=exc,
            )
            raise

        # 4. Persist result + transition COMPLETED.
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
        self._repo.update_status(run_id, ResearchRunStatus.COMPLETED)

        logger.info(
            "research_run.worker.completed",
            run_id=run_id,
            strategy_id=strategy_id,
            trade_count=backtest_result.total_trades,
            equity_points=len(backtest_result.equity_curve),
            total_return_pct=str(backtest_result.total_return_pct),
            correlation_id=correlation_id,
            component="run_executor_pool",
        )

    def _mark_failed(
        self,
        run_id: str,
        error_message: str,
        *,
        correlation_id: str | None,
        exc: Exception,
    ) -> None:
        """
        Persist a FAILED transition + error_message and log the cause.

        Args:
            run_id: The ULID to mark FAILED.
            error_message: Operator-readable cause.
            correlation_id: Propagated to the log line.
            exc: Source exception, logged with ``exc_info``.
        """
        logger.error(
            "research_run.worker.failed",
            run_id=run_id,
            error=error_message,
            exc_info=exc,
            correlation_id=correlation_id,
            component="run_executor_pool",
        )
        try:
            self._repo.update_status(run_id, ResearchRunStatus.FAILED, error_message=error_message)
        except Exception as persist_exc:  # pragma: no cover -- defensive
            logger.error(
                "research_run.worker.mark_failed_persist_error",
                run_id=run_id,
                error=str(persist_exc),
                exc_info=True,
                correlation_id=correlation_id,
                component="run_executor_pool",
            )


# ---------------------------------------------------------------------------
# Submission context
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class _SubmittedRun:
    """
    Per-submission context the pool needs to invoke the worker.

    Frozen so callers cannot mutate plan/dataset out from under an
    in-flight task.
    """

    run_id: str
    strategy_id: str
    experiment_plan: ExperimentPlan
    resolved_dataset: ResolvedDataset
    correlation_id: str | None


# ---------------------------------------------------------------------------
# RunExecutorPool
# ---------------------------------------------------------------------------


class RunExecutorPool:
    """
    Bounded asyncio task pool for deferred research-run execution.

    Responsibilities:
        - Accept submissions of :class:`_SubmittedRun` contexts.
        - Schedule each submission as an asyncio task that dispatches
          the synchronous executor onto a thread (so the event loop stays
          responsive).
        - Track in-flight tasks so :meth:`wait_for_idle` can deterministically
          block tests until every submission has finished.
        - Refuse duplicate submissions for the same run_id (the worker
          would race against itself otherwise).

    Does NOT:
        - Persist run state. The worker handles all repo writes.
        - Recover orphaned QUEUED runs on startup (see module docstring).
        - Spawn additional event loops or threads. It re-uses the
          ambient event loop and the default thread pool.

    Dependencies:
        - :class:`RunExecutionWorker` (injected): the per-run orchestrator.

    Example::

        pool = RunExecutorPool(worker=worker)
        pool.submit(run_id="01H...", strategy_id="...", plan=..., dataset=...)
        await pool.wait_for_idle()
    """

    def __init__(
        self,
        *,
        worker: RunExecutionWorker,
        max_concurrent_runs: int = DEFAULT_MAX_CONCURRENT_RUNS,
    ) -> None:
        """
        Construct the pool.

        Args:
            worker: Worker that owns per-run lifecycle.
            max_concurrent_runs: Upper bound on in-flight tasks. Defaults
                to :data:`DEFAULT_MAX_CONCURRENT_RUNS` (4).
        """
        if max_concurrent_runs < 1:
            raise ValueError(f"max_concurrent_runs must be >= 1, got {max_concurrent_runs}")
        self._worker = worker
        self._max_concurrent_runs = max_concurrent_runs
        # Lazy semaphore: tied to the loop the first task is scheduled on.
        # asyncio.Semaphore() created at __init__ time would bind to
        # whatever loop happened to be current then, which breaks tests
        # that create their own loop per case.
        self._semaphore: asyncio.Semaphore | None = None
        self._inflight: dict[str, asyncio.Task[None]] = {}
        # Guards _inflight + _semaphore creation across thread boundaries
        # (FastAPI request handlers may submit from sync helpers via
        # `asyncio.run_coroutine_threadsafe`).
        self._lock = threading.Lock()
        # Coroutine-level mutex used by :meth:`cancel_run` to serialise
        # concurrent cancel requests for the same run_id. Built lazily on
        # first use so it binds to the loop that actually owns the pool.
        self._cancel_lock: asyncio.Lock | None = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    @property
    def max_concurrent_runs(self) -> int:
        """Read-only view of the bound passed at construction time."""
        return self._max_concurrent_runs

    def inflight_count(self) -> int:
        """
        Return the number of tasks the pool is currently tracking.

        A task counts as in-flight from submit() until its done callback
        removes it, regardless of whether it is currently waiting on the
        semaphore or actively running the worker.
        """
        with self._lock:
            return len(self._inflight)

    def submit(self, context: _SubmittedRun) -> asyncio.Task[None]:
        """
        Schedule a deferred run on the ambient event loop.

        The returned task can be awaited by callers that want
        per-submission completion semantics; tests typically use
        :meth:`wait_for_idle` instead so they don't have to thread tasks
        through their fixtures.

        Args:
            context: The submission to dispatch. ``context.run_id`` must
                already correspond to a row in QUEUED state.

        Returns:
            The :class:`asyncio.Task` driving the worker call.

        Raises:
            RuntimeError: If a task for ``context.run_id`` is already in
                flight (refused to prevent worker races against itself).
        """
        # get_running_loop raises if not in an async context; that's
        # the right semantics here -- the pool only makes sense inside
        # the FastAPI event loop.
        loop = asyncio.get_running_loop()
        with self._lock:
            if context.run_id in self._inflight:
                raise RuntimeError(
                    f"run {context.run_id} already in flight; refusing duplicate submit"
                )
            if self._semaphore is None:
                self._semaphore = asyncio.Semaphore(self._max_concurrent_runs)
            task = loop.create_task(self._run(context))
            self._inflight[context.run_id] = task

        # Ensure the entry is cleaned up regardless of success/failure.
        def _on_done(t: asyncio.Task[None]) -> None:
            with self._lock:
                self._inflight.pop(context.run_id, None)
            # Surface unhandled exceptions in the log; do not crash the
            # event loop. The run row already carries FAILED in this case.
            exc = t.exception() if not t.cancelled() else None
            if exc is not None:
                logger.warning(
                    "research_run.pool.task_finished_with_error",
                    run_id=context.run_id,
                    error=str(exc),
                    component="run_executor_pool",
                )

        task.add_done_callback(_on_done)

        logger.info(
            "research_run.pool.submitted",
            run_id=context.run_id,
            strategy_id=context.strategy_id,
            inflight=len(self._inflight),
            max_concurrent=self._max_concurrent_runs,
            correlation_id=context.correlation_id,
            component="run_executor_pool",
        )
        return task

    async def cancel_run(self, run_id: str) -> bool:
        """
        Cancel an in-flight task for ``run_id`` if one exists.

        Looks the task up in the in-flight tracker; if present, calls
        :meth:`asyncio.Task.cancel` and awaits the task so the
        ``CancelledError`` propagation completes deterministically before
        we return. The ``async with self._semaphore`` block in
        :meth:`_run` guarantees the semaphore slot is released as part of
        the unwind, even when the task is cancelled mid-execution.

        Args:
            run_id: The ULID whose in-flight task should be aborted.

        Returns:
            ``True`` if a task existed for ``run_id`` and was cancelled.
            ``False`` if no such task was tracked (already completed,
            never submitted, or cancelled by an earlier call).

        Example::

            cancelled = await pool.cancel_run("01H...")
            if cancelled:
                logger.info("aborted in-flight run %s", run_id)
        """
        # Bind the cancel-side lock to the running loop on first use; the
        # ``threading.Lock`` continues to guard ``_inflight`` for the
        # cross-thread invariants ``submit`` relies on.
        if self._cancel_lock is None:
            self._cancel_lock = asyncio.Lock()

        async with self._cancel_lock:
            # Pop under the threading lock so a concurrent done-callback
            # cannot race our task lookup. If the task has already left
            # the map (worker finished between submit and cancel), we
            # surface that to the caller as ``False`` rather than silently
            # returning ``True``; the service layer logs the race.
            with self._lock:
                task = self._inflight.pop(run_id, None)

            if task is None:
                logger.info(
                    "research_run.pool.cancel_no_task",
                    run_id=run_id,
                    component="run_executor_pool",
                )
                return False

            if task.done():
                # Already terminal; nothing to cancel. We still report
                # True because the caller's intent (the entry is no
                # longer in-flight) is satisfied.
                logger.info(
                    "research_run.pool.cancel_already_done",
                    run_id=run_id,
                    component="run_executor_pool",
                )
                return True

            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                # Expected outcome of cancel() — the task body either
                # propagated CancelledError out of an await point or
                # raised it on re-entry. Suppress so cancel_run remains
                # an idempotent operator action.
                pass
            except Exception as exc:  # noqa: BLE001 -- surface in log only
                # The worker raised something else (e.g. it had already
                # transitioned to FAILED before our cancel landed). The
                # row's persisted state is the source of truth; we log
                # and report success because the in-flight slot is gone.
                logger.warning(
                    "research_run.pool.cancel_task_raised",
                    run_id=run_id,
                    error=str(exc),
                    component="run_executor_pool",
                )

            logger.info(
                "research_run.pool.cancelled",
                run_id=run_id,
                component="run_executor_pool",
            )
            return True

    async def wait_for_idle(self, timeout: float | None = None) -> None:
        """
        Block until every in-flight submission has completed (or failed).

        Intended for tests; production code should not need to wait for
        the pool to drain.

        Args:
            timeout: Optional upper bound in seconds. ``None`` waits
                forever (the default; tests that need a guard set their
                own ``pytest`` timeout).

        Raises:
            asyncio.TimeoutError: If ``timeout`` elapses with tasks
                still in flight.
        """
        # Snapshot the current task set; new submissions arriving during
        # the wait are NOT joined. This is intentional: a test that
        # submits inside another submission would otherwise deadlock.
        with self._lock:
            tasks = list(self._inflight.values())
        if not tasks:
            return
        if timeout is None:
            await asyncio.gather(*tasks, return_exceptions=True)
        else:
            await asyncio.wait_for(
                asyncio.gather(*tasks, return_exceptions=True),
                timeout=timeout,
            )

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    async def _run(self, context: _SubmittedRun) -> None:
        """
        Single in-flight task body: acquire the semaphore, dispatch the
        synchronous worker on a thread, log entry and exit.
        """
        assert self._semaphore is not None  # noqa: S101 -- set in submit()
        async with self._semaphore:
            try:
                await asyncio.to_thread(
                    self._worker.execute,
                    run_id=context.run_id,
                    strategy_id=context.strategy_id,
                    experiment_plan=context.experiment_plan,
                    resolved_dataset=context.resolved_dataset,
                    correlation_id=context.correlation_id,
                )
            except FXLabError:
                # Worker has already persisted FAILED on the run row;
                # swallow so the pool does not crash. The caller polls
                # GET /runs/{id} to see the failure.
                logger.warning(
                    "research_run.pool.fxlab_error",
                    run_id=context.run_id,
                    component="run_executor_pool",
                )
            except Exception as exc:
                # Unexpected; the worker tried to persist FAILED but the
                # exception escaped anyway. Re-raise for the done-callback
                # to log; do not let it crash the event loop.
                logger.error(
                    "research_run.pool.unexpected_worker_error",
                    run_id=context.run_id,
                    error=str(exc),
                    exc_info=True,
                    component="run_executor_pool",
                )
                raise


# ---------------------------------------------------------------------------
# Helpers used by ResearchRunService when constructing submissions
# ---------------------------------------------------------------------------


def build_submission(
    *,
    run_id: str,
    strategy_id: str,
    experiment_plan: ExperimentPlan,
    resolved_dataset: ResolvedDataset,
    correlation_id: str | None,
) -> _SubmittedRun:
    """
    Convenience constructor for the :class:`_SubmittedRun` dataclass.

    Hides the underscore-prefixed dataclass name from callers (the name
    is module-private to keep mypy from suggesting consumers import it
    directly; callers should go through this helper).

    Args:
        run_id: ULID of the QUEUED run row.
        strategy_id: Strategy ULID for the IR loader.
        experiment_plan: Plan body.
        resolved_dataset: Resolver output for the plan's dataset_ref.
        correlation_id: Propagated through every log line emitted by the
            worker and pool.

    Returns:
        Frozen :class:`_SubmittedRun` ready to pass to
        :meth:`RunExecutorPool.submit`.
    """
    return _SubmittedRun(
        run_id=run_id,
        strategy_id=strategy_id,
        experiment_plan=experiment_plan,
        resolved_dataset=resolved_dataset,
        correlation_id=correlation_id,
    )


# Re-exports kept narrow: the dataclass stays underscore-prefixed; the
# public surface is the pool, the worker, and the build_submission helper.
__all__ = [
    "DEFAULT_MAX_CONCURRENT_RUNS",
    "RunExecutionWorker",
    "RunExecutorPool",
    "build_submission",
]
