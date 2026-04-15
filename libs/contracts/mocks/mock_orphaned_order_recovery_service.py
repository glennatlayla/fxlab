"""
Mock orphaned order recovery service for unit testing.

Responsibilities:
- Implement OrphanedOrderRecoveryServiceInterface with dict-backed state.
- Provide configurable behaviour (no-op, simulated recovery, or realistic).
- Track recovery invocations for test assertions.

Does NOT:
- Perform any real broker communication.
- Persist state across process restarts.

Dependencies:
- libs.contracts.interfaces.orphaned_order_recovery_interface

Example:
    repo = MockOrphanedOrderRecoveryService()
    report = repo.recover_orphaned_orders(
        deployment_id="01HDEPLOY...",
        correlation_id="corr-001",
    )
"""

from __future__ import annotations

from datetime import datetime, timezone

from libs.contracts.interfaces.orphaned_order_recovery_interface import (
    OrphanedOrderRecoveryServiceInterface,
)
from libs.contracts.orphan_recovery import (
    OrphanRecoveryReport,
)


class MockOrphanedOrderRecoveryService(OrphanedOrderRecoveryServiceInterface):
    """
    In-memory mock orphaned order recovery service for unit tests.

    Responsibilities:
    - Simulate orphaned order recovery with configurable behaviour.
    - Track invocation counts and arguments for test assertions.
    - Provide introspection helpers for verification.

    Does NOT:
    - Perform real broker communication.
    - Actually modify order state (except in memory).

    Example:
        service = MockOrphanedOrderRecoveryService(recovered_count=2)
        report = service.recover_orphaned_orders(
            deployment_id="01HDEPLOY...",
            correlation_id="corr-001",
        )
        assert report.recovered_count == 2
        assert service.get_recover_calls()[0]["deployment_id"] == "01HDEPLOY..."
    """

    def __init__(
        self,
        recovered_count: int = 0,
        failed_count: int = 0,
        cancelled_count: int = 0,
    ) -> None:
        """
        Initialize the mock service.

        Args:
            recovered_count: Number of orders to report as recovered.
            failed_count: Number of recovery attempts to report as failed.
            cancelled_count: Number of extra broker orders to report.
        """
        self._recovered_count = recovered_count
        self._failed_count = failed_count
        self._cancelled_count = cancelled_count
        self._recover_calls: list[dict[str, str]] = []
        self._recover_all_calls: list[dict[str, str]] = []

    def recover_orphaned_orders(
        self,
        *,
        deployment_id: str,
        correlation_id: str,
    ) -> OrphanRecoveryReport:
        """
        Simulate orphaned order recovery for a deployment.

        Records the invocation and returns a report with preconfigured counts.

        Args:
            deployment_id: ULID of the deployment to recover.
            correlation_id: Distributed tracing ID.

        Returns:
            OrphanRecoveryReport with configured counts and empty details.
        """
        self._recover_calls.append(
            {
                "deployment_id": deployment_id,
                "correlation_id": correlation_id,
            }
        )

        now = datetime.now(timezone.utc)
        return OrphanRecoveryReport(
            deployment_id=deployment_id,
            recovered_count=self._recovered_count,
            cancelled_count=self._cancelled_count,
            failed_count=self._failed_count,
            details=[],
            started_at=now,
            completed_at=now,
        )

    def recover_all_deployments(
        self,
        *,
        correlation_id: str,
    ) -> list[OrphanRecoveryReport]:
        """
        Simulate batch recovery across all deployments.

        Records the invocation and returns an empty list (no deployments found).

        Args:
            correlation_id: Distributed tracing ID.

        Returns:
            Empty list (mock has no deployments).
        """
        self._recover_all_calls.append(
            {
                "correlation_id": correlation_id,
            }
        )
        return []

    # ------------------------------------------------------------------
    # Test introspection helpers
    # ------------------------------------------------------------------

    def get_recover_calls(self) -> list[dict[str, str]]:
        """
        Retrieve all recover_orphaned_orders invocations.

        Returns:
            List of call dicts with deployment_id and correlation_id.
        """
        return list(self._recover_calls)

    def get_recover_all_calls(self) -> list[dict[str, str]]:
        """
        Retrieve all recover_all_deployments invocations.

        Returns:
            List of call dicts with correlation_id.
        """
        return list(self._recover_all_calls)

    def clear(self) -> None:
        """Clear all recorded invocations."""
        self._recover_calls.clear()
        self._recover_all_calls.clear()
