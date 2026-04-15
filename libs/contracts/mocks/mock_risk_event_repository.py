"""
In-memory mock implementation of RiskEventRepositoryInterface.

Responsibilities:
- Provide a test double for risk event persistence.
- Support introspection helpers for test assertions.

Does NOT:
- Persist data beyond the lifetime of the instance.

Dependencies:
- libs.contracts.interfaces.risk_event_repository_interface.
- libs.contracts.risk: RiskEvent.

Example:
    repo = MockRiskEventRepository()
    repo.save(event)
    assert repo.count() == 1
"""

from __future__ import annotations

from libs.contracts.interfaces.risk_event_repository_interface import (
    RiskEventRepositoryInterface,
)
from libs.contracts.risk import RiskEvent


class MockRiskEventRepository(RiskEventRepositoryInterface):
    """
    In-memory implementation of RiskEventRepositoryInterface.

    Responsibilities:
    - Store risk events in memory for testing.
    - Support filtering by deployment and severity.
    - Provide introspection helpers (count, get_all, clear).

    Does NOT:
    - Persist data to any external store.

    Example:
        repo = MockRiskEventRepository()
        repo.save(event)
        events = repo.list_by_deployment(deployment_id="dep-001")
    """

    def __init__(self) -> None:
        self._events: list[RiskEvent] = []

    def save(self, event: RiskEvent) -> None:
        """
        Persist a risk event in memory.

        Args:
            event: RiskEvent to store.
        """
        self._events.append(event)

    def list_by_deployment(
        self,
        *,
        deployment_id: str,
        severity: str | None = None,
        limit: int = 100,
    ) -> list[RiskEvent]:
        """
        List risk events for a deployment.

        Args:
            deployment_id: ULID of the deployment.
            severity: Optional filter by severity level.
            limit: Maximum number of events to return.

        Returns:
            List of RiskEvent objects, most recent first.
        """
        filtered = [e for e in self._events if e.deployment_id == deployment_id]
        if severity is not None:
            filtered = [e for e in filtered if e.severity.value == severity]
        # Most recent first (reverse chronological by insertion order)
        filtered = list(reversed(filtered))
        return filtered[:limit]

    # ------------------------------------------------------------------
    # Introspection helpers for tests
    # ------------------------------------------------------------------

    def count(self) -> int:
        """Return total number of stored events."""
        return len(self._events)

    def get_all(self) -> list[RiskEvent]:
        """Return all stored events."""
        return list(self._events)

    def clear(self) -> None:
        """Remove all stored events."""
        self._events.clear()
