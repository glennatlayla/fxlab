"""
Unit tests for StressTestService.

Validates scenario execution, predefined scenarios, custom shocks,
halt detection, margin impact, and edge cases.

Naming convention: test_<unit>_<scenario>_<expected_outcome>
"""

from __future__ import annotations

from decimal import Decimal
from typing import Any

import pytest

from libs.contracts.errors import NotFoundError
from libs.contracts.risk import PreTradeRiskLimits
from libs.contracts.stress_test import (
    PREDEFINED_SCENARIOS,
    ScenarioLibrary,
    StressScenario,
)
from services.api.services.stress_test_service import StressTestService

# ---------------------------------------------------------------------------
# Mock repositories
# ---------------------------------------------------------------------------

_DEPLOY_ID = "01HTESTDEPLOY000000000000"


class MockPositionRepo:
    """In-memory mock position repository for stress test tests."""

    def __init__(self) -> None:
        self._positions: list[dict[str, Any]] = []

    def set_positions(self, positions: list[dict[str, Any]]) -> None:
        self._positions = positions

    def list_by_deployment(self, *, deployment_id: str) -> list[dict[str, Any]]:
        return [p for p in self._positions if p.get("deployment_id") == deployment_id]


class MockRiskGate:
    """Mock risk gate for halt trigger detection."""

    def __init__(self) -> None:
        self._limits: dict[str, PreTradeRiskLimits] = {}
        self._raise_not_found: bool = False

    def set_limits(self, deployment_id: str, limits: PreTradeRiskLimits) -> None:
        self._limits[deployment_id] = limits

    def set_raise_not_found(self) -> None:
        self._raise_not_found = True

    def get_risk_limits(self, *, deployment_id: str) -> PreTradeRiskLimits:
        if self._raise_not_found or deployment_id not in self._limits:
            raise NotFoundError("No risk limits configured")
        return self._limits[deployment_id]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_position(
    symbol: str,
    market_value: str,
) -> dict[str, Any]:
    return {
        "id": f"01HPOS{symbol}00000000000000",
        "deployment_id": _DEPLOY_ID,
        "symbol": symbol,
        "quantity": "100",
        "average_entry_price": "100.00",
        "market_price": "100.00",
        "market_value": market_value,
        "unrealized_pnl": "0",
        "realized_pnl": "0",
        "cost_basis": "10000.00",
    }


def _make_service(
    positions: list[dict[str, Any]] | None = None,
    risk_gate: MockRiskGate | None = None,
) -> StressTestService:
    pos_repo = MockPositionRepo()
    if positions:
        pos_repo.set_positions(positions)
    return StressTestService(
        position_repo=pos_repo,
        risk_gate=risk_gate,
    )


# ---------------------------------------------------------------------------
# run_scenario — custom scenarios
# ---------------------------------------------------------------------------


