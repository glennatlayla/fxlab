"""
Background job for periodic broker-vs-internal reconciliation.

Responsibilities:
- On a configurable interval, list all deployments with state=active and
  execution_mode=live, and invoke ReconciliationService.run_reconciliation
  on each.
- Isolate per-deployment failures so one broker outage does not block
  reconciliation for other deployments.
- Log each tick and each per-deployment outcome with structured fields.

Does NOT:
- Modify orders or positions (ReconciliationService is read-only).
- Halt trading on discrepancies (kill-switch policy is a separate concern).
- Persist reconciliation reports (delegated to ReconciliationService ->
  ReconciliationRepository).

Rationale:
Startup-only reconciliation closes the crash-recovery window but leaves a
long-lived divergence window mid-day: if internal state and broker state
drift while the API is up (e.g. broker cancels due to margin, message lost,
clock skew), the drift is only caught at the *next* restart. Periodic
reconciliation bounds that window to the configured interval.

This mirrors the lifecycle shape of SecretRotationJob: a daemon thread
driven by a stop event, with idempotent start()/stop().

Dependencies:
- ReconciliationServiceInterface (injected): the service that runs a
  single reconciliation per deployment.
- DeploymentRepositoryInterface (injected, duck-typed on .list_by_state):
  used to enumerate active deployments.
- threading (stdlib): daemon thread with interruptible sleep.

Error conditions:
- Invalid constructor args (None service or repo) raise ValueError.
- Per-deployment reconciliation exceptions are logged at ERROR and do
  NOT abort the tick; remaining deployments are still attempted.
- start()/stop() are idempotent.

Example:
    svc = ReconciliationService(...)
    repo = SqlDeploymentRepository(db_session)
    job = PeriodicReconciliationJob(
        reconciliation_service=svc,
        deployment_repo=repo,
        check_interval_seconds=300.0,
    )
    job.start()
    # ... app runs ...
    job.stop()
"""

from __future__ import annotations

import threading
from typing import Any, Callable, Protocol, runtime_checkable

import structlog

from libs.contracts.interfaces.reconciliation_service_interface import (
    ReconciliationServiceInterface,
)
from libs.contracts.reconciliation import ReconciliationTrigger

logger = structlog.get_logger(__name__)

# Default execution mode we reconcile against. Paper and shadow modes do
# not submit to a real broker, so reconciling them would compare against
# an empty / synthetic adapter.
_LIVE_EXECUTION_MODE = "live"
_ACTIVE_STATE = "active"


@runtime_checkable
class _DeploymentRepoShape(Protocol):
    """
    Structural shape of the deployment repository we depend on.

    We only need to enumerate deployments by state — this narrow protocol
    keeps the job decoupled from the full DeploymentRepositoryInterface
    and makes it testable with a tiny fake.
    """

    def list_by_state(self, *, state: str) -> list[dict[str, Any]]: ...


