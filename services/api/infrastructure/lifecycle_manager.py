"""
Graceful lifecycle manager for application startup and shutdown.

Responsibilities:
- Orchestrate the shutdown sequence: drain → reconcile → deregister → dispose.
- Orchestrate startup recovery: reconnect adapters → reconcile active deployments.
- Log structured events at each lifecycle stage for operational visibility.
- Handle partial failures gracefully (one adapter failing does not block others).

Does NOT:
- Create or configure broker adapters (that is the deployment service's job).
- Own the FastAPI lifespan — the lifespan delegates to this manager.
- Make decisions about discrepancies (log WARNING, do not auto-resolve).

Dependencies:
- DrainMiddleware (injected): controls request acceptance and in-flight tracking.
- BrokerAdapterRegistry (injected): manages adapter lifecycle.
- ReconciliationService (optional, injected): runs pre-shutdown/post-startup reconciliation.
- SQLAlchemy Engine (injected): database connection pool for disposal.
- structlog: structured logging.

Error conditions:
- Individual reconciliation or adapter failures are caught and logged, never propagated.
- Engine disposal failure is logged and swallowed.

Example:
    manager = GracefulLifecycleManager(
        drain=drain_middleware,
        broker_registry=registry,
        engine=engine,
        reconciliation_service=recon_service,
    )
    # On shutdown:
    manager.shutdown()
    # On startup:
    manager.startup_reconciliation()
"""

from __future__ import annotations

import time
from typing import Any

import structlog

from services.api.infrastructure.broker_registry import BrokerAdapterRegistry
from services.api.middleware.drain import DrainMiddleware

logger = structlog.get_logger(__name__)


