"""
Risk alert service interface (port).

Responsibilities:
- Define the abstract contract for risk alert evaluation and configuration.
- Serve as the dependency injection target for controllers and tests.

Does NOT:
- Implement alert evaluation logic (service implementation responsibility).
- Dispatch notifications (IncidentManager responsibility).

Dependencies:
- None (pure interface).

Error conditions:
- NotFoundError: deployment not found.
- ValidationError: invalid alert configuration.

Example:
    service: RiskAlertServiceInterface = RiskAlertService(...)
    result = service.evaluate_alerts(deployment_id="01H...")
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from libs.contracts.risk_alert import (
    RiskAlertConfig,
    RiskAlertEvaluation,
)


class RiskAlertServiceInterface(ABC):
    """
    Port interface for risk alert evaluation and configuration.

    Responsibilities:
    - Evaluate risk metrics against configured thresholds.
    - Manage alert configurations per deployment.
    - List active alert configurations.

    Does NOT:
    - Dispatch notifications directly (delegates to IncidentManager).
    - Persist alert history (repository responsibility).
    """

    @abstractmethod
    def evaluate_alerts(self, deployment_id: str) -> RiskAlertEvaluation:
        """
        Evaluate all risk alert rules for a deployment.

        Computes current VaR, concentration, and correlation metrics,
        then compares against configured thresholds. Any breaches are
        dispatched to the IncidentManager for notification.

        Args:
            deployment_id: Target deployment to evaluate.

        Returns:
            RiskAlertEvaluation with list of triggered alerts.

        Raises:
            NotFoundError: If the deployment has no positions.
        """
        ...

    @abstractmethod
    def get_config(self, deployment_id: str) -> RiskAlertConfig:
        """
        Get the alert configuration for a deployment.

        Args:
            deployment_id: Target deployment.

        Returns:
            RiskAlertConfig for the deployment (defaults if not configured).
        """
        ...

    @abstractmethod
    def update_config(self, config: RiskAlertConfig) -> RiskAlertConfig:
        """
        Create or update the alert configuration for a deployment.

        Args:
            config: New alert configuration.

        Returns:
            The saved RiskAlertConfig.
        """
        ...

    @abstractmethod
    def list_configs(self) -> list[RiskAlertConfig]:
        """
        List all alert configurations.

        Returns:
            List of all configured RiskAlertConfig entries.
        """
        ...
