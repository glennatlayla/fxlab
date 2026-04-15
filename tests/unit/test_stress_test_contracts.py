"""
Unit tests for stress testing and scenario analysis contracts.

Validates Pydantic models: StressScenario, SymbolStressImpact,
StressTestResult, ScenarioLibrary, and PREDEFINED_SCENARIOS.

Naming convention: test_<unit>_<scenario>_<expected_outcome>
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

import pytest
from pydantic import ValidationError

from libs.contracts.stress_test import (
    PREDEFINED_SCENARIOS,
    ScenarioLibrary,
    StressScenario,
    StressTestResult,
    SymbolStressImpact,
)

_NOW = datetime(2026, 4, 12, 12, 0, 0, tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# ScenarioLibrary
# ---------------------------------------------------------------------------


class TestScenarioLibrary:
    """Tests for ScenarioLibrary enum."""

    def test_all_values(self) -> None:
        assert ScenarioLibrary.FLASH_CRASH_2010.value == "flash_crash_2010"
        assert ScenarioLibrary.COVID_MARCH_2020.value == "covid_march_2020"
        assert ScenarioLibrary.RATE_HIKE_2022.value == "rate_hike_2022"
        assert ScenarioLibrary.SECTOR_ROTATION.value == "sector_rotation"
        assert ScenarioLibrary.CUSTOM.value == "custom"

    def test_from_string(self) -> None:
        assert ScenarioLibrary("flash_crash_2010") is ScenarioLibrary.FLASH_CRASH_2010


# ---------------------------------------------------------------------------
# StressScenario
# ---------------------------------------------------------------------------


class TestStressScenario:
    """Tests for StressScenario construction and validation."""

    def test_construction(self) -> None:
        scenario = StressScenario(
            name="Test",
            description="A test scenario",
            shocks={"AAPL": Decimal("-10.0")},
        )
        assert scenario.name == "Test"
        assert scenario.shocks["AAPL"] == Decimal("-10.0")
        assert scenario.is_predefined is False
        assert scenario.scenario_type is ScenarioLibrary.CUSTOM

    def test_frozen_model(self) -> None:
        scenario = StressScenario(name="Test", shocks={"*": Decimal("-5.0")})
        with pytest.raises(ValidationError):
            scenario.name = "Changed"  # type: ignore[misc]

    def test_wildcard_shock(self) -> None:
        scenario = StressScenario(name="All Positions", shocks={"*": Decimal("-8.7")})
        assert "*" in scenario.shocks

    def test_empty_name_rejected(self) -> None:
        with pytest.raises(ValidationError):
            StressScenario(name="", shocks={"*": Decimal("-5.0")})

    def test_empty_shocks_rejected(self) -> None:
        with pytest.raises(ValidationError, match="shocks"):
            StressScenario(name="Test", shocks={})

    def test_serialization_roundtrip(self) -> None:
        scenario = StressScenario(
            name="Test",
            shocks={"AAPL": Decimal("-10.0"), "MSFT": Decimal("-5.0")},
        )
        data = scenario.model_dump()
        restored = StressScenario(**data)
        assert restored.name == scenario.name
        assert restored.shocks == scenario.shocks


# ---------------------------------------------------------------------------
# SymbolStressImpact
# ---------------------------------------------------------------------------


class TestSymbolStressImpact:
    """Tests for SymbolStressImpact construction and validation."""

    def test_construction(self) -> None:
        impact = SymbolStressImpact(
            symbol="AAPL",
            current_value=Decimal("10000.00"),
            shock_pct=Decimal("-8.7"),
            stressed_value=Decimal("9130.00"),
            pnl_impact=Decimal("-870.00"),
        )
        assert impact.symbol == "AAPL"
        assert impact.pnl_impact == Decimal("-870.00")

    def test_frozen_model(self) -> None:
        impact = SymbolStressImpact(
            symbol="AAPL",
            current_value=Decimal("10000"),
            shock_pct=Decimal("-5"),
            stressed_value=Decimal("9500"),
            pnl_impact=Decimal("-500"),
        )
        with pytest.raises(ValidationError):
            impact.pnl_impact = Decimal("0")  # type: ignore[misc]

    def test_empty_symbol_rejected(self) -> None:
        with pytest.raises(ValidationError):
            SymbolStressImpact(
                symbol="",
                current_value=Decimal("10000"),
                shock_pct=Decimal("-5"),
                stressed_value=Decimal("9500"),
                pnl_impact=Decimal("-500"),
            )


# ---------------------------------------------------------------------------
# StressTestResult
# ---------------------------------------------------------------------------


class TestStressTestResult:
    """Tests for StressTestResult construction and validation."""

    def test_construction(self) -> None:
        result = StressTestResult(
            scenario_name="Flash Crash",
            portfolio_pnl_impact=Decimal("-8700.00"),
            per_symbol_impact=[
                SymbolStressImpact(
                    symbol="AAPL",
                    current_value=Decimal("10000"),
                    shock_pct=Decimal("-8.7"),
                    stressed_value=Decimal("9130"),
                    pnl_impact=Decimal("-870"),
                ),
            ],
            margin_impact=Decimal("-4350.00"),
            would_trigger_halt=True,
            daily_loss_limit=Decimal("5000.00"),
            computed_at=_NOW,
        )
        assert result.portfolio_pnl_impact == Decimal("-8700.00")
        assert result.would_trigger_halt is True
        assert result.daily_loss_limit == Decimal("5000.00")

    def test_frozen_model(self) -> None:
        result = StressTestResult(
            scenario_name="Test",
            portfolio_pnl_impact=Decimal("-100"),
            per_symbol_impact=[],
            margin_impact=Decimal("-50"),
            would_trigger_halt=False,
            computed_at=_NOW,
        )
        with pytest.raises(ValidationError):
            result.would_trigger_halt = True  # type: ignore[misc]

    def test_default_computed_at(self) -> None:
        result = StressTestResult(
            scenario_name="Test",
            portfolio_pnl_impact=Decimal("-100"),
            per_symbol_impact=[],
            margin_impact=Decimal("-50"),
            would_trigger_halt=False,
        )
        assert result.computed_at.tzinfo is not None

    def test_serialization_roundtrip(self) -> None:
        result = StressTestResult(
            scenario_name="Test",
            portfolio_pnl_impact=Decimal("-5000"),
            per_symbol_impact=[
                SymbolStressImpact(
                    symbol="AAPL",
                    current_value=Decimal("10000"),
                    shock_pct=Decimal("-50"),
                    stressed_value=Decimal("5000"),
                    pnl_impact=Decimal("-5000"),
                ),
            ],
            margin_impact=Decimal("-2500"),
            would_trigger_halt=True,
            computed_at=_NOW,
        )
        data = result.model_dump()
        restored = StressTestResult(**data)
        assert restored.portfolio_pnl_impact == result.portfolio_pnl_impact


# ---------------------------------------------------------------------------
# PREDEFINED_SCENARIOS
# ---------------------------------------------------------------------------


class TestPredefinedScenarios:
    """Tests for the predefined scenario library."""

    def test_all_non_custom_scenarios_defined(self) -> None:
        """Every non-CUSTOM ScenarioLibrary member must have a predefined scenario."""
        for member in ScenarioLibrary:
            if member is not ScenarioLibrary.CUSTOM:
                assert member in PREDEFINED_SCENARIOS, f"{member} missing"

    def test_flash_crash_shock(self) -> None:
        scenario = PREDEFINED_SCENARIOS[ScenarioLibrary.FLASH_CRASH_2010]
        assert scenario.shocks["*"] == Decimal("-8.7")
        assert scenario.is_predefined is True

    def test_covid_shock(self) -> None:
        scenario = PREDEFINED_SCENARIOS[ScenarioLibrary.COVID_MARCH_2020]
        assert scenario.shocks["*"] == Decimal("-34.0")

    def test_rate_hike_shock(self) -> None:
        scenario = PREDEFINED_SCENARIOS[ScenarioLibrary.RATE_HIKE_2022]
        assert scenario.shocks["*"] == Decimal("-33.0")

    def test_sector_rotation_shock(self) -> None:
        scenario = PREDEFINED_SCENARIOS[ScenarioLibrary.SECTOR_ROTATION]
        assert scenario.shocks["*"] == Decimal("-15.0")

    def test_all_predefined_are_marked(self) -> None:
        for scenario in PREDEFINED_SCENARIOS.values():
            assert scenario.is_predefined is True
