"""
SQL-backed repository for Alertmanager webhook notifications.

Purpose:
    Persist ``AlertNotification`` domain records produced by the
    AlertIngestService into the ``alert_notifications`` table. This is
    the only layer in the stack that talks SQL for this entity.

Responsibilities:
    - save_batch(): atomically INSERT a list of notifications.
    - count_by_fingerprint(): operator/test introspection helper.

Does NOT:
    - Transform or enrich the notification payload.
    - Dispatch notifications to third parties.
    - Know anything about HTTP, FastAPI, or Alertmanager's wire format.

Dependencies:
    - SQLAlchemy Session (injected via constructor).
    - libs.contracts.models.AlertNotificationRecord: ORM model.
    - libs.contracts.alertmanager_webhook.AlertNotification: domain model.

Error conditions:
    - AlertNotificationRepositoryError is raised when the underlying
      store rejects the write (driver errors, integrity violations).
      The inner ``SQLAlchemyError`` is chained via ``from`` so operators
      see the full cause.

Example:
    repo = SqlAlertNotificationRepository(db=session)
    persisted = repo.save_batch([notification_a, notification_b])
    assert persisted == 2
"""

from __future__ import annotations

import structlog
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from libs.contracts.alertmanager_webhook import AlertNotification
from libs.contracts.interfaces.alert_notification_repository import (
    AlertNotificationRepositoryError,
    AlertNotificationRepositoryInterface,
)
from libs.contracts.models import AlertNotificationRecord

logger = structlog.get_logger(__name__)


class SqlAlertNotificationRepository(AlertNotificationRepositoryInterface):
    """
    Append-only SQL repository for alert notifications.

    Responsibilities:
    - INSERT batches of AlertNotification records in a single flush so
      partial writes never leak state.
    - Return accurate row counts to the caller.

    Does NOT:
    - Deduplicate, upsert, or reorder. Alertmanager's repeat_interval
      intentionally produces duplicates — they carry operational meaning.
    - commit() the session. Request-scoped commits are the caller's
      responsibility (FastAPI's ``get_db`` handles it at request end).

    Dependencies:
    - SQLAlchemy Session (injected).
    """

    def __init__(self, db: Session) -> None:
        """
        Initialise with a SQLAlchemy session.

        Args:
            db: Request-scoped SQLAlchemy session. Not retained across
                requests; the caller ensures lifetime.
        """
        self._db = db

    def save_batch(self, notifications: list[AlertNotification]) -> int:
        """
        Persist all notifications in a single transaction.

        Args:
            notifications: Pre-validated domain records. Empty list is a
                no-op that returns 0 without touching the DB.

        Returns:
            Count of rows persisted (== len(notifications) on success).

        Raises:
            AlertNotificationRepositoryError: If SQLAlchemy reports any
                driver or integrity error. The underlying exception is
                chained via ``from`` to preserve the stack.

        Example:
            repo.save_batch([n1, n2])  # → 2
        """
        if not notifications:
            logger.debug(
                "alert_notification_repository.save_batch.empty",
                component="SqlAlertNotificationRepository",
                operation="save_batch",
            )
            return 0

        try:
            records = [
                AlertNotificationRecord(
                    id=n.id,
                    fingerprint=n.fingerprint,
                    status=n.status,
                    alertname=n.alertname,
                    severity=n.severity,
                    starts_at=n.starts_at,
                    ends_at=n.ends_at,
                    labels=n.labels,
                    annotations=n.annotations,
                    generator_url=n.generator_url,
                    receiver=n.receiver,
                    external_url=n.external_url,
                    group_key=n.group_key,
                    received_at=n.received_at,
                )
                for n in notifications
            ]
            self._db.add_all(records)
            self._db.flush()
        except SQLAlchemyError as exc:
            # Roll back the flush so callers can retry without seeing
            # a half-committed state. This is safe because save_batch is
            # the only mutation in the transaction for the webhook path.
            self._db.rollback()
            logger.error(
                "alert_notification_repository.save_batch.failed",
                component="SqlAlertNotificationRepository",
                operation="save_batch",
                batch_size=len(notifications),
                error=str(exc),
                exc_info=True,
            )
            raise AlertNotificationRepositoryError(
                f"Failed to persist {len(notifications)} alert notifications"
            ) from exc

        logger.info(
            "alert_notification_repository.save_batch.succeeded",
            component="SqlAlertNotificationRepository",
            operation="save_batch",
            batch_size=len(notifications),
            result="success",
        )
        return len(notifications)

    def count_by_fingerprint(self, fingerprint: str) -> int:
        """
        Return the number of historical rows for a given fingerprint.

        Args:
            fingerprint: Alertmanager stable alert identifier.

        Returns:
            Non-negative row count (0 if never seen).

        Raises:
            AlertNotificationRepositoryError: On SQLAlchemy error.
        """
        try:
            count = (
                self._db.query(AlertNotificationRecord)
                .filter(AlertNotificationRecord.fingerprint == fingerprint)
                .count()
            )
        except SQLAlchemyError as exc:
            logger.error(
                "alert_notification_repository.count.failed",
                component="SqlAlertNotificationRepository",
                operation="count_by_fingerprint",
                fingerprint=fingerprint,
                error=str(exc),
                exc_info=True,
            )
            raise AlertNotificationRepositoryError(
                f"Failed to count rows for fingerprint {fingerprint!r}"
            ) from exc

        return int(count)
