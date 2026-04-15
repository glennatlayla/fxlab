"""
In-memory mock position repository for unit testing.

Responsibilities:
- Implement PositionRepositoryInterface with dict-backed storage.
- Maintain a composite key index (deployment_id, symbol) for efficient lookups.
- Provide seed() and introspection helpers for test setup and assertions.
- Match the behavioural contract of the production SQL repository.
- Mock pessimistic locking (get_for_update) as a no-op (returns position or None).

Does NOT:
- Persist data across process restarts.
- Implement actual row-level database locking (test-only mock).
- Contain business logic or P&L calculations.
- Enforce position size limits.

Dependencies:
- libs.contracts.interfaces.position_repository_interface.PositionRepositoryInterface
- libs.contracts.errors.NotFoundError

Error conditions:
- NotFoundError: position_id does not exist in update_position.

Example:
    repo = MockPositionRepository()
    record = repo.save(
        deployment_id="01HDEPLOY...",
        symbol="AAPL",
        quantity="100",
        average_entry_price="150.00",
    )
    assert repo.get_by_deployment_and_symbol(
        deployment_id="01HDEPLOY...",
        symbol="AAPL",
    ) == record
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from libs.contracts.errors import NotFoundError
from libs.contracts.interfaces.position_repository_interface import (
    PositionRepositoryInterface,
)


def _generate_test_ulid() -> str:
    """
    Generate a ULID for test use.

    Uses python-ulid which produces spec-compliant 26-character Crockford
    base32 ULIDs.

    Returns:
        26-character ULID string.
    """
    import ulid as _ulid

    return str(_ulid.ULID())


class MockPositionRepository(PositionRepositoryInterface):
    """
    In-memory implementation of PositionRepositoryInterface for unit tests.

    Responsibilities:
    - Store position records in a dict keyed by position ID.
    - Maintain a composite key index for (deployment_id, symbol) lookups.
    - Provide seed() for prepopulating test data.
    - Provide introspection helpers for assertions.
    - Mock pessimistic locking without actual database locking.

    Does NOT:
    - Enforce position constraints or limits (service responsibility).
    - Persist across test runs.
    - Implement true row-level locking (mocked as immediate return).

    Example:
        repo = MockPositionRepository()
        record = repo.save(
            deployment_id="01HDEPLOY...",
            symbol="AAPL",
            quantity="100",
            average_entry_price="150.00",
        )
        assert repo.count() == 1
        found = repo.get_by_deployment_and_symbol(
            deployment_id="01HDEPLOY...",
            symbol="AAPL",
        )
        assert found == record
    """

    def __init__(self) -> None:
        self._store: dict[str, dict[str, Any]] = {}
        # Maps (deployment_id, symbol) tuple to position_id
        self._deployment_symbol_index: dict[tuple[str, str], str] = {}

    # ------------------------------------------------------------------
    # Interface methods
    # ------------------------------------------------------------------

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
        position_id = _generate_test_ulid()
        now = datetime.now(tz=timezone.utc).isoformat()
        record: dict[str, Any] = {
            "id": position_id,
            "deployment_id": deployment_id,
            "symbol": symbol,
            "quantity": quantity,
            "average_entry_price": average_entry_price,
            "market_price": market_price,
            "market_value": market_value,
            "unrealized_pnl": unrealized_pnl,
            "realized_pnl": realized_pnl,
            "cost_basis": cost_basis,
            "created_at": now,
            "updated_at": now,
        }
        self._store[position_id] = record
        self._deployment_symbol_index[(deployment_id, symbol)] = position_id
        return dict(record)

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
        position_id = self._deployment_symbol_index.get((deployment_id, symbol))
        if position_id is None:
            return None
        return dict(self._store[position_id])

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
        result = [dict(r) for r in self._store.values() if r["deployment_id"] == deployment_id]
        return result

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
        record = self._store.get(position_id)
        if record is None:
            raise NotFoundError(f"Position {position_id} not found")

        if quantity is not None:
            record["quantity"] = quantity
        if average_entry_price is not None:
            record["average_entry_price"] = average_entry_price
        if market_price is not None:
            record["market_price"] = market_price
        if market_value is not None:
            record["market_value"] = market_value
        if unrealized_pnl is not None:
            record["unrealized_pnl"] = unrealized_pnl
        if realized_pnl is not None:
            record["realized_pnl"] = realized_pnl
        if cost_basis is not None:
            record["cost_basis"] = cost_basis

        record["updated_at"] = datetime.now(tz=timezone.utc).isoformat()
        return dict(record)

    def get_for_update(
        self,
        *,
        deployment_id: str,
        symbol: str,
    ) -> dict[str, Any] | None:
        """
        Acquire a pessimistic row-level lock on a position for safe update.

        In the mock, this is equivalent to get_by_deployment_and_symbol()
        since there is no actual database locking. In production, this uses
        SELECT ... FOR UPDATE NOWAIT.

        Args:
            deployment_id: Deployment ULID.
            symbol: Instrument ticker.

        Returns:
            Dict with all position fields (locked row), or None if no
            position exists for this deployment + symbol.
        """
        # Mock: just return the position without actual locking
        return self.get_by_deployment_and_symbol(deployment_id=deployment_id, symbol=symbol)

    # ------------------------------------------------------------------
    # Test helpers / introspection
    # ------------------------------------------------------------------

    def seed(
        self,
        *,
        position_id: str | None = None,
        deployment_id: str = "01HDEPLOYTEST0000000000001",
        symbol: str = "AAPL",
        quantity: str = "100",
        average_entry_price: str = "150.00",
        market_price: str = "155.00",
        market_value: str = "15500.00",
        unrealized_pnl: str = "500.00",
        realized_pnl: str = "0",
        cost_basis: str = "15000.00",
    ) -> dict[str, Any]:
        """
        Prepopulate a position record for test setup.

        Unlike save(), this allows setting an arbitrary initial state
        and position_id for test determinism.

        Args:
            position_id: Fixed ULID (auto-generated if None).
            deployment_id: Deployment ULID.
            symbol: Instrument ticker.
            quantity: Position quantity.
            average_entry_price: Average entry price.
            market_price: Current market price.
            market_value: Current market value.
            unrealized_pnl: Unrealized P&L.
            realized_pnl: Realized P&L.
            cost_basis: Cost basis.

        Returns:
            Seeded position dict.

        Example:
            record = repo.seed(
                symbol="GOOGL",
                quantity="-50",
                deployment_id="01HDEPLOY...",
            )
        """
        if position_id is None:
            position_id = _generate_test_ulid()
        now = datetime.now(tz=timezone.utc).isoformat()
        record: dict[str, Any] = {
            "id": position_id,
            "deployment_id": deployment_id,
            "symbol": symbol,
            "quantity": quantity,
            "average_entry_price": average_entry_price,
            "market_price": market_price,
            "market_value": market_value,
            "unrealized_pnl": unrealized_pnl,
            "realized_pnl": realized_pnl,
            "cost_basis": cost_basis,
            "created_at": now,
            "updated_at": now,
        }
        self._store[position_id] = record
        self._deployment_symbol_index[(deployment_id, symbol)] = position_id
        return dict(record)

    def count(self) -> int:
        """Return the number of stored positions."""
        return len(self._store)

    def get_all(self) -> list[dict[str, Any]]:
        """Return all stored positions."""
        return [dict(r) for r in self._store.values()]

    def clear(self) -> None:
        """Remove all stored data."""
        self._store.clear()
        self._deployment_symbol_index.clear()