class TestRunScenario:
    """Tests for custom scenario execution."""

    def test_wildcard_shock_applies_to_all(self) -> None:
        """Wildcard '*' shock applies to every position."""
        positions = [
            _make_position("AAPL", "10000.00"),
            _make_position("MSFT", "5000.00"),
        ]
        service = _make_service(positions=positions)
        scenario = StressScenario(
            name="Test Crash",
            shocks={"*": Decimal("-10.0")},
        )

        result = service.run_scenario(deployment_id=_DEPLOY_ID, scenario=scenario)

        assert result.portfolio_pnl_impact == Decimal("-1500.00")
        assert len(result.per_symbol_impact) == 2

    def test_symbol_specific_shock(self) -> None:
        """Symbol-specific shock overrides wildcard."""
        positions = [
            _make_position("AAPL", "10000.00"),
            _make_position("MSFT", "10000.00"),
        ]
        service = _make_service(positions=positions)
        scenario = StressScenario(
            name="AAPL Crash",
            shocks={"AAPL": Decimal("-50.0"), "*": Decimal("-5.0")},
        )

        result = service.run_scenario(deployment_id=_DEPLOY_ID, scenario=scenario)

        aapl_impact = next(si for si in result.per_symbol_impact if si.symbol == "AAPL")
        msft_impact = next(si for si in result.per_symbol_impact if si.symbol == "MSFT")
        assert aapl_impact.shock_pct == Decimal("-50.0")
        assert aapl_impact.pnl_impact == Decimal("-5000.00")
        assert msft_impact.shock_pct == Decimal("-5.0")
        assert msft_impact.pnl_impact == Decimal("-500.00")

    def test_100_percent_drawdown_zeros_portfolio(self) -> None:
        """100% drawdown should zero out the portfolio."""
        positions = [_make_position("AAPL", "10000.00")]
        service = _make_service(positions=positions)
        scenario = StressScenario(
            name="Total Loss",
            shocks={"*": Decimal("-100.0")},
        )

        result = service.run_scenario(deployment_id=_DEPLOY_ID, scenario=scenario)

        assert result.portfolio_pnl_impact == Decimal("-10000.00")
        assert result.per_symbol_impact[0].stressed_value == Decimal("0.00")

    def test_positive_shock(self) -> None:
        """Positive shock increases position values."""
        positions = [_make_position("AAPL", "10000.00")]
        service = _make_service(positions=positions)
        scenario = StressScenario(
            name="Rally",
            shocks={"*": Decimal("20.0")},
        )

        result = service.run_scenario(deployment_id=_DEPLOY_ID, scenario=scenario)

        assert result.portfolio_pnl_impact == Decimal("2000.00")
        assert result.per_symbol_impact[0].stressed_value == Decimal("12000.00")

    def test_unmatched_symbol_gets_zero_shock(self) -> None:
        """Position with no matching shock and no wildcard gets 0% shock."""
        positions = [
            _make_position("AAPL", "10000.00"),
            _make_position("MSFT", "5000.00"),
        ]
        service = _make_service(positions=positions)
        scenario = StressScenario(
            name="AAPL Only",
            shocks={"AAPL": Decimal("-20.0")},
        )

        result = service.run_scenario(deployment_id=_DEPLOY_ID, scenario=scenario)

        msft_impact = next(si for si in result.per_symbol_impact if si.symbol == "MSFT")
        assert msft_impact.shock_pct == Decimal("0")
        assert msft_impact.pnl_impact == Decimal("0.00")

    def test_sorted_by_absolute_impact(self) -> None:
        """Per-symbol impacts should be sorted by absolute impact descending."""
        positions = [
            _make_position("AAPL", "1000.00"),
            _make_position("MSFT", "50000.00"),
        ]
        service = _make_service(positions=positions)
        scenario = StressScenario(
            name="Crash",
            shocks={"*": Decimal("-10.0")},
        )

        result = service.run_scenario(deployment_id=_DEPLOY_ID, scenario=scenario)

        assert result.per_symbol_impact[0].symbol == "MSFT"

    def test_margin_impact_is_half_pnl(self) -> None:
        """Margin impact should be 50% of portfolio P&L impact."""
        positions = [_make_position("AAPL", "10000.00")]
        service = _make_service(positions=positions)
        scenario = StressScenario(
            name="Test",
            shocks={"*": Decimal("-20.0")},
        )

        result = service.run_scenario(deployment_id=_DEPLOY_ID, scenario=scenario)

        assert result.margin_impact == result.portfolio_pnl_impact * Decimal("0.5")

    def test_raises_not_found_no_positions(self) -> None:
        service = _make_service(positions=[])
        scenario = StressScenario(name="Test", shocks={"*": Decimal("-5.0")})
        with pytest.raises(NotFoundError):
            service.run_scenario(deployment_id=_DEPLOY_ID, scenario=scenario)


# ---------------------------------------------------------------------------
# run_predefined
# ---------------------------------------------------------------------------