class GracefulLifecycleManager:
    """
    Orchestrates graceful application shutdown and startup recovery.

    Shutdown sequence:
    1. Stop accepting new requests (drain middleware).
    2. Wait for in-flight requests to complete (configurable timeout).
    3. Run reconciliation for each active deployment (if recon service wired).
    4. Deregister all broker adapters (disconnect from brokers).
    5. Dispose database connection pool.
    6. Log shutdown summary.

    Startup recovery:
    1. Run reconciliation for each registered deployment (detects orphaned state).
    2. Log discrepancies as WARNING (no auto-resolve — operators must review).

    Responsibilities:
    - Coordinate the ordered shutdown of all subsystems.
    - Coordinate post-startup reconciliation.
    - Handle partial failures without propagating exceptions.

    Does NOT:
    - Create or register broker adapters.
    - Own the FastAPI lifespan context manager.
    - Auto-resolve reconciliation discrepancies.

    Dependencies:
    - DrainMiddleware: request acceptance and in-flight tracking.
    - BrokerAdapterRegistry: adapter lifecycle management.
    - ReconciliationService (optional): pre/post lifecycle reconciliation.
    - SQLAlchemy Engine: database pool management.

    Example:
        manager = GracefulLifecycleManager(
            drain=drain,
            broker_registry=registry,
            engine=engine,
            reconciliation_service=recon,
            drain_timeout_s=30.0,
        )
        manager.shutdown()
    """

    def __init__(
        self,
        *,
        drain: DrainMiddleware,
        broker_registry: BrokerAdapterRegistry,
        engine: Any,
        reconciliation_service: Any | None = None,
        drain_timeout_s: float = 30.0,
    ) -> None:
        """
        Initialize the lifecycle manager.

        Args:
            drain: DrainMiddleware instance for request draining.
            broker_registry: Registry of active broker adapters.
            engine: SQLAlchemy engine for connection pool disposal.
            reconciliation_service: Optional ReconciliationService for
                pre-shutdown and post-startup reconciliation.
            drain_timeout_s: Maximum seconds to wait for in-flight
                requests to drain. Default 30.
        """
        self._drain = drain
        self._registry = broker_registry
        self._engine = engine
        self._recon = reconciliation_service
        self._drain_timeout_s = drain_timeout_s

    # ------------------------------------------------------------------
    # Shutdown
    # ------------------------------------------------------------------

    def shutdown(self) -> None:
        """
        Execute the full graceful shutdown sequence.

        Steps:
        1. Stop accepting new requests.
        2. Wait for in-flight requests to drain (up to configured timeout).
        3. Reconcile each active deployment against broker state.
        4. Deregister all broker adapters (calls disconnect on each).
        5. Dispose database engine (unless SQLite in-memory).
        6. Log shutdown summary.

        All steps are fault-tolerant: individual failures are logged
        but do not prevent the remaining shutdown steps from executing.
        """
        start_time = time.monotonic()

        logger.info(
            "shutdown.starting",
            registered_adapters=self._registry.count(),
            component="lifecycle_manager",
        )

        # Step 1: Stop accepting new requests
        self._drain.stop_accepting()

        # Step 2: Wait for in-flight requests to drain
        remaining = self._drain.wait_for_drain(timeout_s=self._drain_timeout_s)
        if remaining > 0:
            logger.warning(
                "shutdown.drain_timeout",
                remaining_requests=remaining,
                timeout_s=self._drain_timeout_s,
                component="lifecycle_manager",
            )

        # Step 3: Reconcile active deployments
        recon_results = self._reconcile_deployments(trigger="shutdown")

        # Step 4: Deregister all broker adapters
        deregistered = 0
        try:
            deregistered = self._registry.deregister_all()
        except Exception:
            logger.error(
                "shutdown.deregister_all_failed",
                component="lifecycle_manager",
                exc_info=True,
            )

        # Step 5: Dispose database engine
        self._dispose_engine()

        # Step 6: Log shutdown summary
        elapsed_ms = int((time.monotonic() - start_time) * 1000)
        logger.info(
            "shutdown.complete",
            adapters_deregistered=deregistered,
            drain_remaining=remaining,
            reconciliations_attempted=recon_results["attempted"],
            reconciliations_succeeded=recon_results["succeeded"],
            reconciliations_failed=recon_results["failed"],
            duration_ms=elapsed_ms,
            component="lifecycle_manager",
        )

    # ------------------------------------------------------------------
    # Startup Recovery
    # ------------------------------------------------------------------

    def startup_reconciliation(self) -> None:
        """
        Run post-startup reconciliation for all registered deployments.

        For each deployment that has an active broker adapter, runs
        reconciliation to detect discrepancies between internal state
        and broker state. Discrepancies are logged as WARNING — they
        are NOT auto-resolved so operators can review before taking action.

        If no reconciliation service is wired, this method is a no-op.
        If no deployments are registered, this method is a no-op.

        All failures are caught and logged per-deployment without
        preventing reconciliation of other deployments.
        """
        if self._recon is None:
            logger.info(
                "startup.reconciliation_skipped",
                reason="no reconciliation service configured",
                component="lifecycle_manager",
            )
            return

        deployments = self._registry.list_deployments()
        if not deployments:
            logger.info(
                "startup.reconciliation_skipped",
                reason="no registered deployments",
                component="lifecycle_manager",
            )
            return

        logger.info(
            "startup.reconciliation_starting",
            deployment_count=len(deployments),
            component="lifecycle_manager",
        )

        results = self._reconcile_deployments(trigger="startup")

        logger.info(
            "startup.reconciliation_complete",
            attempted=results["attempted"],
            succeeded=results["succeeded"],
            failed=results["failed"],
            total_discrepancies=results["total_discrepancies"],
            component="lifecycle_manager",
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _reconcile_deployments(self, trigger: str) -> dict[str, int]:
        """
        Run reconciliation for all registered deployments.

        Args:
            trigger: Reconciliation trigger label ("startup" or "shutdown").

        Returns:
            Dict with counts: attempted, succeeded, failed, total_discrepancies.
        """
        results: dict[str, int] = {
            "attempted": 0,
            "succeeded": 0,
            "failed": 0,
            "total_discrepancies": 0,
        }

        if self._recon is None:
            return results

        deployments = self._registry.list_deployments()

        for dep_info in deployments:
            dep_id = dep_info["deployment_id"]
            results["attempted"] += 1

            try:
                report = self._recon.run_reconciliation(
                    deployment_id=dep_id,
                    trigger=trigger,
                )
                results["succeeded"] += 1

                discrepancies = getattr(report, "total_discrepancies", 0)
                results["total_discrepancies"] += discrepancies

                if discrepancies > 0:
                    unresolved = getattr(report, "unresolved_count", 0)
                    logger.warning(
                        f"{trigger}.reconciliation_discrepancies",
                        deployment_id=dep_id,
                        total_discrepancies=discrepancies,
                        unresolved=unresolved,
                        component="lifecycle_manager",
                    )
                else:
                    logger.info(
                        f"{trigger}.reconciliation_clean",
                        deployment_id=dep_id,
                        component="lifecycle_manager",
                    )

            except Exception:
                results["failed"] += 1
                logger.error(
                    f"{trigger}.reconciliation_error",
                    deployment_id=dep_id,
                    component="lifecycle_manager",
                    exc_info=True,
                )

        return results

    def _dispose_engine(self) -> None:
        """
        Dispose the database connection pool.

        Skips disposal for SQLite in-memory databases to preserve
        test data across TestClient instances that share the same engine.

        All errors are logged but swallowed.
        """
        db_url = str(self._engine.url)

        if db_url.startswith("sqlite") and ":memory:" in db_url:
            logger.info(
                "shutdown.engine_dispose_skipped",
                reason="sqlite in-memory — preserving test data",
                component="lifecycle_manager",
            )
            return

        try:
            self._engine.dispose()
            logger.info(
                "shutdown.engine_disposed",
                component="lifecycle_manager",
            )
        except Exception:
            logger.error(
                "shutdown.engine_dispose_failed",
                component="lifecycle_manager",
                exc_info=True,
            )
