"""
AlertIngestServiceInterface — port for Alertmanager webhook ingestion.

Purpose:
    Define the contract the observability route layer uses to hand a
    parsed Alertmanager payload into the service layer for persistence
    and structured logging.

Responsibilities:
    - ingest(): accept a validated ``AlertmanagerWebhookPayload``,
      transform it into domain ``AlertNotification`` records, persist
      the batch, and return an ``AlertIngestResult`` summary.

Does NOT:
    - Parse or validate HTTP payloads (the controller does this by
      calling ``AlertmanagerWebhookPayload.model_validate``).
    - Dispatch notifications to third parties (email/Slack/PagerDuty).

Dependencies:
    - libs.contracts.alertmanager_webhook:
      AlertmanagerWebhookPayload, AlertIngestResult.

Example:
    class AlertIngestService(AlertIngestServiceInterface):
        def ingest(self, payload, *, correlation_id): ...
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from libs.contracts.alertmanager_webhook import (
    AlertIngestResult,
    AlertmanagerWebhookPayload,
)


class AlertIngestServiceError(Exception):
    """
    Raised when ingestion fails for any non-input-validation reason.

    Controllers should translate this into a 5xx response (the operator
    reading the logs has enough context from the chained cause).
    """


class AlertIngestServiceInterface(ABC):
    """
    Abstract port for Alertmanager webhook ingestion.

    Implementations delegate persistence to an injected
    AlertNotificationRepositoryInterface and ULID generation to an
    injected factory, so tests can inject deterministic variants.
    """

    @abstractmethod
    def ingest(
        self,
        payload: AlertmanagerWebhookPayload,
        *,
        correlation_id: str,
    ) -> AlertIngestResult:
        """
        Ingest one Alertmanager webhook batch.

        Args:
            payload: Pre-validated Alertmanager v4 payload.
            correlation_id: Request-scoped tracing ID, echoed into the
                result so the route can include it in the HTTP response.

        Returns:
            AlertIngestResult summarising how many alerts were received
            versus persisted.

        Raises:
            AlertIngestServiceError: If persistence fails. The underlying
                cause is chained via ``from`` so operators can diagnose.

        Example:
            result = service.ingest(payload, correlation_id="corr-1")
            assert result.persisted_count == len(payload.alerts)
        """
        ...
