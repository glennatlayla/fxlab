"""
Notification provider interface (Phase 6 — M13).

Purpose:
    Define the abstract port for notification delivery so that the
    notification dispatch service depends on an interface, not on
    concrete HTTP client implementations.

Responsibilities:
    - send_alert: Deliver an incident alert to the provider.
    - send_resolution: Notify the provider that an incident is resolved.

Does NOT:
    - Contain routing logic (notification service responsibility).
    - Track incident lifecycle (incident manager responsibility).

Dependencies:
    - IncidentRecord, NotificationResult contracts.

Example:
    class MyProvider(NotificationProviderInterface):
        def send_alert(self, incident: IncidentRecord) -> NotificationResult:
            ...
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from libs.contracts.notification import IncidentRecord, NotificationResult


class NotificationProviderInterface(ABC):
    """
    Abstract port for external notification delivery.

    Implementations translate IncidentRecord data into provider-specific
    API calls (Slack webhooks, PagerDuty Events API, etc.).

    Responsibilities:
        - send_alert: Fire an alert for a new or escalated incident.
        - send_resolution: Notify resolution of a previously alerted incident.

    Does NOT:
        - Decide when to send (caller responsibility).
        - Retry on failure (resilient adapter or caller responsibility).

    Error conditions:
        - ExternalServiceError / TransientError on API failures.

    Example:
        result = provider.send_alert(incident)
        if not result.success:
            logger.warning("notification failed", error=result.error_message)
    """

    @abstractmethod
    def send_alert(self, incident: IncidentRecord) -> NotificationResult:
        """
        Deliver an alert notification for the given incident.

        Args:
            incident: The incident to alert on.

        Returns:
            NotificationResult indicating success/failure.
        """

    @abstractmethod
    def send_resolution(self, incident: IncidentRecord) -> NotificationResult:
        """
        Notify that the given incident has been resolved.

        Args:
            incident: The resolved incident.

        Returns:
            NotificationResult indicating success/failure.
        """
