"""
Unit tests for M11 graceful shutdown and startup recovery.

Covers:
- GracefulLifecycleManager shutdown sequence:
  1. Drain middleware stops accepting
  2. Wait for in-flight requests to drain
  3. Reconcile active deployments
  4. Deregister all broker adapters
  5. Dispose database connections
  6. Log shutdown summary
- GracefulLifecycleManager startup sequence:
  1. Load active deployments from DB
  2. Reconnect broker adapters
  3. Run startup reconciliation
  4. Log startup summary
- Shutdown timeout handling
- Partial failure during shutdown (some adapters fail to disconnect)
- Startup reconciliation discrepancy detection

Dependencies:
- services.api.infrastructure.lifecycle_manager: GracefulLifecycleManager
- services.api.middleware.drain: DrainMiddleware
- services.api.infrastructure.broker_registry: BrokerAdapterRegistry
"""

from __future__ import annotations

from typing import Any
from unittest.mock import MagicMock, patch

from services.api.infrastructure.lifecycle_manager import GracefulLifecycleManager
from services.api.middleware.drain import DrainMiddleware

# ------------------------------------------------------------------
# Helpers
# ------------------------------------------------------------------


def _make_mock_engine() -> MagicMock:
    """Create a mock SQLAlchemy engine."""
    engine = MagicMock()
    engine.url = "postgresql://localhost/fxlab"
    return engine


def _make_mock_registry(deployment_count: int = 0) -> MagicMock:
    """Create a mock BrokerAdapterRegistry."""
    registry = MagicMock()
    registry.count.return_value = deployment_count
    registry.deregister_all.return_value = deployment_count
    deployments = [
        {"deployment_id": f"dep-{i:03d}", "broker_type": "mock"} for i in range(deployment_count)
    ]
    registry.list_deployments.return_value = deployments
    return registry


def _make_mock_reconciliation_service() -> MagicMock:
    """Create a mock ReconciliationService."""
    service = MagicMock()
    # run_reconciliation returns a report-like dict
    service.run_reconciliation.return_value = MagicMock(
        deployment_id="dep-000",
        trigger="shutdown",
        total_discrepancies=0,
        resolved_count=0,
        unresolved_count=0,
    )
    return service


def _make_mock_deployment_repo(active_deployments: list[dict[str, Any]] | None = None) -> MagicMock:
    """Create a mock deployment repository."""
    repo = MagicMock()
    if active_deployments is None:
        active_deployments = []
    repo.list_active.return_value = active_deployments
    return repo


# ------------------------------------------------------------------
# Tests: Shutdown Sequence
# ------------------------------------------------------------------


class TestShutdownSequence:
    """GracefulLifecycleManager shutdown follows the correct order."""

    def test_shutdown_stops_accepting_requests(self) -> None:
        """Shutdown sets drain middleware to not-accepting."""
        drain = DrainMiddleware()
        manager = GracefulLifecycleManager(
            drain=drain,
            broker_registry=_make_mock_registry(),
            engine=_make_mock_engine(),
        )
        assert drain.is_accepting is True
        manager.shutdown()
        assert drain.is_accepting is False

    def test_shutdown_waits_for_drain(self) -> None:
        """Shutdown calls wait_for_drain with configured timeout."""
        drain = DrainMiddleware()
        registry = _make_mock_registry()
        manager = GracefulLifecycleManager(
            drain=drain,
            broker_registry=registry,
            engine=_make_mock_engine(),
            drain_timeout_s=15.0,
        )
        with patch.object(drain, "wait_for_drain", return_value=0) as mock_wait:
            manager.shutdown()
            mock_wait.assert_called_once_with(timeout_s=15.0)

    def test_shutdown_reconciles_active_deployments(self) -> None:
        """Shutdown runs reconciliation for each active deployment."""
        drain = DrainMiddleware()
        registry = _make_mock_registry(deployment_count=2)
        recon = _make_mock_reconciliation_service()
        manager = GracefulLifecycleManager(
            drain=drain,
            broker_registry=registry,
            engine=_make_mock_engine(),
            reconciliation_service=recon,
        )
        manager.shutdown()
        assert recon.run_reconciliation.call_count == 2

    def test_shutdown_deregisters_all_adapters(self) -> None:
        """Shutdown calls deregister_all on the broker registry."""
        drain = DrainMiddleware()
        registry = _make_mock_registry(deployment_count=3)
        manager = GracefulLifecycleManager(
            drain=drain,
            broker_registry=registry,
            engine=_make_mock_engine(),
        )
        manager.shutdown()
        registry.deregister_all.assert_called_once()

    def test_shutdown_disposes_engine(self) -> None:
        """Shutdown disposes the database engine."""
        drain = DrainMiddleware()
        engine = _make_mock_engine()
        manager = GracefulLifecycleManager(
            drain=drain,
            broker_registry=_make_mock_registry(),
            engine=engine,
        )
        manager.shutdown()
        engine.dispose.assert_called_once()

    def test_shutdown_skips_dispose_for_sqlite_memory(self) -> None:
        """Shutdown does NOT dispose SQLite in-memory engine (preserves test data)."""
        drain = DrainMiddleware()
        engine = MagicMock()
        engine.url = "sqlite:///:memory:"
        manager = GracefulLifecycleManager(
            drain=drain,
            broker_registry=_make_mock_registry(),
            engine=engine,
        )
        manager.shutdown()
        engine.dispose.assert_not_called()

    def test_shutdown_with_no_reconciliation_service(self) -> None:
        """Shutdown works when no reconciliation service is provided."""
        drain = DrainMiddleware()
        registry = _make_mock_registry(deployment_count=2)
        manager = GracefulLifecycleManager(
            drain=drain,
            broker_registry=registry,
            engine=_make_mock_engine(),
        )
        # Should not raise
        manager.shutdown()
        registry.deregister_all.assert_called_once()

    def test_shutdown_logs_summary(self) -> None:
        """Shutdown logs a summary with adapter count and drain info."""
        drain = DrainMiddleware()
        registry = _make_mock_registry(deployment_count=1)
        manager = GracefulLifecycleManager(
            drain=drain,
            broker_registry=registry,
            engine=_make_mock_engine(),
        )
        # This test verifies no exception is raised during summary logging
        manager.shutdown()