class TestRunPredefined:
    """Tests for predefined scenario execution."""

    def test_flash_crash_applies_correct_shock(self) -> None:
        positions = [_make_position("AAPL", "100000.00")]
        service = _make_service(positions=positions)

        result = service.run_predefined(
            deployment_id=_DEPLOY_ID,
            scenario_name=ScenarioLibrary.FLASH_CRASH_2010,
        )

        # -8.7% of 100000 = -8700
        assert result.portfolio_pnl_impact == Decimal("-8700.00")
        assert result.scenario_name == "Flash Crash 2010"

    def test_covid_scenario(self) -> None:
        positions = [_make_position("AAPL", "100000.00")]
        service = _make_service(positions=positions)

        result = service.run_predefined(
            deployment_id=_DEPLOY_ID,
            scenario_name=ScenarioLibrary.COVID_MARCH_2020,
        )

        assert result.portfolio_pnl_impact == Decimal("-34000.00")

    def test_all_predefined_scenarios_run(self) -> None:
        """Every predefined scenario should execute without error."""
        positions = [_make_position("AAPL", "10000.00")]
        service = _make_service(positions=positions)

        for scenario_name in PREDEFINED_SCENARIOS:
            result = service.run_predefined(
                deployment_id=_DEPLOY_ID,
                scenario_name=scenario_name,
            )
            assert result.scenario_name is not None

    def test_custom_scenario_not_in_predefined(self) -> None:
        """CUSTOM is not in PREDEFINED_SCENARIOS — should raise."""
        positions = [_make_position("AAPL", "10000.00")]
        service = _make_service(positions=positions)

        with pytest.raises(NotFoundError, match="not found"):
            service.run_predefined(
                deployment_id=_DEPLOY_ID,
                scenario_name=ScenarioLibrary.CUSTOM,
            )


# ---------------------------------------------------------------------------
# Halt trigger detection
# ---------------------------------------------------------------------------


class TestHaltTrigger:
    """Tests for halt trigger detection."""

    def test_triggers_halt_when_loss_exceeds_limit(self) -> None:
        risk_gate = MockRiskGate()
        risk_gate.set_limits(
            _DEPLOY_ID,
            PreTradeRiskLimits(max_daily_loss=Decimal("5000")),
        )
        positions = [_make_position("AAPL", "100000.00")]
        service = _make_service(positions=positions, risk_gate=risk_gate)
        scenario = StressScenario(name="Crash", shocks={"*": Decimal("-10.0")})

        result = service.run_scenario(deployment_id=_DEPLOY_ID, scenario=scenario)

        # 10% of 100000 = 10000 > 5000 limit
        assert result.would_trigger_halt is True
        assert result.daily_loss_limit == Decimal("5000")

    def test_no_halt_when_loss_below_limit(self) -> None:
        risk_gate = MockRiskGate()
        risk_gate.set_limits(
            _DEPLOY_ID,
            PreTradeRiskLimits(max_daily_loss=Decimal("50000")),
        )
        positions = [_make_position("AAPL", "10000.00")]
        service = _make_service(positions=positions, risk_gate=risk_gate)
        scenario = StressScenario(name="Small Drop", shocks={"*": Decimal("-5.0")})

        result = service.run_scenario(deployment_id=_DEPLOY_ID, scenario=scenario)

        assert result.would_trigger_halt is False

    def test_no_halt_when_no_risk_gate(self) -> None:
        positions = [_make_position("AAPL", "100000.00")]
        service = _make_service(positions=positions, risk_gate=None)
        scenario = StressScenario(name="Crash", shocks={"*": Decimal("-50.0")})

        result = service.run_scenario(deployment_id=_DEPLOY_ID, scenario=scenario)

        assert result.would_trigger_halt is False
        assert result.daily_loss_limit is None

    def test_no_halt_when_no_limits_configured(self) -> None:
        risk_gate = MockRiskGate()
        risk_gate.set_raise_not_found()
        positions = [_make_position("AAPL", "100000.00")]
        service = _make_service(positions=positions, risk_gate=risk_gate)
        scenario = StressScenario(name="Crash", shocks={"*": Decimal("-50.0")})

        result = service.run_scenario(deployment_id=_DEPLOY_ID, scenario=scenario)

        assert result.would_trigger_halt is False


# ---------------------------------------------------------------------------
# list_predefined_scenarios
# ---------------------------------------------------------------------------


class TestListPredefined:
    """Tests for listing predefined scenarios."""

    def test_returns_all_predefined(self) -> None:
        service = _make_service(positions=[])
        scenarios = service.list_predefined_scenarios()
        assert len(scenarios) == len(PREDEFINED_SCENARIOS)

    def test_all_returned_are_predefined(self) -> None:
        service = _make_service(positions=[])
        for s in service.list_predefined_scenarios():
            assert s.is_predefined is True

    def test_sorted_by_name(self) -> None:
        service = _make_service(positions=[])
        scenarios = service.list_predefined_scenarios()
        names = [s.name for s in scenarios]
        assert names == sorted(names)
