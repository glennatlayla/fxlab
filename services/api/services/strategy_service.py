"""
Strategy management service.

Responsibilities:
- Orchestrate strategy creation with DSL validation.
- Persist strategies via the repository interface.
- Format strategy data including parsed DSL metadata.
- Provide live DSL validation for frontend editors.

Does NOT:
- Access the database directly (delegates to StrategyRepositoryInterface).
- Execute or backtest strategies (runtime engine responsibility).
- Handle HTTP or message formatting (controller responsibility).

Dependencies:
- StrategyRepositoryInterface (injected): Strategy persistence.
- dsl_validator: DSL tokenizer/parser for condition validation.

Error conditions:
- ValidationError: DSL condition syntax is invalid.
- NotFoundError: Requested strategy does not exist.

Example:
    service = StrategyService(strategy_repo=repo)
    result = service.create_strategy(
        name="RSI Reversal",
        entry_condition="RSI(14) < 30 AND price > SMA(200)",
        exit_condition="RSI(14) > 70 OR price < SMA(200)",
        created_by="01HUSER001",
    )
"""

from __future__ import annotations

import json
from typing import Any

import structlog

from libs.contracts.errors import NotFoundError, ValidationError
from libs.contracts.interfaces.strategy_repository_interface import (
    StrategyRepositoryInterface,
)
from services.api.services.dsl_validator import (
    DslValidationResult,
    validate_dsl,
)
from services.api.services.interfaces.strategy_service_interface import (
    StrategyServiceInterface,
)

logger = structlog.get_logger(__name__)


def _build_strategy_code(
    entry_condition: str,
    exit_condition: str,
    description: str | None = None,
    instrument: str | None = None,
    timeframe: str | None = None,
    max_position_size: float | None = None,
    stop_loss_percent: float | None = None,
    take_profit_percent: float | None = None,
    parameters: dict[str, Any] | None = None,
) -> str:
    """
    Assemble a strategy code JSON document from individual fields.

    The strategy code is stored as a structured JSON string in the
    database. This format preserves all form fields and allows the
    strategy compiler to extract individual components.

    Args:
        entry_condition: DSL entry condition expression.
        exit_condition: DSL exit condition expression.
        description: Optional strategy description.
        instrument: Target instrument symbol.
        timeframe: Candle timeframe.
        max_position_size: Max position in dollars.
        stop_loss_percent: Stop loss percentage.
        take_profit_percent: Take profit percentage.
        parameters: Strategy-specific parameter overrides.

    Returns:
        JSON string encoding all strategy fields.
    """
    code_doc: dict[str, Any] = {
        "entry_condition": entry_condition,
        "exit_condition": exit_condition,
    }
    if description:
        code_doc["description"] = description
    if instrument:
        code_doc["instrument"] = instrument
    if timeframe:
        code_doc["timeframe"] = timeframe
    if max_position_size is not None:
        code_doc["max_position_size"] = max_position_size
    if stop_loss_percent is not None:
        code_doc["stop_loss_percent"] = stop_loss_percent
    if take_profit_percent is not None:
        code_doc["take_profit_percent"] = take_profit_percent
    if parameters:
        code_doc["parameters"] = parameters

    return json.dumps(code_doc, sort_keys=True)


def _format_validation_result(result: DslValidationResult) -> dict[str, Any]:
    """
    Convert a DslValidationResult to a serialisable dict.

    Args:
        result: Parsed validation result from the DSL validator.

    Returns:
        Dict with is_valid, errors (list of dicts), indicators_used, variables_used.
    """
    return {
        "is_valid": result.is_valid,
        "errors": [
            {
                "message": e.message,
                "line": e.line,
                "column": e.column,
                "suggestion": e.suggestion,
            }
            for e in result.errors
        ],
        "indicators_used": sorted(result.indicators_used),
        "variables_used": sorted(result.variables_used),
    }


