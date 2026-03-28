"""
MockAuditExplorerRepository — in-memory AuditExplorerRepositoryInterface for unit tests (M9).

Purpose:
    Provide a fast, fully controllable fake implementation of
    AuditExplorerRepositoryInterface so that unit tests can exercise
    audit explorer route handlers without a real database.

Responsibilities:
    - Store AuditEventRecord objects in memory, keyed by id.
    - Implement list() with filtering on actor, action_type, target_type, target_id.
    - Implement find_by_id() with the same error contract as the real implementation.
    - Provide save() and clear() introspection helpers for test setup/teardown.

Does NOT:
    - Implement cursor pagination (always returns the full matching set in tests).
    - Connect to any database or external system.
    - Write audit events.

Dependencies:
    - AuditExplorerRepositoryInterface (parent).
    - AuditEventRecord (domain contract).
    - NotFoundError (typed exception).

Error conditions:
    - find_by_id raises NotFoundError for unknown audit event IDs.

Example:
    repo = MockAuditExplorerRepository()
    repo.save(
        AuditEventRecord(
            id="01HQAUDIT0AAAAAAAAAAAAAAAA",
            actor="analyst@fxlab.io",
            action="run.started",
            object_id="01HQRUN0AAAAAAAAAAAAAAAA0",
            object_type="run",
            correlation_id="corr-123",
            created_at=datetime.now(timezone.utc),
        )
    )
    events = repo.list(correlation_id="test")
"""

from __future__ import annotations

from libs.contracts.audit_explorer import AuditEventRecord
from libs.contracts.errors import NotFoundError
from libs.contracts.interfaces.audit_explorer_repository import (
    AuditExplorerRepositoryInterface,
)


class MockAuditExplorerRepository(AuditExplorerRepositoryInterface):
    """
    In-memory AuditExplorerRepositoryInterface for unit tests.

    Thread-safety: Not thread-safe.  Use only in synchronous unit tests.
    """

    def __init__(self) -> None:
        # Insertion-order-preserving dict, keyed by audit event ID.
        self._store: dict[str, AuditEventRecord] = {}

    # ------------------------------------------------------------------
    # AuditExplorerRepositoryInterface implementation
    # ------------------------------------------------------------------

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
        Return a filtered list of audit events (no cursor pagination in mock).

        Filtering is applied as an AND of all non-empty parameters.
        `cursor` is ignored; `limit` caps the result list.

        Args:
            actor:          Filter by actor when non-empty.
            action_type:    Filter by action prefix when non-empty.
            target_type:    Filter by object_type when non-empty.
            target_id:      Filter by object_id when non-empty.
            cursor:         Ignored in mock.
            limit:          Maximum result count.
            correlation_id: Ignored in mock; accepted for interface parity.

        Returns:
            List of matching AuditEventRecord (may be empty).
        """
        results: list[AuditEventRecord] = []
        for record in self._store.values():
            if actor and record.actor != actor:
                continue
            if action_type and not record.action.startswith(action_type):
                continue
            if target_type and record.object_type != target_type:
                continue
            if target_id and record.object_id != target_id:
                continue
            results.append(record)
            if len(results) >= limit:
                break
        return results

    def find_by_id(self, id: str, correlation_id: str) -> AuditEventRecord:
        """
        Return a single audit event by ULID.

        Args:
            id:             Audit event ULID.
            correlation_id: Ignored in mock.

        Returns:
            AuditEventRecord matching the given ID.

        Raises:
            NotFoundError: If no audit event exists with the given ID.
        """
        if id not in self._store:
            raise NotFoundError(f"AuditEventRecord id={id!r} not found")
        return self._store[id]

    # ------------------------------------------------------------------
    # Test introspection helpers
    # ------------------------------------------------------------------

    def save(self, record: AuditEventRecord) -> None:
        """
        Persist an AuditEventRecord to the in-memory store.

        Args:
            record: AuditEventRecord to store; keyed by record.id.
        """
        self._store[record.id] = record

    def clear(self) -> None:
        """Remove all stored audit event records."""
        self._store.clear()

    def count(self) -> int:
        """Return the number of stored audit event records."""
        return len(self._store)
