"""
Risk alert config repository interface (port).

Responsibilities:
- Define the abstract contract for risk alert configuration persistence.
- Serve as the dependency injection target for services and tests.

Does NOT:
- Implement persistence logic (adapter responsibility).
- Contain business logic (service responsibility).

Dependencies:
- None (pure interface).

Error conditions:
- NotFoundError: config not found for deployment_id.

Example:
    repo: RiskAlertConfigRepositoryInterface = SqlRiskAlertConfigRepository(db)
    config = repo.find_by_deployment_id("01H...")
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from libs.contracts.risk_alert import RiskAlertConfig


class RiskAlertConfigRepositoryInterface(ABC):
    """
    Port interface for risk alert configuration persistence.

    Responsibilities:
    - Read, write, and list alert configurations.

    Does NOT:
    - Evaluate alerts or dispatch notifications.
    """

    @abstractmethod
    def find_by_deployment_id(self, deployment_id: str) -> RiskAlertConfig | None:
        """
        Find alert config for a deployment.

        Args:
            deployment_id: Target deployment.

        Returns:
            RiskAlertConfig if found, None otherwise.
        """
        ...

    @abstractmethod
    def save(self, config: RiskAlertConfig) -> RiskAlertConfig:
        """
        Create or update an alert configuration.

        Upserts by deployment_id.

        Args:
            config: Alert configuration to persist.

        Returns:
            The saved RiskAlertConfig.
        """
        ...

    @abstractmethod
    def find_all(self) -> list[RiskAlertConfig]:
        """
        List all alert configurations.

        Returns:
            List of all persisted RiskAlertConfig entries.
        """
        ...

    @abstractmethod
    def find_all_enabled(self) -> list[RiskAlertConfig]:
        """
        List all enabled alert configurations.

        Returns:
            List of enabled RiskAlertConfig entries.
        """
        ...