class StrategyService(StrategyServiceInterface):
    """
    Production strategy management service.

    Responsibilities:
    - Validate entry and exit DSL conditions before persisting.
    - Assemble strategy code documents and persist via repository.
    - Retrieve and list strategies with optional filtering.
    - Provide standalone DSL validation for live editor feedback.

    Does NOT:
    - Execute strategies or run backtests.
    - Handle HTTP routing or response formatting.

    Dependencies:
    - StrategyRepositoryInterface (injected).

    Example:
        service = StrategyService(strategy_repo=repo)
        result = service.create_strategy(
            name="RSI Reversal",
            entry_condition="RSI(14) < 30",
            exit_condition="RSI(14) > 70",
            created_by="01HUSER001",
        )
    """

    def __init__(self, *, strategy_repo: StrategyRepositoryInterface) -> None:
        self._strategy_repo = strategy_repo

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

        Validates both entry and exit conditions using the DSL parser.
        If either condition is invalid, raises ValidationError with
        detailed error positions and suggestions.

        Args:
            name: Strategy name (1-255 chars).
            entry_condition: DSL entry condition expression.
            exit_condition: DSL exit condition expression.
            description: Optional human-readable description.
            instrument: Target instrument (e.g. "AAPL").
            timeframe: Candle timeframe (e.g. "1h", "1d").
            max_position_size: Maximum position size in dollars.
            stop_loss_percent: Stop loss as percentage.
            take_profit_percent: Take profit as percentage.
            parameters: Optional custom parameter dict.
            created_by: ULID of the creating user.

        Returns:
            Dict with: strategy (persisted record), entry_validation,
            exit_validation, indicators_used, variables_used.

        Raises:
            ValidationError: If name is empty or DSL conditions are invalid.
        """
        logger.info(
            "strategy.create.started",
            name=name,
            created_by=created_by,
            component="StrategyService",
            operation="create_strategy",
        )

        # Validate name
        if not name or not name.strip():
            raise ValidationError("Strategy name is required")

        # Validate DSL conditions
        entry_result = validate_dsl(entry_condition)
        exit_result = validate_dsl(exit_condition)

        errors: list[str] = []
        if not entry_result.is_valid:
            for e in entry_result.errors:
                errors.append(f"Entry condition: {e.message} (line {e.line}, col {e.column})")
        if not exit_result.is_valid:
            for e in exit_result.errors:
                errors.append(f"Exit condition: {e.message} (line {e.line}, col {e.column})")

        if errors:
            raise ValidationError("; ".join(errors))

        # Assemble strategy code document
        code = _build_strategy_code(
            entry_condition=entry_condition,
            exit_condition=exit_condition,
            description=description,
            instrument=instrument,
            timeframe=timeframe,
            max_position_size=max_position_size,
            stop_loss_percent=stop_loss_percent,
            take_profit_percent=take_profit_percent,
            parameters=parameters,
        )

        # Persist to database
        strategy = self._strategy_repo.create(
            name=name.strip(),
            code=code,
            created_by=created_by,
        )

        # Collect all indicators and variables across both conditions
        all_indicators = entry_result.indicators_used | exit_result.indicators_used
        all_variables = entry_result.variables_used | exit_result.variables_used

        logger.info(
            "strategy.create.completed",
            strategy_id=strategy["id"],
            name=name,
            indicators=sorted(all_indicators),
            component="StrategyService",
            operation="create_strategy",
        )

        return {
            "strategy": strategy,
            "entry_validation": _format_validation_result(entry_result),
            "exit_validation": _format_validation_result(exit_result),
            "indicators_used": sorted(all_indicators),
            "variables_used": sorted(all_variables),
        }

    def get_strategy(self, strategy_id: str) -> dict[str, Any]:
        """
        Retrieve a strategy by ID.

        Parses the stored code JSON to extract individual fields.

        Args:
            strategy_id: ULID of the strategy.

        Returns:
            Strategy dict with parsed code fields.

        Raises:
            NotFoundError: If strategy does not exist.
        """
        strategy = self._strategy_repo.get_by_id(strategy_id)
        if strategy is None:
            raise NotFoundError(f"Strategy {strategy_id} not found")

        # Parse the code JSON to expose individual fields
        try:
            code_doc = json.loads(strategy["code"])
        except (json.JSONDecodeError, TypeError):
            code_doc = {"raw": strategy["code"]}

        return {
            **strategy,
            "parsed_code": code_doc,
        }

    def list_strategies(
        self,
        *,
        created_by: str | None = None,
        is_active: bool | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> dict[str, Any]:
        """
        List strategies with optional filtering and pagination.

        Args:
            created_by: Filter by creator ULID.
            is_active: Filter by active flag.
            limit: Page size.
            offset: Page offset.

        Returns:
            Dict with strategies list and pagination metadata.
        """
        strategies = self._strategy_repo.list_strategies(
            created_by=created_by,
            is_active=is_active,
            limit=limit,
            offset=offset,
        )

        logger.debug(
            "strategy.list.completed",
            count=len(strategies),
            component="StrategyService",
            operation="list_strategies",
        )

        return {
            "strategies": strategies,
            "limit": limit,
            "offset": offset,
            "count": len(strategies),
        }

    def validate_dsl_expression(self, expression: str) -> dict[str, Any]:
        """
        Validate a DSL expression without creating a strategy.

        Used by the frontend DslEditor for live validation as the
        user types.

        Args:
            expression: Raw DSL condition string.

        Returns:
            Dict with is_valid, errors, indicators_used, variables_used.

        Example:
            result = service.validate_dsl_expression("RSI(14) < 30")
            assert result["is_valid"] is True
        """
        result = validate_dsl(expression)
        return _format_validation_result(result)
