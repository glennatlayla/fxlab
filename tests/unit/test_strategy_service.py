"""
Tests for the StrategyService.

Verifies:
- Strategy creation with valid DSL conditions.
- DSL validation errors prevent strategy creation.
- Strategy retrieval by ID.
- Strategy listing with filters and pagination.
- DSL expression validation (standalone).
- Name validation.

Example:
    pytest tests/unit/test_strategy_service.py -v
"""

from __future__ import annotations

import json

import pytest

from libs.contracts.errors import NotFoundError, ValidationError
from libs.contracts.mocks.mock_strategy_repository import MockStrategyRepository
from services.api.services.strategy_service import StrategyService

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _make_service() -> tuple[StrategyService, MockStrategyRepository]:
    """Create a StrategyService with a fresh mock repository."""
    repo = MockStrategyRepository()
    service = StrategyService(strategy_repo=repo)
    return service, repo


# ---------------------------------------------------------------------------
# Create strategy
# ---------------------------------------------------------------------------


class TestCreateStrategy:
    """Tests for strategy creation."""

    def test_create_valid_strategy(self) -> None:
        """Valid conditions should persist and return validation metadata."""
        service, repo = _make_service()

        result = service.create_strategy(
            name="RSI Reversal",
            entry_condition="RSI(14) < 30 AND price > SMA(200)",
            exit_condition="RSI(14) > 70 OR price < SMA(200)",
            description="Mean reversion strategy",
            instrument="AAPL",
            timeframe="1h",
            max_position_size=10000,
            stop_loss_percent=2.0,
            take_profit_percent=5.0,
            created_by="01HUSER001",
        )

        assert "strategy" in result
        assert result["strategy"]["name"] == "RSI Reversal"
        assert result["strategy"]["is_active"] is True
        assert result["entry_validation"]["is_valid"] is True
        assert result["exit_validation"]["is_valid"] is True
        assert "RSI" in result["indicators_used"]
        assert "SMA" in result["indicators_used"]
        assert "price" in result["variables_used"]

        # Verify persisted in repo
        assert repo.count() == 1
        stored = repo.get_all()[0]
        code_doc = json.loads(stored["code"])
        assert code_doc["entry_condition"] == "RSI(14) < 30 AND price > SMA(200)"
        assert code_doc["instrument"] == "AAPL"

    def test_create_with_invalid_entry_condition(self) -> None:
        """Invalid entry condition should raise ValidationError."""
        service, repo = _make_service()

        with pytest.raises(ValidationError, match="Entry condition"):
            service.create_strategy(
                name="Bad Strategy",
                entry_condition="RSI() < 30",  # Missing argument
                exit_condition="RSI(14) > 70",
                created_by="01HUSER001",
            )

        # Nothing should be persisted
        assert repo.count() == 0

    def test_create_with_invalid_exit_condition(self) -> None:
        """Invalid exit condition should raise ValidationError."""
        service, repo = _make_service()

        with pytest.raises(ValidationError, match="Exit condition"):
            service.create_strategy(
                name="Bad Strategy",
                entry_condition="RSI(14) < 30",
                exit_condition="FOOBAR(14) > 70",  # Unknown indicator
                created_by="01HUSER001",
            )

        assert repo.count() == 0

    def test_create_with_both_conditions_invalid(self) -> None:
        """Both conditions invalid should report errors for both."""
        service, _ = _make_service()

        with pytest.raises(ValidationError, match="Entry condition.*Exit condition"):
            service.create_strategy(
                name="Bad Strategy",
                entry_condition="RSI() < 30",
                exit_condition="MACD(12) > 0",
                created_by="01HUSER001",
            )

    def test_create_with_empty_name_raises(self) -> None:
        """Empty name should raise ValidationError."""
        service, _ = _make_service()

        with pytest.raises(ValidationError, match="name is required"):
            service.create_strategy(
                name="",
                entry_condition="RSI(14) < 30",
                exit_condition="RSI(14) > 70",
                created_by="01HUSER001",
            )

    def test_create_with_whitespace_name_raises(self) -> None:
        """Whitespace-only name should raise ValidationError."""
        service, _ = _make_service()

        with pytest.raises(ValidationError, match="name is required"):
            service.create_strategy(
                name="   ",
                entry_condition="RSI(14) < 30",
                exit_condition="RSI(14) > 70",
                created_by="01HUSER001",
            )

    def test_create_minimal_fields(self) -> None:
        """Only required fields should work (name, conditions, created_by)."""
        service, repo = _make_service()

        result = service.create_strategy(
            name="Minimal",
            entry_condition="price > SMA(20)",
            exit_condition="price < SMA(20)",
            created_by="01HUSER001",
        )

        assert result["strategy"]["name"] == "Minimal"
        assert repo.count() == 1

    def test_create_preserves_risk_parameters(self) -> None:
        """Risk parameters should be stored in the code JSON."""
        service, repo = _make_service()

        service.create_strategy(
            name="Risk Test",
            entry_condition="RSI(14) < 30",
            exit_condition="RSI(14) > 70",
            max_position_size=50000,
            stop_loss_percent=3.5,
            take_profit_percent=7.0,
            created_by="01HUSER001",
        )

        stored = repo.get_all()[0]
        code_doc = json.loads(stored["code"])
        assert code_doc["max_position_size"] == 50000
        assert code_doc["stop_loss_percent"] == 3.5
        assert code_doc["take_profit_percent"] == 7.0


