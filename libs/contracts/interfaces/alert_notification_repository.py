"""
AlertNotificationRepositoryInterface — port for alert notification persistence.

Purpose:
    Define the contract every alert-notification repository implementation
    must honour so the AlertIngestService depends on an abstraction, not
    on SQLAlchemy or any other concrete storage.

Responsibilities:
    - save_batch(): persist a list of AlertNotification records in a
      single transaction (atomic — all-or-nothing).
    - count_by_fingerprint(): introspection helper used primarily by
      tests and operator tooling.

Does NOT:
    - Mutate the alert payload.
    - Dispatch notifications or call external systems.
    - Evaluate alert semantics (severity routing, dedup windows, etc.).

Dependencies:
    - libs.contracts.alertmanager_webhook: AlertNotification.

Example:
    class SqlAlertNotificationRepository(AlertNotificationRepositoryInterface):
        def save_batch(self, notifications): ...
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from libs.contracts.alertmanager_webhook import AlertNotification


class AlertNotificationRepositoryError(Exception):
    """
    Raised when the repository cannot persist a batch for any reason
    other than caller error (network, DB outage, constraint violation).

    Service-layer callers should treat this as a 5xx-class failure.
    """


class AlertNotificationRepositoryInterface(ABC):
    """
    Abstract port for alert-notification persistence.

    Implementations provide either a SQL-backed repository (production)
    or an in-memory fake (unit tests).
    """

    @abstractmethod
    def save_batch(self, notifications: list[AlertNotification]) -> int:
        """
        Persist every notification in ``notifications`` atomically.

        Args:
            notifications: Pre-validated domain records to persist. May
                be empty — implementations must handle that as a no-op
                and return 0 without touching the database.

        Returns:
            The number of rows persisted. For append-only implementations
            this equals ``len(notifications)``.

        Raises:
            AlertNotificationRepositoryError: If the underlying store
                rejects the write (connection loss, integrity error,
                driver exception).

        Example:
            count = repo.save_batch([notification_a, notification_b])
            assert count == 2
        """
        ...

    @abstractmethod
    def count_by_fingerprint(self, fingerprint: str) -> int:
        """
        Count how many rows exist for a given Alertmanager fingerprint.

        Used by operators to inspect the history of a single alert and
        by tests to assert persistence behaviour.

        Args:
            fingerprint: Alertmanager's stable alert identifier.

        Returns:
            Number of matching rows (0 if never seen).

        Raises:
            AlertNotificationRepositoryError: On transport/connection
                failure.
        """
        ...
