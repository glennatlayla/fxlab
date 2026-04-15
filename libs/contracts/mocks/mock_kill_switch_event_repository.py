"""
In-memory mock implementation of KillSwitchEventRepositoryInterface.

Responsibilities:
- Provide a test double for kill switch event persistence.
- Support introspection helpers for test assertions.

Does NOT:
- Persist data beyond the lifetime of the instance.
- Enforce kill switch business rules.

Dependencies:
- libs.contracts.interfaces.kill_switch_event_repository_interface.
- libs.contracts.errors: NotFoundError.

Example:
    repo = MockKillSwitchEventRepository()
    event = repo.save(scope="global", target_id="global", ...)
    assert repo.count() == 1
"""

from __future__ import annotations

from typing import Any

from libs.contracts.errors import NotFoundError
from libs.contracts.interfaces.kill_switch_event_repository_interface import (
    KillSwitchEventRepositoryInterface,
)


class MockKillSwitchEventRepository(KillSwitchEventRepositoryInterface):
    """
    In-memory implementation of KillSwitchEventRepositoryInterface.

    Responsibilities:
    - Store kill switch events in memory for testing.
    - Support get_active, list_active, deactivate, and list_by_scope.
    - Provide introspection helpers (count, get_all, clear).

    Does NOT:
    - Persist data to any external store.

    Raises:
    - NotFoundError: when deactivating a non-existent event.

    Example:
        repo = MockKillSwitchEventRepository()
        event = repo.save(scope="global", target_id="global",
                         activated_by="system",
                         activated_at="2026-04-11T10:00:00+00:00",
                         reason="Manual halt")
        active = repo.list_active()
    """

    def __init__(self) -> None:
        self._store: dict[str, dict[str, Any]] = {}
        self._counter: int = 0

    def save(
        self,
        *,
        scope: str,
        target_id: str,
        activated_by: str,
        activated_at: str,
        reason: str,
        mtth_ms: int | None = None,
    ) -> dict[str, Any]:
        """
        Persist a new kill switch activation event in memory.

        Args:
            scope: Kill switch scope.
            target_id: Target identifier.
            activated_by: Activating user or system.
            activated_at: ISO 8601 timestamp.
            reason: Activation reason.
            mtth_ms: Mean time to halt (optional).

        Returns:
            Dict with all event fields.
        """
        self._counter += 1
        event_id = f"mock-ks-{self._counter:06d}"
        event = {
            "id": event_id,
            "scope": scope,
            "target_id": target_id,
            "activated_by": activated_by,
            "activated_at": activated_at,
            "deactivated_at": None,
            "reason": reason,
            "mtth_ms": mtth_ms,
            "created_at": activated_at,
            "updated_at": activated_at,
        }
        self._store[event_id] = event
        return dict(event)

    def get_active(self, *, scope: str, target_id: str) -> dict[str, Any] | None:
        """
        Get the currently active kill switch for a scope + target.

        Args:
            scope: Kill switch scope.
            target_id: Target identifier.

        Returns:
            Dict or None.
        """
        for event in self._store.values():
            if (
                event["scope"] == scope
                and event["target_id"] == target_id
                and event["deactivated_at"] is None
            ):
                return dict(event)
        return None

    def list_active(self) -> list[dict[str, Any]]:
        """
        List all currently active kill switch events.

        Returns:
            List of event dicts where deactivated_at is None.
        """
        active = [dict(e) for e in self._store.values() if e["deactivated_at"] is None]
        active.sort(key=lambda e: e["activated_at"], reverse=True)
        return active

    def deactivate(
        self,
        *,
        event_id: str,
        deactivated_at: str,
        mtth_ms: int | None = None,
    ) -> dict[str, Any]:
        """
        Deactivate a kill switch event.

        Args:
            event_id: Event ID.
            deactivated_at: ISO 8601 timestamp.
            mtth_ms: Mean time to halt (optional).

        Returns:
            Updated event dict.

        Raises:
            NotFoundError: If event does not exist.
        """
        if event_id not in self._store:
            raise NotFoundError(f"KillSwitchEvent with id={event_id!r} not found")

        self._store[event_id]["deactivated_at"] = deactivated_at
        if mtth_ms is not None:
            self._store[event_id]["mtth_ms"] = mtth_ms

        return dict(self._store[event_id])

    def list_by_scope(self, *, scope: str, limit: int = 100) -> list[dict[str, Any]]:
        """
        List events by scope.

        Args:
            scope: Kill switch scope.
            limit: Maximum results.

        Returns:
            List of event dicts.
        """
        filtered = [dict(e) for e in self._store.values() if e["scope"] == scope]
        filtered.sort(key=lambda e: e["activated_at"], reverse=True)
        return filtered[:limit]

    # ------------------------------------------------------------------
    # Introspection helpers for tests
    # ------------------------------------------------------------------

    def count(self) -> int:
        """Return total number of stored events."""
        return len(self._store)

    def get_all(self) -> list[dict[str, Any]]:
        """Return all stored events."""
        return [dict(e) for e in self._store.values()]

    def clear(self) -> None:
        """Remove all stored events and reset counter."""
        self._store.clear()
        self._counter = 0