class PeriodicReconciliationJob:
    """
    Daemon-thread scheduler that periodically reconciles all active live
    deployments.

    Thread safety:
        Internal state (_running, _stop_event, _thread) is protected by
        _lock. The injected ReconciliationService is assumed thread-safe
        (its production implementation is).

    Responsibilities:
    - Periodic scan for active live deployments.
    - Invocation of ReconciliationService.run_reconciliation per deployment.
    - Isolation of per-deployment failures from the tick loop.

    Does NOT:
    - Own reconciliation logic (delegated to ReconciliationService).
    - Decide what counts as "active" or "live" — trusts the repository.

    Example:
        job = PeriodicReconciliationJob(
            reconciliation_service=svc,
            deployment_repo=repo,
            check_interval_seconds=300.0,
        )
        job.start()
        ids = job.check_and_reconcile()  # also callable manually
        job.stop()
    """

    def __init__(
        self,
        *,
        reconciliation_service: ReconciliationServiceInterface | None = None,
        reconciliation_service_factory: (
            Callable[[], ReconciliationServiceInterface] | None
        ) = None,
        deployment_repo: _DeploymentRepoShape,
        check_interval_seconds: float = 300.0,
    ) -> None:
        """
        Initialise the periodic reconciliation job.

        Exactly one of `reconciliation_service` or
        `reconciliation_service_factory` must be provided:

        - reconciliation_service: use a single shared service across all
          ticks. Only safe if the service and its underlying repositories
          are thread-safe with respect to the code that shares them.
        - reconciliation_service_factory: a zero-argument callable that
          produces a fresh ReconciliationServiceInterface per tick. This
          is the recommended production wiring because SQLAlchemy Session
          instances are NOT thread-safe — a factory that builds a fresh
          session + repositories per tick avoids concurrent-use hazards.

        Args:
            reconciliation_service: Shared service instance (optional).
            reconciliation_service_factory: Per-tick factory (optional).
            deployment_repo: Repository supporting list_by_state(state=...).
                This repo IS shared across ticks; the job only calls a
                read method on it. In production wire it to a repo whose
                session access is thread-safe (e.g. scoped_session) or
                accept the implicit lock provided by sqlite/postgres-level
                isolation of a single read.
            check_interval_seconds: Seconds between ticks. 0 or negative
                disables the background thread; start() becomes a no-op.
                Default: 300 (5 minutes).

        Raises:
            ValueError: when required args are missing, or both service
                and factory are provided simultaneously.

        Example:
            job = PeriodicReconciliationJob(
                reconciliation_service_factory=lambda: build_service(),
                deployment_repo=repo,
                check_interval_seconds=300.0,
            )
        """
        if reconciliation_service is None and reconciliation_service_factory is None:
            raise ValueError(
                "Either reconciliation_service or reconciliation_service_factory must be provided."
            )
        if reconciliation_service is not None and reconciliation_service_factory is not None:
            raise ValueError(
                "Provide only one of reconciliation_service or "
                "reconciliation_service_factory, not both."
            )
        if deployment_repo is None:
            raise ValueError("deployment_repo is required for PeriodicReconciliationJob")

        self._reconciliation_service = reconciliation_service
        self._reconciliation_service_factory = reconciliation_service_factory
        self._deployment_repo = deployment_repo
        self._check_interval = float(check_interval_seconds)
        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        self._thread: threading.Thread | None = None
        self._running = False

    def _get_service(self) -> ReconciliationServiceInterface:
        """
        Return a ReconciliationService instance for the current tick.

        Uses the factory when provided (recommended: fresh session per
        tick), otherwise falls back to the shared instance.
        """
        if self._reconciliation_service_factory is not None:
            return self._reconciliation_service_factory()
        # Invariant: exactly one is non-None (enforced in __init__).
        assert self._reconciliation_service is not None
        return self._reconciliation_service

    # ------------------------------------------------------------------
    # Public lifecycle API
    # ------------------------------------------------------------------

    @property
    def is_running(self) -> bool:
        """Whether the background reconciliation thread is currently active."""
        with self._lock:
            return self._running

    @property
    def check_interval_seconds(self) -> float:
        """Configured interval between ticks, in seconds."""
        return self._check_interval

    def start(self) -> None:
        """
        Start the background reconciliation thread.

        Idempotent: calling start() when already running is a no-op.
        If check_interval_seconds <= 0 the job is considered disabled and
        start() is a no-op — operators use this to turn the feature off
        without removing the wiring.

        The thread is a daemon thread, so it does not block process exit.

        Example:
            job.start()
            assert job.is_running is True
        """
        if self._check_interval <= 0:
            logger.info(
                "periodic_reconciliation.disabled",
                component="PeriodicReconciliationJob",
                operation="start",
                check_interval_seconds=self._check_interval,
                detail=(
                    "check_interval_seconds is 0 or negative — periodic "
                    "reconciliation is disabled. Set RECONCILIATION_INTERVAL_SECONDS "
                    "to a positive number to enable."
                ),
            )
            return

        with self._lock:
            if self._running:
                logger.warning(
                    "periodic_reconciliation.already_running",
                    component="PeriodicReconciliationJob",
                    operation="start",
                )
                return
            self._stop_event.clear()
            self._thread = threading.Thread(
                target=self._run_loop,
                name="periodic-reconciliation-job",
                daemon=True,
            )
            self._running = True
            self._thread.start()

        logger.info(
            "periodic_reconciliation.started",
            component="PeriodicReconciliationJob",
            operation="start",
            check_interval_seconds=self._check_interval,
        )

    def stop(self) -> None:
        """
        Stop the background reconciliation thread.

        Idempotent: calling stop() when not running is a no-op. Blocks up
        to 2x check_interval for the thread to terminate.

        Example:
            job.stop()
            assert job.is_running is False
        """
        with self._lock:
            if not self._running:
                return
            self._stop_event.set()
            thread = self._thread

        if thread is not None:
            # Bound the wait to avoid hanging shutdown if a reconciliation
            # call is stuck on a slow broker. Daemon threads are GC'd on
            # process exit regardless.
            thread.join(timeout=max(self._check_interval * 2.0, 1.0))

        with self._lock:
            self._running = False
            self._thread = None

        logger.info(
            "periodic_reconciliation.stopped",
            component="PeriodicReconciliationJob",
            operation="stop",
        )

    # ------------------------------------------------------------------
    # Core tick — also callable manually from admin endpoints or tests
    # ------------------------------------------------------------------

    def check_and_reconcile(self) -> list[str]:
        """
        Run one reconciliation pass across all active live deployments.

        Enumerates deployments with state='active' and execution_mode='live',
        invoking ReconciliationService.run_reconciliation for each. A
        failure for one deployment is logged and does NOT abort the pass.

        Returns:
            List of deployment_ids that were *successfully* reconciled
            (exception-free return from run_reconciliation). Deployments
            that raised are omitted but will be retried on the next tick.

        Example:
            reconciled = job.check_and_reconcile()
        """
        try:
            active = self._deployment_repo.list_by_state(state=_ACTIVE_STATE)
        except Exception:
            logger.error(
                "periodic_reconciliation.list_deployments_failed",
                component="PeriodicReconciliationJob",
                operation="check_and_reconcile",
                exc_info=True,
            )
            return []

        live_active = [d for d in active if d.get("execution_mode") == _LIVE_EXECUTION_MODE]

        logger.info(
            "periodic_reconciliation.tick_started",
            component="PeriodicReconciliationJob",
            operation="check_and_reconcile",
            active_total=len(active),
            live_eligible=len(live_active),
        )

        reconciled_ids: list[str] = []
        # Resolve the service once per tick — for factory wiring, this
        # creates a fresh session + repositories scoped to this tick so
        # per-deployment failures don't leak state into the next tick.
        try:
            service = self._get_service()
        except Exception:
            logger.error(
                "periodic_reconciliation.service_build_failed",
                component="PeriodicReconciliationJob",
                operation="check_and_reconcile",
                exc_info=True,
            )
            return []

        for deployment in live_active:
            deployment_id = deployment.get("id")
            if not deployment_id:
                # Defensive: skip rows missing an id rather than crashing.
                continue
            try:
                service.run_reconciliation(
                    deployment_id=deployment_id,
                    trigger=ReconciliationTrigger.SCHEDULED,
                )
                reconciled_ids.append(deployment_id)
                logger.debug(
                    "periodic_reconciliation.deployment_ok",
                    component="PeriodicReconciliationJob",
                    operation="check_and_reconcile",
                    deployment_id=deployment_id,
                )
            except Exception:
                # Per-deployment isolation. One broker outage must not
                # block reconciliation of the rest of the portfolio.
                logger.error(
                    "periodic_reconciliation.deployment_failed",
                    component="PeriodicReconciliationJob",
                    operation="check_and_reconcile",
                    deployment_id=deployment_id,
                    exc_info=True,
                )

        logger.info(
            "periodic_reconciliation.tick_completed",
            component="PeriodicReconciliationJob",
            operation="check_and_reconcile",
            reconciled_count=len(reconciled_ids),
            eligible_count=len(live_active),
        )
        return reconciled_ids

    # ------------------------------------------------------------------
    # Internal loop
    # ------------------------------------------------------------------

    def _run_loop(self) -> None:
        """
        Background loop — runs one pass, sleeps until next interval, repeats.

        Uses Event.wait() for interruptible sleep so stop() returns quickly
        instead of waiting for the next full interval.
        """
        logger.debug(
            "periodic_reconciliation.loop_started",
            component="PeriodicReconciliationJob",
            operation="_run_loop",
            check_interval_seconds=self._check_interval,
        )

        while not self._stop_event.is_set():
            try:
                self.check_and_reconcile()
            except Exception:
                # check_and_reconcile already isolates per-deployment errors,
                # but we wrap the whole pass too so a bug in the list/iter
                # layer doesn't kill the scheduler thread silently.
                logger.error(
                    "periodic_reconciliation.loop_tick_failed",
                    component="PeriodicReconciliationJob",
                    operation="_run_loop",
                    exc_info=True,
                )
            # Interruptible sleep. wait() returns True when the event is
            # set, which happens on stop().
            self._stop_event.wait(self._check_interval)

        logger.debug(
            "periodic_reconciliation.loop_stopped",
            component="PeriodicReconciliationJob",
            operation="_run_loop",
        )
