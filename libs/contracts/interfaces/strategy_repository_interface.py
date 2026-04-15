"""
Strategy repository interface (port).

Responsibilities:
- Define the abstract contract for strategy CRUD persistence.
- Support creating, retrieving, listing, and deactivating strategies.
- Return dict representations for layer decoupling.

Does NOT:
- Implement storage logic (adapter responsibility).
- Validate DSL syntax (service layer responsibility).
- Contain business logic.

Dependencies:
- None (pure interface).

Error conditions:
- NotFoundError: raised when a specific strategy is not found.

Example:
    repo: StrategyRepositoryInterface = SqlStrategyRepository(db=session)
    strategy = repo.create(
        name="Momentum Crossover",
        code="RSI(14) < 30 AND price > SMA(200)",
        created_by="01HUSER001",
    )
    found = repo.get_by_id("01HSTRAT001")
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class StrategyRepositoryInterface(ABC):
    """
    Abstract interface for strategy persistence.

    All monetary values and identifiers are strings to maintain
    decimal precision safety and layer decoupling.

    Implementations:
    - SqlStrategyRepository: Production SQL-backed persistence.
    - MockStrategyRepository: In-memory fake for unit testing.
    """

    @abstractmethod
    def create(
        self,
        *,
        name: str,
        code: str,
        created_by: str,
        version: str | None = None,
    ) -> dict[str, Any]:
        """
        Create a new strategy record.

        Args:
            name: Human-readable strategy name.
            code: Strategy DSL source code (entry/exit conditions).
            created_by: ULID of the creating user.
            version: Optional semantic version string.

        Returns:
            Dict with id, name, code, version, created_by, is_active,
            created_at, updated_at.
        """

    @abstractmethod
    def get_by_id(self, strategy_id: str) -> dict[str, Any] | None:
        """
        Retrieve a strategy by its ULID.

        Args:
            strategy_id: ULID of the strategy.

        Returns:
            Dict representation of the strategy, or None if not found.
        """

    @abstractmethod
    def list_strategies(
        self,
        *,
        created_by: str | None = None,
        is_active: bool | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        """
        List strategies with optional filtering and pagination.

        Args:
            created_by: Filter by creator ULID.
            is_active: Filter by active status.
            limit: Maximum results to return.
            offset: Number of results to skip.

        Returns:
            List of strategy dicts ordered by created_at descending.
        """

    @abstractmethod
    def update(
        self,
        strategy_id: str,
        *,
        name: str | None = None,
        code: str | None = None,
        version: str | None = None,
        is_active: bool | None = None,
    ) -> dict[str, Any] | None:
        """
        Update fields on an existing strategy.

        Uses optimistic locking via row_version. Only non-None fields
        are updated.

        Args:
            strategy_id: ULID of the strategy to update.
            name: New name (optional).
            code: New DSL code (optional).
            version: New version string (optional).
            is_active: New active status (optional).

        Returns:
            Updated strategy dict, or None if not found.
        """

    @abstractmethod
    def deactivate(self, strategy_id: str) -> bool:
        """
        Soft-delete a strategy by setting is_active=False.

        Args:
            strategy_id: ULID of the strategy to deactivate.

        Returns:
            True if found and deactivated, False if not found.
        """
