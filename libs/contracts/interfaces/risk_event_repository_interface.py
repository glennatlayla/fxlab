"""
Risk event repository interface (port).

Responsibilities:
- Define the abstract contract for risk event persistence.
- Risk events form an append-only audit trail.

Does NOT:
- Implement storage logic (repository adapters do that).
- Make risk decisions (service responsibility).

Dependencies:
- libs.contracts.risk: RiskEvent.

Example:
    repo: RiskEventRepositoryInterface = SqlRiskEventRepository(db)
    repo.save(event)
    events = repo.list_by_deployment(deployment_id="01HDEPLOY...")
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from libs.contracts.risk import RiskEvent


class RiskEventRepositoryInterface(ABC):
    """
    Port interface for risk event persistence.

    Risk events are append-only — they are never updated or deleted.

    Implementations:
    - SqlRiskEventRepository — SQL implementation (M5)
    - MockRiskEventRepository — In-memory mock for testing
    """

    @abstractmethod
    def save(self, event: RiskEvent) -> None:
        """
        Persist a risk event.

        Args:
            event: RiskEvent to persist.
        """
        ...

    @abstractmethod
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
        ...
