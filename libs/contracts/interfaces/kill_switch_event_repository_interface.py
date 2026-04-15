"""
Kill switch event repository interface (port).

Responsibilities:
- Define the abstract contract for kill switch event persistence and retrieval.
- Support querying active (non-deactivated) kill switch events.
- Support deactivation of events (the only allowed mutation).

Does NOT:
- Implement storage logic.
- Enforce kill switch activation/deactivation logic.
- Manage order cancellation or emergency posture execution.

Dependencies:
- None (pure interface).

Error conditions:
- NotFoundError: raised by deactivate when event does not exist.

Example:
    repo: KillSwitchEventRepositoryInterface = SqlKillSwitchEventRepository(db=session)
    event = repo.save(
        scope="strategy",
        target_id="01HSTRAT...",
        activated_by="user:01HUSER...",
        activated_at="2026-04-11T14:30:00+00:00",
        reason="Daily loss limit breached",
    )
    active = repo.list_active()
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class KillSwitchEventRepositoryInterface(ABC):
    """
    Port interface for kill switch event persistence.

    Responsibilities:
    - Persist kill switch activation events.
    - Support deactivation (setting deactivated_at timestamp).
    - Query active events by scope and target.

    Does NOT:
    - Enforce kill switch business rules (service layer responsibility).
    - Cancel orders or execute emergency postures.
    """

    @abstractmethod
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
        Persist a new kill switch activation event.

        Generates a ULID primary key.

        Args:
            scope: Kill switch scope ("global", "strategy", "symbol").
            target_id: Target identifier (strategy_id, symbol, or "global").
            activated_by: Identifier of the user or system that activated
                the kill switch.
            activated_at: ISO 8601 timestamp of activation.
            reason: Human-readable reason for activation.
            mtth_ms: Measured mean time to halt in milliseconds (optional,
                typically set after activation completes).

        Returns:
            Dict with all event fields including generated id and timestamps.
        """
        ...

    @abstractmethod
    def get_active(self, *, scope: str, target_id: str) -> dict[str, Any] | None:
        """
        Get the currently active kill switch for a scope + target.

        An event is "active" if deactivated_at is NULL.

        Args:
            scope: Kill switch scope.
            target_id: Target identifier.

        Returns:
            Dict with event fields, or None if no active event exists
            for this scope + target.
        """
        ...

    @abstractmethod
    def list_active(self) -> list[dict[str, Any]]:
        """
        List all currently active kill switch events.

        Returns:
            List of event dicts where deactivated_at is NULL,
            ordered by activated_at descending.
        """
        ...

    @abstractmethod
    def deactivate(
        self, *, event_id: str, deactivated_at: str, mtth_ms: int | None = None
    ) -> dict[str, Any]:
        """
        Deactivate a kill switch event by setting its deactivated_at timestamp.

        Args:
            event_id: ULID of the event to deactivate.
            deactivated_at: ISO 8601 timestamp of deactivation.
            mtth_ms: Measured mean time to halt in milliseconds (optional).

        Returns:
            Updated event dict.

        Raises:
            NotFoundError: If no event exists with this ID.
        """
        ...

    @abstractmethod
    def list_by_scope(self, *, scope: str, limit: int = 100) -> list[dict[str, Any]]:
        """
        List kill switch events by scope, including both active and deactivated.

        Args:
            scope: Kill switch scope ("global", "strategy", "symbol").
            limit: Maximum number of events to return.

        Returns:
            List of event dicts ordered by activated_at descending.
        """
        ...