# ------------------------------------------------------------------
# Tests: Shutdown Failure Handling
# ------------------------------------------------------------------


class TestShutdownFailureHandling:
    """Shutdown handles partial failures gracefully."""

    def test_shutdown_continues_on_reconciliation_failure(self) -> None:
        """Reconciliation failure for one deployment does not block others."""
        drain = DrainMiddleware()
        registry = _make_mock_registry(deployment_count=2)
        recon = _make_mock_reconciliation_service()
        recon.run_reconciliation.side_effect = [
            Exception("broker unreachable"),
            MagicMock(total_discrepancies=0),
        ]
        manager = GracefulLifecycleManager(
            drain=drain,
            broker_registry=registry,
            engine=_make_mock_engine(),
            reconciliation_service=recon,
        )
        # Should NOT raise — reconciliation errors are caught
        manager.shutdown()
        assert recon.run_reconciliation.call_count == 2
        registry.deregister_all.assert_called_once()

    def test_shutdown_continues_on_drain_timeout(self) -> None:
        """Shutdown proceeds even if drain timeout is exceeded."""
        drain = DrainMiddleware()
        registry = _make_mock_registry()
        manager = GracefulLifecycleManager(
            drain=drain,
            broker_registry=registry,
            engine=_make_mock_engine(),
            drain_timeout_s=0.1,
        )
        # Simulate in-flight request that won't complete
        drain._in_flight.increment()
        manager.shutdown()
        # Shutdown should still deregister and dispose
        registry.deregister_all.assert_called_once()
        # Clean up
        drain._in_flight.decrement()


# ------------------------------------------------------------------
# Tests: Startup Recovery
# ------------------------------------------------------------------


class TestStartupRecovery:
    """Startup reconnects adapters and runs reconciliation."""

    def test_startup_runs_reconciliation_for_active_deployments(self) -> None:
        """Startup triggers reconciliation for each active deployment."""
        drain = DrainMiddleware()
        registry = _make_mock_registry(deployment_count=2)
        recon = _make_mock_reconciliation_service()
        manager = GracefulLifecycleManager(
            drain=drain,
            broker_registry=registry,
            engine=_make_mock_engine(),
            reconciliation_service=recon,
        )
        manager.startup_reconciliation()
        assert recon.run_reconciliation.call_count == 2

    def test_startup_reconciliation_logs_discrepancies(self) -> None:
        """Startup logs WARNING when reconciliation finds discrepancies."""
        drain = DrainMiddleware()
        registry = _make_mock_registry(deployment_count=1)
        recon = _make_mock_reconciliation_service()
        recon.run_reconciliation.return_value = MagicMock(
            deployment_id="dep-000",
            trigger="startup",
            total_discrepancies=3,
            resolved_count=1,
            unresolved_count=2,
        )
        manager = GracefulLifecycleManager(
            drain=drain,
            broker_registry=registry,
            engine=_make_mock_engine(),
            reconciliation_service=recon,
        )
        # Should not raise — discrepancies are logged, not auto-resolved
        manager.startup_reconciliation()

    def test_startup_reconciliation_continues_on_failure(self) -> None:
        """Reconciliation failure for one deployment does not block others."""
        drain = DrainMiddleware()
        registry = _make_mock_registry(deployment_count=3)
        recon = _make_mock_reconciliation_service()
        recon.run_reconciliation.side_effect = [
            Exception("connection refused"),
            MagicMock(total_discrepancies=0),
            MagicMock(total_discrepancies=0),
        ]
        manager = GracefulLifecycleManager(
            drain=drain,
            broker_registry=registry,
            engine=_make_mock_engine(),
            reconciliation_service=recon,
        )
        manager.startup_reconciliation()
        assert recon.run_reconciliation.call_count == 3

    def test_startup_reconciliation_noop_without_service(self) -> None:
        """Startup reconciliation is a no-op when no recon service is wired."""
        drain = DrainMiddleware()
        registry = _make_mock_registry(deployment_count=2)
        manager = GracefulLifecycleManager(
            drain=drain,
            broker_registry=registry,
            engine=_make_mock_engine(),
        )
        # Should not raise
        manager.startup_reconciliation()

    def test_startup_reconciliation_noop_with_no_deployments(self) -> None:
        """Startup reconciliation skips if no deployments are registered."""
        drain = DrainMiddleware()
        registry = _make_mock_registry(deployment_count=0)
        recon = _make_mock_reconciliation_service()
        manager = GracefulLifecycleManager(
            drain=drain,
            broker_registry=registry,
            engine=_make_mock_engine(),
            reconciliation_service=recon,
        )
        manager.startup_reconciliation()
        recon.run_reconciliation.assert_not_called()
