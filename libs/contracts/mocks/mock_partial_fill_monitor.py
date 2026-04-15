"""
In-memory mock partial fill monitor for unit testing.

Responsibilities:
- Implement PartialFillMonitorInterface with configurable behaviour.
- Store resolution records in memory for test assertions.
- Support seed() and introspection helpers for test setup and inspection.
- Match the behavioural contract of the production service.

Does NOT:
- Persist data across process restarts.
- Contain business logic or partial fill resolution rules.
- Communicate with any broker or repository.

Dependencies:
- libs.contracts.interfaces.partial_fill_monitor_interface.PartialFillMonitorInterface

Error conditions:
- Configurable via set_next_error() to simulate broker failures.

Example:
    monitor = MockPartialFillMonitor()
    resolutions = monitor.check_partial_fills(
        deployment_id="01HDEPLOY...",
        policy=PartialFillPolicy(),
        correlation_id="corr-001",
    )
    assert len(resolutions) == 0  # No partial fills seeded
"""

from __future__ import annotations

from datetime import datetime, timezone

from libs.contracts.errors import ExternalServiceError, TransientError
from libs.contracts.interfaces.partial_fill_monitor_interface import (
    PartialFillMonitorInterface,
)
from libs.contracts.partial_fill import PartialFillPolicy, PartialFillResolution


class MockPartialFillMonitor(PartialFillMonitorInterface):
    """
    In-memory implementation of PartialFillMonitorInterface for unit tests.

    Responsibilities:
    - Store resolution records in a list keyed by deployment_id.
    - Maintain a list of seeded partial fill scenarios.
    - Simulate broker responses for testing partial fill logic.
    - Provide seed() for prepopulating test data.
    - Provide introspection helpers for assertions.

    Does NOT:
    - Persist data across test runs.
    - Make actual broker calls.
    - Update order status (caller responsibility in tests).

    Example:
        monitor = MockPartialFillMonitor()
        monitor.seed_resolution(
            order_id="01HORDER...",
            action_taken="cancelled_remaining",
        )
        resolutions = monitor.check_partial_fills(
            deployment_id="01HDEPLOY...",
            policy=PartialFillPolicy(),
            correlation_id="corr-001",
        )
        assert len(resolutions) == 1
    """

    def __init__(self) -> None:
        """Initialize the mock monitor."""
        # Maps (deployment_id, correlation_id) → list of resolutions
        self._resolutions: dict[tuple[str, str], list[PartialFillResolution]] = {}
        # Optional error to raise on next call
        self._next_error: ExternalServiceError | TransientError | None = None
        # Count of check_partial_fills calls
        self._call_count = 0

    # ------------------------------------------------------------------
    # Interface method
    # ------------------------------------------------------------------

    def check_partial_fills(
        self,
        *,
        deployment_id: str,
        policy: PartialFillPolicy,
        correlation_id: str,
    ) -> list[PartialFillResolution]:
        """
        Return preseeded resolutions for testing.

        If set_next_error() was called, raises that error instead of
        returning resolutions.

        Args:
            deployment_id: ULID of the deployment (used as key).
            policy: PartialFillPolicy (unused in mock, just for signature match).
            correlation_id: Correlation ID (used as key).

        Returns:
            List of seeded PartialFillResolution records.

        Raises:
            ExternalServiceError or TransientError if set_next_error() was called.
        """
        self._call_count += 1

        # Check if an error should be raised
        if self._next_error is not None:
            error = self._next_error
            self._next_error = None  # One-time error
            raise error

        key = (deployment_id, correlation_id)
        return list(self._resolutions.get(key, []))

    # ------------------------------------------------------------------
    # Test helpers / introspection
    # ------------------------------------------------------------------

    def seed_resolution(
        self,
        *,
        deployment_id: str = "01HTESTDEP0000000000000001",
        order_id: str = "01HTESTORD0000000000000001",
        broker_order_id: str = "TEST-12345",
        original_quantity: str = "1000",
        filled_quantity: str = "750",
        fill_ratio: float = 0.75,
        action_taken: str = "cancelled_remaining",
        cancelled_at: datetime | None = None,
        error_message: str | None = None,
        correlation_id: str = "test-corr-001",
    ) -> PartialFillResolution:
        """
        Prepopulate a resolution record for test setup.

        Args:
            deployment_id: Deployment ULID (key for storage).
            order_id: Order ULID.
            broker_order_id: Broker-assigned order ID.
            original_quantity: Original order quantity.
            filled_quantity: Quantity already filled.
            fill_ratio: Fill ratio (0.0-1.0).
            action_taken: Action that was taken.
            cancelled_at: Cancellation timestamp (if applicable).
            error_message: Error details (if applicable).
            correlation_id: Correlation ID (key for storage).

        Returns:
            Seeded PartialFillResolution.

        Example:
            res = monitor.seed_resolution(
                deployment_id="01HDEPLOY...",
                order_id="01HORDER...",
                action_taken="cancelled_remaining",
            )
        """
        if cancelled_at is None and action_taken == "cancelled_remaining":
            cancelled_at = datetime.now(tz=timezone.utc)

        resolution = PartialFillResolution(
            order_id=order_id,
            broker_order_id=broker_order_id,
            original_quantity=original_quantity,
            filled_quantity=filled_quantity,
            fill_ratio=fill_ratio,
            action_taken=action_taken,  # type: ignore[arg-type]
            cancelled_at=cancelled_at,
            error_message=error_message,
        )

        key = (deployment_id, correlation_id)
        if key not in self._resolutions:
            self._resolutions[key] = []
        self._resolutions[key].append(resolution)

        return resolution

    def set_next_error(self, error: ExternalServiceError | TransientError) -> None:
        """
        Configure the mock to raise an error on the next call.

        The error is raised once and then cleared (one-time error).

        Args:
            error: Exception to raise on next check_partial_fills() call.

        Example:
            monitor.set_next_error(
                TransientError("Broker timeout")
            )
            with pytest.raises(TransientError):
                monitor.check_partial_fills(...)
        """
        self._next_error = error

    def call_count(self) -> int:
        """Return the number of check_partial_fills() calls made."""
        return self._call_count

    def get_resolutions(
        self,
        *,
        deployment_id: str,
        correlation_id: str,
    ) -> list[PartialFillResolution]:
        """
        Retrieve all resolutions for a deployment and correlation ID.

        Args:
            deployment_id: Deployment ULID.
            correlation_id: Correlation ID.

        Returns:
            List of seeded resolutions (may be empty).
        """
        key = (deployment_id, correlation_id)
        return list(self._resolutions.get(key, []))

    def clear(self) -> None:
        """Remove all stored resolutions and reset state."""
        self._resolutions.clear()
        self._next_error = None
        self._call_count = 0
