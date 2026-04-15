"""
AlertIngestService — service layer for Alertmanager webhook ingestion.

Purpose:
    Translate a parsed Alertmanager v4 webhook payload into canonical
    ``AlertNotification`` domain records and persist them atomically via
    the injected repository.

Responsibilities:
    - Generate a unique ``AlertNotification.id`` per alert in the batch.
    - Stamp a single ``received_at`` timestamp on every notification in
      one batch so related rows group cleanly.
    - Emit structured log lines at every material step for operator
      observability (batch started, persisted, failed).

Does NOT:
    - Parse raw HTTP JSON (controllers call model_validate).
    - Dispatch notifications to external channels (Slack, PagerDuty,
      email) — that is the downstream responsibility of whatever
      subscribes to the persisted log.

Dependencies:
    - AlertNotificationRepositoryInterface (injected).
    - ULID factory callable (injected; default: ``ulid.new``).
    - Clock callable (injected; default: ``lambda: datetime.now(UTC)``).
    - structlog logger (module-level).

Error conditions:
    - AlertIngestServiceError: wraps any
      AlertNotificationRepositoryError raised by the repository.

Example:
    service = AlertIngestService(repository=repo)
    result = service.ingest(payload, correlation_id="corr-123")
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timezone

import structlog
from ulid import ULID

from libs.contracts.alertmanager_webhook import (
    AlertIngestResult,
    AlertmanagerWebhookPayload,
    AlertNotification,
)
from libs.contracts.interfaces.alert_ingest_service import (
    AlertIngestServiceError,
    AlertIngestServiceInterface,
)
from libs.contracts.interfaces.alert_notification_repository import (
    AlertNotificationRepositoryError,
    AlertNotificationRepositoryInterface,
)

logger = structlog.get_logger(__name__)


class AlertIngestService(AlertIngestServiceInterface):
    """
    Default implementation of AlertIngestServiceInterface.

    Thread-safety:
        Stateless aside from its injected dependencies. Safe to share
        across request handlers as long as the injected repository and
        clock are likewise stateless (FastAPI injects a per-request
        repository via the DI container, satisfying that contract).
    """

    def __init__(
        self,
        *,
        repository: AlertNotificationRepositoryInterface,
        id_factory: Callable[[], str] | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        """
        Initialise the service.

        Args:
            repository: Where persisted notifications go.
            id_factory: Optional callable returning a unique string ID
                per invocation. Defaults to a ULID factory. Injected for
                deterministic tests.
            clock: Optional callable returning the current UTC time.
                Defaults to ``datetime.now(timezone.utc)``. Injected for
                deterministic tests.
        """
        self._repository = repository
        self._id_factory = id_factory or _default_id_factory
        self._clock = clock or _default_clock

    def ingest(
        self,
        payload: AlertmanagerWebhookPayload,
        *,
        correlation_id: str,
    ) -> AlertIngestResult:
        """
        Persist every alert in ``payload`` in one batch.

        Args:
            payload: Pre-validated Alertmanager v4 payload.
            correlation_id: Request-scoped tracing ID.

        Returns:
            AlertIngestResult summarising counts and echoing the
            correlation_id/group_key for log-stitching.

        Raises:
            AlertIngestServiceError: If the repository rejects the batch.
        """
        received_count = len(payload.alerts)
        received_at = self._clock()

        logger.info(
            "alert_ingest_service.batch_received",
            operation="alert_ingest",
            correlation_id=correlation_id,
            component="AlertIngestService",
            received_count=received_count,
            group_key=payload.groupKey,
            receiver=payload.receiver,
        )

        notifications: list[AlertNotification] = [
            AlertNotification.from_payload(
                id=self._id_factory(),
                payload=payload,
                alert=alert,
                received_at=received_at,
            )
            for alert in payload.alerts
        ]

        try:
            persisted = self._repository.save_batch(notifications)
        except AlertNotificationRepositoryError as exc:
            logger.error(
                "alert_ingest_service.persist_failed",
                operation="alert_ingest",
                correlation_id=correlation_id,
                component="AlertIngestService",
                received_count=received_count,
                error=str(exc),
                exc_info=True,
            )
            raise AlertIngestServiceError("Failed to persist alert notifications") from exc

        logger.info(
            "alert_ingest_service.batch_persisted",
            operation="alert_ingest",
            correlation_id=correlation_id,
            component="AlertIngestService",
            received_count=received_count,
            persisted_count=persisted,
            group_key=payload.groupKey,
            result="success",
        )

        return AlertIngestResult(
            received_count=received_count,
            persisted_count=persisted,
            correlation_id=correlation_id,
            group_key=payload.groupKey,
        )


# ---------------------------------------------------------------------------
# Default factories (module-level so they can be imported by tests)
# ---------------------------------------------------------------------------


def _default_id_factory() -> str:
    """Return a fresh ULID as a 26-character string."""
    return str(ULID())


def _default_clock() -> datetime:
    """Return the current UTC time as an aware datetime."""
    return datetime.now(timezone.utc)