# ---------------------------------------------------------------------------
# Get strategy
# ---------------------------------------------------------------------------


class TestGetStrategy:
    """Tests for strategy retrieval."""

    def test_get_existing_strategy(self) -> None:
        """Should return strategy with parsed code fields."""
        service, _ = _make_service()

        created = service.create_strategy(
            name="Test Get",
            entry_condition="RSI(14) < 30",
            exit_condition="RSI(14) > 70",
            instrument="AAPL",
            created_by="01HUSER001",
        )

        strategy_id = created["strategy"]["id"]
        result = service.get_strategy(strategy_id)

        assert result["name"] == "Test Get"
        assert "parsed_code" in result
        assert result["parsed_code"]["entry_condition"] == "RSI(14) < 30"
        assert result["parsed_code"]["instrument"] == "AAPL"

    def test_get_nonexistent_raises_not_found(self) -> None:
        """Nonexistent ID should raise NotFoundError."""
        service, _ = _make_service()

        with pytest.raises(NotFoundError, match="not found"):
            service.get_strategy("01HNONEXISTENT0000000000")


# ---------------------------------------------------------------------------
# List strategies
# ---------------------------------------------------------------------------


class TestListStrategies:
    """Tests for strategy listing."""

    def test_list_empty(self) -> None:
        """Empty repo returns empty list."""
        service, _ = _make_service()

        result = service.list_strategies()
        assert result["strategies"] == []
        assert result["count"] == 0

    def test_list_returns_all(self) -> None:
        """All created strategies appear in the list."""
        service, _ = _make_service()

        for i in range(3):
            service.create_strategy(
                name=f"Strategy {i}",
                entry_condition="RSI(14) < 30",
                exit_condition="RSI(14) > 70",
                created_by="01HUSER001",
            )

        result = service.list_strategies()
        assert result["count"] == 3

    def test_list_with_pagination(self) -> None:
        """Pagination should limit results."""
        service, _ = _make_service()

        for i in range(5):
            service.create_strategy(
                name=f"Strategy {i}",
                entry_condition="RSI(14) < 30",
                exit_condition="RSI(14) > 70",
                created_by="01HUSER001",
            )

        result = service.list_strategies(limit=2, offset=0)
        assert result["count"] == 2
        assert result["limit"] == 2

    def test_list_filter_by_creator(self) -> None:
        """created_by filter should narrow results."""
        service, _ = _make_service()

        service.create_strategy(
            name="User1 Strategy",
            entry_condition="RSI(14) < 30",
            exit_condition="RSI(14) > 70",
            created_by="01HUSER001",
        )
        service.create_strategy(
            name="User2 Strategy",
            entry_condition="RSI(14) < 30",
            exit_condition="RSI(14) > 70",
            created_by="01HUSER002",
        )

        result = service.list_strategies(created_by="01HUSER001")
        assert result["count"] == 1
        assert result["strategies"][0]["created_by"] == "01HUSER001"


# ---------------------------------------------------------------------------
# Validate DSL
# ---------------------------------------------------------------------------


class TestValidateDsl:
    """Tests for standalone DSL validation."""

    def test_valid_expression(self) -> None:
        """Valid expression returns is_valid=True."""
        service, _ = _make_service()

        result = service.validate_dsl_expression("RSI(14) < 30 AND price > SMA(200)")
        assert result["is_valid"] is True
        assert result["errors"] == []
        assert "RSI" in result["indicators_used"]

    def test_invalid_expression(self) -> None:
        """Invalid expression returns structured errors."""
        service, _ = _make_service()

        result = service.validate_dsl_expression("RSI() < 30")
        assert result["is_valid"] is False
        assert len(result["errors"]) > 0
        assert result["errors"][0]["message"] is not None

    def test_empty_expression(self) -> None:
        """Empty expression returns is_valid=False."""
        service, _ = _make_service()

        result = service.validate_dsl_expression("")
        assert result["is_valid"] is False
