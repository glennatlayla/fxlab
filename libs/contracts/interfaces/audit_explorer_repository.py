"""
AuditExplorerRepositoryInterface — port for audit event read access (M9).

Purpose:
    Define the contract that all audit explorer repository implementations
    must honour, so that route handlers depend on an abstraction rather than
    on a concrete database adapter.

Responsibilities:
    - list() → filtered, cursor-paginated list of AuditEventRecord.
    - find_by_id() → single AuditEventRecord by ULID.

Does NOT:
    - Write audit events (write-side is write_audit_event() in audit.py).
    - Contain business logic.

Dependencies:
    - libs.contracts.audit_explorer: AuditEventRecord.
    - libs.contracts.errors: NotFoundError.

Error conditions:
    - find_by_id raises NotFoundError when the audit event ID is unknown.

Example:
    class SqlAuditExplorerRepository(AuditExplorerRepositoryInterface):
        def list(self, *, actor, action_type, target_type, target_id,
                 cursor, limit, correlation_id): ...
        def find_by_id(self, id, correlation_id): ...
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from libs.contracts.audit_explorer import AuditEventRecord


class AuditExplorerRepositoryInterface(ABC):
    """
    Abstract port for audit event read access.

    Implementations provide either a SQL-backed adapter (production) or
    an in-memory fake (tests).  All dependency injection targets this interface.
    """

    @abstractmethod
    def list(
        self,
        *,
        actor: str = "",
        action_type: str = "",
        target_type: str = "",
        target_id: str = "",
        cursor: str = "",
        limit: int = 50,
        correlation_id: str,
    ) -> list[AuditEventRecord]:
        """
        Return a filtered, cursor-paginated list of audit events.

        Args:
            actor:          Filter by actor identity string.  Empty = no filter.
            action_type:    Filter by action verb prefix, e.g. 'run'.  Empty = no filter.
            target_type:    Filter by object_type, e.g. 'run'.  Empty = no filter.
            target_id:      Filter by object_id ULID.  Empty = no filter.
            cursor:         Opaque cursor for next-page retrieval.  Empty = first page.
            limit:          Maximum number of events to return.
            correlation_id: Request-scoped tracing ID.

        Returns:
            List of matching AuditEventRecord (may be empty).

        Raises:
            ExternalServiceError: On underlying storage failure.
        """
        ...

    @abstractmethod
    def find_by_id(self, id: str, correlation_id: str) -> AuditEventRecord:
        """
        Return a single audit event by ULID.

        Args:
            id:             ULID of the audit event.
            correlation_id: Request-scoped tracing ID.

        Returns:
            AuditEventRecord for the given ID.

        Raises:
            NotFoundError: If no audit event exists with the given ID.
        """
        ...
