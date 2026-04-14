"""
CertificationRepositoryInterface — port for feed certification data access (M8).

Purpose:
    Define the contract that all certification repository implementations must
    honour, so that service and route layers depend on an abstraction (not on
    a concrete database or API adapter).

Responsibilities:
    - list() → return all CertificationEvent records.
    - find_by_feed_id() → return the CertificationEvent for a specific feed.

Does NOT:
    - Contain business logic (that lives in the service layer).
    - Connect to any database or external system (concrete adapters do that).

Dependencies:
    - libs.contracts.certification: CertificationEvent (domain contract).
    - libs.contracts.errors: NotFoundError.

Error conditions:
    - find_by_feed_id raises NotFoundError when the feed_id is unknown.

Example:
    class SqlCertificationRepository(CertificationRepositoryInterface):
        def list(self, correlation_id: str) -> list[CertificationEvent]: ...
        def find_by_feed_id(self, feed_id: str, correlation_id: str) -> CertificationEvent: ...
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from libs.contracts.certification import CertificationEvent


class CertificationRepositoryInterface(ABC):
    """
    Abstract port for certification data access.

    Implementations provide either a SQL-backed adapter (production) or
    an in-memory fake (tests).  All dependency injection targets this interface.
    """

    @abstractmethod
    def list(self, correlation_id: str) -> list[CertificationEvent]:
        """
        Return all certification events.

        Args:
            correlation_id: Request-scoped tracing ID for structured logging.

        Returns:
            List of CertificationEvent (may be empty).

        Raises:
            ExternalServiceError: On underlying storage failure.
        """
        ...

    @abstractmethod
    def find_by_feed_id(self, feed_id: str, correlation_id: str) -> CertificationEvent:
        """
        Return the certification event for a specific feed.

        Args:
            feed_id:          ULID of the feed to look up.
            correlation_id:   Request-scoped tracing ID.

        Returns:
            CertificationEvent for the specified feed.

        Raises:
            NotFoundError: If no certification record exists for feed_id.
        """
        ...
