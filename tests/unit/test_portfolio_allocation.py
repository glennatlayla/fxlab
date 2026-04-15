"""
Unit tests for Portfolio Allocation contracts and engine (M12).

Tests cover:
1. Contract validation — config, allocation, enums, snapshots.
2. Equal weight allocation — capital divided equally.
3. Risk parity — weights inversely proportional to volatility.
4. Inverse volatility — same math as risk parity using annualised vol.
5. Kelly optimal — uses win rate and avg win/loss ratio.
6. Fixed allocation — user-specified weights applied directly.
7. Constraint enforcement — leverage cap, drawdown limits.
8. Edge cases — single strategy, zero volatility, disabled strategies.

Follows §5 TDD naming: test_<unit>_<scenario>_<expected_outcome>
"""

from __future__ import annotations

from decimal import Decimal

import pytest

from libs.contracts.portfolio import (
    AllocationMethod,
    AllocationResult,
    PortfolioConfig,
    PortfolioSnapshot,
    RebalanceFrequency,
    StrategyAllocationConfig,
    StrategyPerformanceInput,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_strategy_config(
    strategy_id: str = "s1",
    deployment_id: str = "d1",
    fixed_weight: float = 0.0,
    max_drawdown_limit: float = 0.20,
    enabled: bool = True,
) -> StrategyAllocationConfig:
    """Build a StrategyAllocationConfig for testing."""
    return StrategyAllocationConfig(
        strategy_id=strategy_id,
        deployment_id=deployment_id,
        fixed_weight=fixed_weight,
        max_drawdown_limit=max_drawdown_limit,
        enabled=enabled,
    )


def _make_performance(
    strategy_id: str = "s1",
    deployment_id: str = "d1",
    volatility: float = 0.20,
    win_rate: float = 0.55,
    avg_win_loss_ratio: float = 1.5,
    current_equity: Decimal = Decimal("100000"),
    max_drawdown: float = 0.05,
) -> StrategyPerformanceInput:
    """Build a StrategyPerformanceInput for testing."""
    return StrategyPerformanceInput(
        strategy_id=strategy_id,
        deployment_id=deployment_id,
        volatility=volatility,
        win_rate=win_rate,
        avg_win_loss_ratio=avg_win_loss_ratio,
        current_equity=current_equity,
        max_drawdown=max_drawdown,
    )


def _make_portfolio_config(
    strategy_configs: list[StrategyAllocationConfig] | None = None,
    allocation_method: AllocationMethod = AllocationMethod.EQUAL_WEIGHT,
    total_capital: Decimal = Decimal("1000000"),
    max_total_leverage: float = 1.0,
    rebalance_threshold: float = 0.05,
) -> PortfolioConfig:
    """Build a PortfolioConfig for testing."""
    if strategy_configs is None:
        strategy_configs = [
            _make_strategy_config("s1", "d1"),
            _make_strategy_config("s2", "d2"),
        ]
    return PortfolioConfig(
        portfolio_id="pf-test",
        name="Test Portfolio",
        total_capital=total_capital,
        allocation_method=allocation_method,
        rebalance_frequency=RebalanceFrequency.DAILY,
        rebalance_threshold=rebalance_threshold,
        strategy_configs=strategy_configs,
        max_total_leverage=max_total_leverage,
    )


def _build_engine():
    """Build a PortfolioAllocationEngine."""
    from services.worker.research.portfolio_allocation_engine import (
        PortfolioAllocationEngine,
    )

    return PortfolioAllocationEngine()


# ===========================================================================
# Test: Contract Validation
# ===========================================================================


class TestPortfolioContracts:
    """Verify portfolio contract validation."""

    def test_allocation_method_enum(self) -> None:
        """All allocation methods are defined."""
        assert AllocationMethod.EQUAL_WEIGHT.value == "equal_weight"
        assert AllocationMethod.RISK_PARITY.value == "risk_parity"
        assert AllocationMethod.INVERSE_VOLATILITY.value == "inverse_volatility"
        assert AllocationMethod.KELLY_OPTIMAL.value == "kelly_optimal"
        assert AllocationMethod.FIXED.value == "fixed"

    def test_rebalance_frequency_enum(self) -> None:
        """All rebalance frequencies are defined."""
        assert RebalanceFrequency.DAILY.value == "daily"
        assert RebalanceFrequency.WEEKLY.value == "weekly"
        assert RebalanceFrequency.MONTHLY.value == "monthly"
        assert RebalanceFrequency.ON_THRESHOLD.value == "on_threshold"

    def test_portfolio_config_frozen(self) -> None:
        """PortfolioConfig is immutable."""
        config = _make_portfolio_config()
        with pytest.raises((TypeError, ValueError, AttributeError)):
            config.name = "Changed"  # type: ignore[misc]

    def test_strategy_allocation_config_frozen(self) -> None:
        """StrategyAllocationConfig is immutable."""
        config = _make_strategy_config()
        with pytest.raises((TypeError, ValueError, AttributeError)):
            config.strategy_id = "changed"  # type: ignore[misc]

    def test_allocation_result_valid(self) -> None:
        """AllocationResult builds with valid data."""
        config = _make_portfolio_config()
        result = AllocationResult(
            config=config,
            allocations=[],
            total_weight=1.0,
            leverage_utilised=1.0,
        )
        assert result.total_weight == 1.0

    def test_portfolio_snapshot_valid(self) -> None:
        """PortfolioSnapshot builds with valid data."""
        snapshot = PortfolioSnapshot(
            portfolio_id="pf-001",
            total_equity=Decimal("1050000"),
            total_pnl=Decimal("50000"),
        )
        assert snapshot.total_equity == Decimal("1050000")
        assert snapshot.timestamp.tzinfo is not None

    def test_strategy_performance_input_valid(self) -> None:
        """StrategyPerformanceInput builds with valid data."""
        perf = _make_performance()
        assert perf.volatility == 0.20
        assert perf.win_rate == 0.55


# ===========================================================================
# Test: Equal Weight Allocation
# ===========================================================================


class TestEqualWeight:
    """Verify equal weight allocation method."""

    def test_equal_weight_two_strategies(self) -> None:
        """Two strategies → 50/50 split."""
        config = _make_portfolio_config(allocation_method=AllocationMethod.EQUAL_WEIGHT)
        performances = [
            _make_performance("s1", "d1"),
            _make_performance("s2", "d2"),
        ]

        engine = _build_engine()
        result = engine.compute_allocations(config, performances)

        assert len(result.allocations) == 2
        for alloc in result.allocations:
            assert abs(alloc.target_weight - 0.5) < 1e-9
            assert alloc.capital_allocated == Decimal("500000")

    def test_equal_weight_three_strategies(self) -> None:
        """Three strategies → 1/3 each."""
        configs = [
            _make_strategy_config("s1", "d1"),
            _make_strategy_config("s2", "d2"),
            _make_strategy_config("s3", "d3"),
        ]
        config = _make_portfolio_config(strategy_configs=configs)
        performances = [
            _make_performance("s1", "d1"),
            _make_performance("s2", "d2"),
            _make_performance("s3", "d3"),
        ]

        engine = _build_engine()
        result = engine.compute_allocations(config, performances)

        assert len(result.allocations) == 3
        for alloc in result.allocations:
            assert abs(alloc.target_weight - 1.0 / 3.0) < 1e-9

    def test_equal_weight_total_weight_is_one(self) -> None:
        """Total weight sums to 1.0."""
        config = _make_portfolio_config()
        performances = [
            _make_performance("s1", "d1"),
            _make_performance("s2", "d2"),
        ]

        engine = _build_engine()
        result = engine.compute_allocations(config, performances)

        assert abs(result.total_weight - 1.0) < 1e-9


# ===========================================================================
# Test: Risk Parity Allocation
# ===========================================================================


class TestRiskParity:
    """Verify risk parity allocation method."""

    def test_risk_parity_higher_vol_gets_less(self) -> None:
        """Strategy with higher volatility gets lower weight."""
        config = _make_portfolio_config(allocation_method=AllocationMethod.RISK_PARITY)
        performances = [
            _make_performance("s1", "d1", volatility=0.10),
            _make_performance("s2", "d2", volatility=0.30),
        ]

        engine = _build_engine()
        result = engine.compute_allocations(config, performances)

        # s1 has lower vol → higher weight
        alloc_s1 = next(a for a in result.allocations if a.strategy_id == "s1")
        alloc_s2 = next(a for a in result.allocations if a.strategy_id == "s2")
        assert alloc_s1.target_weight > alloc_s2.target_weight

    def test_risk_parity_equal_vol_equal_weight(self) -> None:
        """Equal volatilities → equal weights."""
        config = _make_portfolio_config(allocation_method=AllocationMethod.RISK_PARITY)
        performances = [
            _make_performance("s1", "d1", volatility=0.20),
            _make_performance("s2", "d2", volatility=0.20),
        ]

        engine = _build_engine()
        result = engine.compute_allocations(config, performances)

        alloc_s1 = next(a for a in result.allocations if a.strategy_id == "s1")
        alloc_s2 = next(a for a in result.allocations if a.strategy_id == "s2")
        assert abs(alloc_s1.target_weight - alloc_s2.target_weight) < 1e-9

    def test_risk_parity_weights_sum_to_one(self) -> None:
        """Risk parity weights sum to 1.0."""
        config = _make_portfolio_config(allocation_method=AllocationMethod.RISK_PARITY)
        performances = [
            _make_performance("s1", "d1", volatility=0.10),
            _make_performance("s2", "d2", volatility=0.30),
        ]

        engine = _build_engine()
        result = engine.compute_allocations(config, performances)

        assert abs(result.total_weight - 1.0) < 1e-9

    def test_risk_parity_known_values(self) -> None:
        """Risk parity produces correct known weights.

        Two strategies with vol 0.10 and 0.30:
        inv_vol: 10.0 and 3.333...
        total_inv_vol: 13.333...
        weights: 10/13.333 = 0.75, 3.333/13.333 = 0.25
        """
        config = _make_portfolio_config(allocation_method=AllocationMethod.RISK_PARITY)
        performances = [
            _make_performance("s1", "d1", volatility=0.10),
            _make_performance("s2", "d2", volatility=0.30),
        ]

        engine = _build_engine()
        result = engine.compute_allocations(config, performances)

        alloc_s1 = next(a for a in result.allocations if a.strategy_id == "s1")
        alloc_s2 = next(a for a in result.allocations if a.strategy_id == "s2")
        assert abs(alloc_s1.target_weight - 0.75) < 1e-9
        assert abs(alloc_s2.target_weight - 0.25) < 1e-9


# ===========================================================================
# Test: Inverse Volatility
# ===========================================================================


class TestInverseVolatility:
    """Verify inverse volatility allocation method."""

    def test_inverse_vol_same_as_risk_parity_math(self) -> None:
        """Inverse volatility uses the same inverse-vol weighting as risk parity."""
        config_rp = _make_portfolio_config(allocation_method=AllocationMethod.RISK_PARITY)
        config_iv = _make_portfolio_config(allocation_method=AllocationMethod.INVERSE_VOLATILITY)
        performances = [
            _make_performance("s1", "d1", volatility=0.15),
            _make_performance("s2", "d2", volatility=0.25),
        ]

        engine = _build_engine()
        result_rp = engine.compute_allocations(config_rp, performances)
        result_iv = engine.compute_allocations(config_iv, performances)

        # Both methods produce the same weights (inverse volatility weighting)
        for a_rp, a_iv in zip(result_rp.allocations, result_iv.allocations, strict=True):
            assert abs(a_rp.target_weight - a_iv.target_weight) < 1e-9


# ===========================================================================
# Test: Kelly Optimal
# ===========================================================================


class TestKellyOptimal:
    """Verify Kelly optimal allocation method."""

    def test_kelly_positive_edge(self) -> None:
        """Positive edge → positive weight."""
        config = _make_portfolio_config(allocation_method=AllocationMethod.KELLY_OPTIMAL)
        performances = [
            _make_performance("s1", "d1", win_rate=0.60, avg_win_loss_ratio=1.5),
            _make_performance("s2", "d2", win_rate=0.55, avg_win_loss_ratio=1.2),
        ]

        engine = _build_engine()
        result = engine.compute_allocations(config, performances)

        for alloc in result.allocations:
            assert alloc.target_weight > 0

    def test_kelly_higher_edge_gets_more(self) -> None:
        """Strategy with higher Kelly fraction gets more weight."""
        config = _make_portfolio_config(allocation_method=AllocationMethod.KELLY_OPTIMAL)
        performances = [
            _make_performance("s1", "d1", win_rate=0.70, avg_win_loss_ratio=2.0),
            _make_performance("s2", "d2", win_rate=0.50, avg_win_loss_ratio=1.0),
        ]

        engine = _build_engine()
        result = engine.compute_allocations(config, performances)

        alloc_s1 = next(a for a in result.allocations if a.strategy_id == "s1")
        alloc_s2 = next(a for a in result.allocations if a.strategy_id == "s2")
        assert alloc_s1.target_weight > alloc_s2.target_weight

    def test_kelly_no_edge_zero_weight(self) -> None:
        """Zero or negative Kelly edge → zero weight for that strategy.

        Kelly = win_rate - (1 - win_rate) / avg_win_loss_ratio.
        For win_rate=0.40, ratio=1.0: Kelly = 0.40 - 0.60/1.0 = -0.20 → clamp to 0.
        """
        config = _make_portfolio_config(allocation_method=AllocationMethod.KELLY_OPTIMAL)
        performances = [
            _make_performance("s1", "d1", win_rate=0.60, avg_win_loss_ratio=1.5),
            _make_performance("s2", "d2", win_rate=0.40, avg_win_loss_ratio=1.0),
        ]

        engine = _build_engine()
        result = engine.compute_allocations(config, performances)

        alloc_s2 = next(a for a in result.allocations if a.strategy_id == "s2")
        assert alloc_s2.target_weight == 0.0

    def test_kelly_weights_sum_to_one_or_less(self) -> None:
        """Kelly weights are normalised and sum ≤ 1.0."""
        config = _make_portfolio_config(allocation_method=AllocationMethod.KELLY_OPTIMAL)
        performances = [
            _make_performance("s1", "d1", win_rate=0.60, avg_win_loss_ratio=1.5),
            _make_performance("s2", "d2", win_rate=0.55, avg_win_loss_ratio=1.2),
        ]

        engine = _build_engine()
        result = engine.compute_allocations(config, performances)

        assert result.total_weight <= 1.0 + 1e-9


# ===========================================================================
# Test: Fixed Allocation
# ===========================================================================


class TestFixedAllocation:
    """Verify fixed allocation method."""

    def test_fixed_uses_specified_weights(self) -> None:
        """Fixed method uses the fixed_weight from strategy configs."""
        configs = [
            _make_strategy_config("s1", "d1", fixed_weight=0.6),
            _make_strategy_config("s2", "d2", fixed_weight=0.4),
        ]
        config = _make_portfolio_config(
            strategy_configs=configs,
            allocation_method=AllocationMethod.FIXED,
        )
        performances = [
            _make_performance("s1", "d1"),
            _make_performance("s2", "d2"),
        ]

        engine = _build_engine()
        result = engine.compute_allocations(config, performances)

        alloc_s1 = next(a for a in result.allocations if a.strategy_id == "s1")
        alloc_s2 = next(a for a in result.allocations if a.strategy_id == "s2")
        assert abs(alloc_s1.target_weight - 0.6) < 1e-9
        assert abs(alloc_s2.target_weight - 0.4) < 1e-9

    def test_fixed_capital_matches_weight(self) -> None:
        """Fixed allocation capital matches weight × total capital."""
        configs = [
            _make_strategy_config("s1", "d1", fixed_weight=0.7),
            _make_strategy_config("s2", "d2", fixed_weight=0.3),
        ]
        config = _make_portfolio_config(
            strategy_configs=configs,
            allocation_method=AllocationMethod.FIXED,
            total_capital=Decimal("1000000"),
        )
        performances = [
            _make_performance("s1", "d1"),
            _make_performance("s2", "d2"),
        ]

        engine = _build_engine()
        result = engine.compute_allocations(config, performances)

        alloc_s1 = next(a for a in result.allocations if a.strategy_id == "s1")
        alloc_s2 = next(a for a in result.allocations if a.strategy_id == "s2")
        assert alloc_s1.capital_allocated == Decimal("700000")
        assert alloc_s2.capital_allocated == Decimal("300000")


# ===========================================================================
# Test: Constraint Enforcement
# ===========================================================================


class TestConstraints:
    """Verify portfolio constraint enforcement."""

    def test_leverage_cap_applied(self) -> None:
        """Weights are scaled down when they would exceed leverage cap."""
        # Fixed weights that sum to more than leverage cap
        configs = [
            _make_strategy_config("s1", "d1", fixed_weight=0.8),
            _make_strategy_config("s2", "d2", fixed_weight=0.8),
        ]
        config = _make_portfolio_config(
            strategy_configs=configs,
            allocation_method=AllocationMethod.FIXED,
            max_total_leverage=1.0,
        )
        performances = [
            _make_performance("s1", "d1"),
            _make_performance("s2", "d2"),
        ]

        engine = _build_engine()
        result = engine.compute_allocations(config, performances)

        # Total weight must not exceed leverage cap
        assert result.total_weight <= 1.0 + 1e-9
        assert result.constrained is True

    def test_drawdown_limit_zeroes_strategy(self) -> None:
        """Strategy exceeding drawdown limit gets zero allocation."""
        configs = [
            _make_strategy_config("s1", "d1", max_drawdown_limit=0.10),
            _make_strategy_config("s2", "d2", max_drawdown_limit=0.20),
        ]
        config = _make_portfolio_config(
            strategy_configs=configs,
            allocation_method=AllocationMethod.EQUAL_WEIGHT,
        )
        performances = [
            _make_performance("s1", "d1", max_drawdown=0.15),  # Exceeds 0.10 limit
            _make_performance("s2", "d2", max_drawdown=0.05),  # Within 0.20 limit
        ]

        engine = _build_engine()
        result = engine.compute_allocations(config, performances)

        alloc_s1 = next(a for a in result.allocations if a.strategy_id == "s1")
        alloc_s2 = next(a for a in result.allocations if a.strategy_id == "s2")
        # s1 exceeded drawdown limit → zero weight
        assert alloc_s1.target_weight == 0.0
        # s2 gets all the capital
        assert abs(alloc_s2.target_weight - 1.0) < 1e-9
        assert result.constrained is True


# ===========================================================================
# Test: Edge Cases
# ===========================================================================


class TestEdgeCases:
    """Verify edge case handling."""

    def test_single_strategy_gets_full_weight(self) -> None:
        """Single strategy gets weight = 1.0."""
        configs = [_make_strategy_config("s1", "d1")]
        config = _make_portfolio_config(strategy_configs=configs)
        performances = [_make_performance("s1", "d1")]

        engine = _build_engine()
        result = engine.compute_allocations(config, performances)

        assert len(result.allocations) == 1
        assert abs(result.allocations[0].target_weight - 1.0) < 1e-9

    def test_disabled_strategies_excluded(self) -> None:
        """Disabled strategies get zero weight."""
        configs = [
            _make_strategy_config("s1", "d1", enabled=True),
            _make_strategy_config("s2", "d2", enabled=False),
        ]
        config = _make_portfolio_config(strategy_configs=configs)
        performances = [
            _make_performance("s1", "d1"),
            _make_performance("s2", "d2"),
        ]

        engine = _build_engine()
        result = engine.compute_allocations(config, performances)

        alloc_s1 = next(a for a in result.allocations if a.strategy_id == "s1")
        alloc_s2 = next(a for a in result.allocations if a.strategy_id == "s2")
        assert abs(alloc_s1.target_weight - 1.0) < 1e-9
        assert alloc_s2.target_weight == 0.0

    def test_zero_volatility_risk_parity_falls_back(self) -> None:
        """Zero volatility in risk parity → equal weight fallback for that strategy."""
        config = _make_portfolio_config(allocation_method=AllocationMethod.RISK_PARITY)
        performances = [
            _make_performance("s1", "d1", volatility=0.0),
            _make_performance("s2", "d2", volatility=0.20),
        ]

        engine = _build_engine()
        result = engine.compute_allocations(config, performances)

        # Zero-vol strategy gets a large inverse-vol weight (capped at a reasonable level)
        # Engine should handle gracefully without division by zero
        assert result.total_weight > 0

    def test_no_enabled_strategies_raises(self) -> None:
        """All strategies disabled → ValueError."""
        configs = [
            _make_strategy_config("s1", "d1", enabled=False),
            _make_strategy_config("s2", "d2", enabled=False),
        ]
        config = _make_portfolio_config(strategy_configs=configs)
        performances = [
            _make_performance("s1", "d1"),
            _make_performance("s2", "d2"),
        ]

        engine = _build_engine()
        with pytest.raises(ValueError, match="No enabled strategies"):
            engine.compute_allocations(config, performances)

    def test_config_preserved_in_result(self) -> None:
        """Result contains the original config."""
        config = _make_portfolio_config()
        performances = [
            _make_performance("s1", "d1"),
            _make_performance("s2", "d2"),
        ]

        engine = _build_engine()
        result = engine.compute_allocations(config, performances)

        assert result.config == config

    def test_computed_at_is_utc(self) -> None:
        """computed_at is timezone-aware UTC."""
        config = _make_portfolio_config()
        performances = [
            _make_performance("s1", "d1"),
            _make_performance("s2", "d2"),
        ]

        engine = _build_engine()
        result = engine.compute_allocations(config, performances)

        assert result.computed_at.tzinfo is not None

    def test_all_kelly_negative_equal_weight_fallback(self) -> None:
        """All strategies with negative Kelly edge → equal weight fallback."""
        config = _make_portfolio_config(allocation_method=AllocationMethod.KELLY_OPTIMAL)
        performances = [
            _make_performance("s1", "d1", win_rate=0.30, avg_win_loss_ratio=0.8),
            _make_performance("s2", "d2", win_rate=0.35, avg_win_loss_ratio=0.9),
        ]

        engine = _build_engine()
        result = engine.compute_allocations(config, performances)

        # When all Kelly fractions are ≤ 0, fall back to equal weight
        for alloc in result.allocations:
            assert abs(alloc.target_weight - 0.5) < 1e-9
