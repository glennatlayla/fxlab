"""
Strategy service interface.

Responsibilities:
- Define the abstract contract for strategy management use cases.
- Support creating, retrieving, listing strategies.
- Support DSL condition validation.

Does NOT:
- Implement business logic (concrete service responsibility).
- Access persistence directly (delegates to repository).

Dependencies:
- None (pure interface).

Example:
    service: StrategyServiceInterface = StrategyService(strategy_repo=repo)
    result = service.create_strategy(
        name="RSI Reversal",
        code="RSI(14) < 30 AND price > SMA(200)",
        created_by="01HUSER001",
    )
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class StrategyServiceInterface(ABC):
    """
    Abstract interface for strategy management.

    Implementations:
    - StrategyService: Production implementation with full validation.
    """

    @abstractmethod
    def create_strategy(
        self,
        *,
        name: str,
        entry_condition: str,
        exit_condition: str,
        description: str | None = None,
        instrument: str | None = None,
        timeframe: str | None = None,
        max_position_size: float | None = None,
        stop_loss_percent: float | None = None,
        take_profit_percent: float | None = None,
        parameters: dict[str, Any] | None = None,
        created_by: str,
    ) -> dict[str, Any]:
        """
        Create a new strategy with validated DSL conditions.

        Args:
            name: Strategy name.
            entry_condition: DSL entry condition expression.
            exit_condition: DSL exit condition expression.
            description: Optional description.
            instrument: Target instrument (e.g. "AAPL", "ES").
            timeframe: Candle timeframe (e.g. "1h", "1d").
            max_position_size: Max position in dollars.
            stop_loss_percent: Stop loss percentage.
            take_profit_percent: Take profit percentage.
            parameters: Optional strategy-specific parameters.
            created_by: ULID of the creating user.

        Returns:
            Dict with strategy record and validation details.

        Raises:
            ValidationError: If DSL conditions are syntactically invalid.
        """

    @abstractmethod
    def get_strategy(self, strategy_id: str) -> dict[str, Any]:
        """
        Retrieve a strategy by ID.

        Args:
            strategy_id: ULID of the strategy.

        Returns:
            Strategy dict.

        Raises:
            NotFoundError: If strategy does not exist.
        """

    @abstractmethod
    def list_strategies(
        self,
        *,
        created_by: str | None = None,
        is_active: bool | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> dict[str, Any]:
        """
        List strategies with pagination.

        Args:
            created_by: Filter by creator.
            is_active: Filter by active flag.
            limit: Page size.
            offset: Page offset.

        Returns:
            Dict with strategies list and total count.
        """

    @abstractmethod
    def validate_dsl_expression(self, expression: str) -> dict[str, Any]:
        """
        Validate a DSL condition expression without creating a strategy.

        Args:
            expression: Raw DSL string.

        Returns:
            Dict with is_valid, errors, indicators_used, variables_used.
        """
