"""
Position repository interface (port).

Responsibilities:
- Define the abstract contract for position persistence and retrieval.
- Support pessimistic locking for concurrent order placement safety.
- Support upsert semantics (save-or-update by deployment + symbol).

Does NOT:
- Implement storage logic.
- Calculate position P&L (service layer responsibility).
- Enforce risk limits (risk gate service responsibility).

Dependencies:
- None (pure interface).

Error conditions:
- NotFoundError: raised by update_position when position does not exist.

Example:
    repo: PositionRepositoryInterface = SqlPositionRepository(db=session)
    position = repo.save(
        deployment_id="01HDEPLOY...",
        symbol="AAPL",
        quantity="100",
        average_entry_price="150.00",
    )
    locked = repo.get_for_update(deployment_id="01HDEPLOY...", symbol="AAPL")
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class PositionRepositoryInterface(ABC):
    """
    Port interface for position persistence.

    Responsibilities:
    - CRUD operations for position records.
    - Pessimistic locking for safe concurrent updates (get_for_update).
    - Lookup by deployment + symbol composite key.

    Does NOT:
    - Calculate unrealized P&L or market value (caller provides these).
    - Enforce position size limits.
    """

    @abstractmethod
    def save(
        self,
        *,
        deployment_id: str,
        symbol: str,
        quantity: str,
        average_entry_price: str,
        market_price: str = "0",
        market_value: str = "0",
        unrealized_pnl: str = "0",
        realized_pnl: str = "0",
        cost_basis: str = "0",
    ) -> dict[str, Any]:
        """
        Persist a new position record.

        Generates a ULID primary key. All monetary values stored as strings
        for decimal precision safety.

        Args:
            deployment_id: Owning deployment ULID.
            symbol: Instrument ticker (e.g. "AAPL").
            quantity: Current position quantity as string (negative = short).
            average_entry_price: Volume-weighted average entry price.
            market_price: Last known market price.
            market_value: Current market value (quantity * market_price).
            unrealized_pnl: Unrealized profit/loss.
            realized_pnl: Realized profit/loss from closed portions.
            cost_basis: Total cost basis of the position.

        Returns:
            Dict with all position fields including generated id and timestamps.
        """
        ...

    @abstractmethod
    def get_by_deployment_and_symbol(
        self,
        *,
        deployment_id: str,
        symbol: str,
    ) -> dict[str, Any] | None:
        """
        Look up a position by deployment and symbol.

        Args:
            deployment_id: Deployment ULID.
            symbol: Instrument ticker.

        Returns:
            Dict with all position fields, or None if no position exists.
        """
        ...

    @abstractmethod
    def list_by_deployment(
        self,
        *,
        deployment_id: str,
    ) -> list[dict[str, Any]]:
        """
        List all positions for a deployment.

        Args:
            deployment_id: Deployment ULID.

        Returns:
            List of position dicts.
        """
        ...

    @abstractmethod
    def update_position(
        self,
        *,
        position_id: str,
        quantity: str | None = None,
        average_entry_price: str | None = None,
        market_price: str | None = None,
        market_value: str | None = None,
        unrealized_pnl: str | None = None,
        realized_pnl: str | None = None,
        cost_basis: str | None = None,
    ) -> dict[str, Any]:
        """
        Update specific fields on an existing position.

        Only non-None fields are updated. The updated_at timestamp is
        automatically refreshed.

        Args:
            position_id: ULID of the position to update.
            quantity: New quantity (if changed).
            average_entry_price: New average entry price (if changed).
            market_price: New market price (if changed).
            market_value: New market value (if changed).
            unrealized_pnl: New unrealized P&L (if changed).
            realized_pnl: New realized P&L (if changed).
            cost_basis: New cost basis (if changed).

        Returns:
            Updated position dict.

        Raises:
            NotFoundError: If no position exists with this ID.
        """
        ...

    @abstractmethod
    def get_for_update(
        self,
        *,
        deployment_id: str,
        symbol: str,
    ) -> dict[str, Any] | None:
        """
        Acquire a pessimistic row-level lock on a position for safe update.

        Uses SELECT ... FOR UPDATE NOWAIT to immediately fail if the row
        is already locked by another transaction, preventing deadlocks.

        Must be called within an active database transaction. The lock is
        released when the transaction commits or rolls back.

        Args:
            deployment_id: Deployment ULID.
            symbol: Instrument ticker.

        Returns:
            Dict with all position fields (locked row), or None if no
            position exists for this deployment + symbol.

        Raises:
            ExternalServiceError: If the row is already locked by another
                transaction (NOWAIT semantics).
        """
        ...
