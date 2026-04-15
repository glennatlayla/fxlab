"""
Unit tests for Cross-Strategy Risk Aggregation (M14).

Tests cover:
1. Contract validation — VaR, marginal VaR, correlation, drawdown sync, optimization.
2. Portfolio VaR — computed from strategy returns, 95/99 percentiles.
3. Marginal VaR — per-strategy contribution decomposition.
4. Correlation matrix — pairwise correlations, high-correlation alerts.
5. Drawdown sync — detection of simultaneous drawdowns.
6. Optimization — mean-variance suggested weights.
7. Edge cases — single strategy, zero returns, identical strategies.

Follows §5 TDD naming: test_<unit>_<scenario>_<expected_outcome>
"""

from __future__ import annotations

from decimal import Decimal

import numpy as np

from libs.contracts.cross_strategy_risk import (
    CorrelationMatrix,
    DrawdownSyncEvent,
    MarginalVaR,
    OptimizationSuggestion,
    PortfolioVaR,
    VaRMethod,
)
from libs.contracts.portfolio import (
    AllocationMethod,
    PortfolioConfig,
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
) -> StrategyAllocationConfig:
    return StrategyAllocationConfig(
        strategy_id=strategy_id,
        deployment_id=deployment_id,
    )


def _make_performance(
    strategy_id: str = "s1",
    deployment_id: str = "d1",
    volatility: float = 0.20,
    returns: list[float] | None = None,
    current_equity: Decimal = Decimal("500000"),
    max_drawdown: float = 0.05,
) -> StrategyPerformanceInput:
    if returns is None:
        # Generate synthetic daily returns
        rng = np.random.default_rng(hash(strategy_id) % 2**32)
        returns = (rng.normal(0.0005, 0.01, 60)).tolist()
    return StrategyPerformanceInput(
        strategy_id=strategy_id,
        deployment_id=deployment_id,
        volatility=volatility,
        returns=returns,
        win_rate=0.55,
        avg_win_loss_ratio=1.5,
        current_equity=current_equity,
        max_drawdown=max_drawdown,
    )


def _make_portfolio_config(
    strategy_configs: list[StrategyAllocationConfig] | None = None,
    total_capital: Decimal = Decimal("1000000"),
) -> PortfolioConfig:
    if strategy_configs is None:
        strategy_configs = [
            _make_strategy_config("s1", "d1"),
            _make_strategy_config("s2", "d2"),
        ]
    return PortfolioConfig(
        portfolio_id="pf-test",
        name="Test Portfolio",
        total_capital=total_capital,
        allocation_method=AllocationMethod.EQUAL_WEIGHT,
        rebalance_frequency=RebalanceFrequency.DAILY,
        strategy_configs=strategy_configs,
    )


def _build_service():
    from services.api.services.cross_strategy_risk_service import (
        CrossStrategyRiskService,
    )

    return CrossStrategyRiskService()


# ===========================================================================
# Test: Contract Validation
# ===========================================================================


class TestRiskContracts:
    """Verify risk contract validation."""

    def test_var_method_enum(self) -> None:
        """VaR methods are defined."""
        assert VaRMethod.HISTORICAL.value == "historical"
        assert VaRMethod.PARAMETRIC.value == "parametric"

    def test_portfolio_var_valid(self) -> None:
        """PortfolioVaR builds with valid data."""
        var = PortfolioVaR(
            portfolio_id="pf-001",
            var_95=Decimal("25000"),
            var_99=Decimal("40000"),
            total_equity=Decimal("1000000"),
        )
        assert var.var_95 == Decimal("25000")
        assert var.computed_at.tzinfo is not None

    def test_marginal_var_valid(self) -> None:
        """MarginalVaR builds with valid data."""
        mvar = MarginalVaR(
            strategy_id="s1",
            marginal_var_95=Decimal("15000"),
            marginal_var_99=Decimal("25000"),
            pct_contribution=0.60,
        )
        assert mvar.pct_contribution == 0.60

    def test_correlation_matrix_valid(self) -> None:
        """CorrelationMatrix builds with valid data."""
        corr = CorrelationMatrix(
            portfolio_id="pf-001",
            strategy_ids=["s1", "s2"],
            matrix=[[1.0, 0.3], [0.3, 1.0]],
        )
        assert len(corr.matrix) == 2

    def test_drawdown_sync_event_valid(self) -> None:
        """DrawdownSyncEvent builds with valid data."""
        event = DrawdownSyncEvent(
            portfolio_id="pf-001",
            strategy_ids=["s1", "s2"],
            avg_drawdown=0.08,
            max_drawdown=0.12,
        )
        assert event.avg_drawdown == 0.08

    def test_optimization_suggestion_valid(self) -> None:
        """OptimizationSuggestion builds with valid data."""
        suggestion = OptimizationSuggestion(
            portfolio_id="pf-001",
            suggested_weights={"s1": 0.6, "s2": 0.4},
            expected_return=0.15,
            expected_volatility=0.12,
            sharpe_ratio=1.25,
        )
        assert suggestion.sharpe_ratio == 1.25


# ===========================================================================
# Test: Portfolio VaR
# ===========================================================================


class TestPortfolioVaR:
    """Verify portfolio VaR computation."""

    def test_var_positive(self) -> None:
        """Portfolio VaR is positive (represents potential loss)."""
        config = _make_portfolio_config()
        performances = [
            _make_performance("s1", "d1"),
            _make_performance("s2", "d2"),
        ]

        service = _build_service()
        var = service.compute_portfolio_var(config, performances)

        assert var.var_95 > 0
        assert var.var_99 > 0

    def test_var_99_greater_than_var_95(self) -> None:
        """99% VaR ≥ 95% VaR (higher confidence = more extreme loss)."""
        config = _make_portfolio_config()
        performances = [
            _make_performance("s1", "d1"),
            _make_performance("s2", "d2"),
        ]

        service = _build_service()
        var = service.compute_portfolio_var(config, performances)

        assert var.var_99 >= var.var_95

    def test_var_portfolio_id_preserved(self) -> None:
        """VaR result contains the correct portfolio_id."""
        config = _make_portfolio_config()
        performances = [
            _make_performance("s1", "d1"),
            _make_performance("s2", "d2"),
        ]

        service = _build_service()
        var = service.compute_portfolio_var(config, performances)

        assert var.portfolio_id == "pf-test"

    def test_var_diversification_benefit(self) -> None:
        """Portfolio VaR is less than sum of individual VaRs when not perfectly correlated."""
        config = _make_portfolio_config()
        # Different return seeds = different strategies = imperfect correlation
        performances = [
            _make_performance("s1", "d1", current_equity=Decimal("500000")),
            _make_performance("s2", "d2", current_equity=Decimal("500000")),
        ]

        service = _build_service()
        portfolio_var = service.compute_portfolio_var(config, performances)

        # Compute individual VaRs
        config_s1 = _make_portfolio_config(strategy_configs=[_make_strategy_config("s1")])
        var_s1 = service.compute_portfolio_var(config_s1, [performances[0]])

        config_s2 = _make_portfolio_config(strategy_configs=[_make_strategy_config("s2")])
        var_s2 = service.compute_portfolio_var(config_s2, [performances[1]])

        # Diversification: portfolio VaR ≤ sum of individual VaRs
        assert portfolio_var.var_95 <= var_s1.var_95 + var_s2.var_95


# ===========================================================================
# Test: Marginal VaR
# ===========================================================================


class TestMarginalVaR:
    """Verify marginal VaR decomposition."""

    def test_marginal_var_per_strategy(self) -> None:
        """Marginal VaR has entry for each strategy."""
        config = _make_portfolio_config()
        performances = [
            _make_performance("s1", "d1"),
            _make_performance("s2", "d2"),
        ]

        service = _build_service()
        result = service.compute_marginal_var(config, performances)

        assert len(result.marginal_vars) == 2
        strategy_ids = {mv.strategy_id for mv in result.marginal_vars}
        assert strategy_ids == {"s1", "s2"}

    def test_marginal_var_contributions_sum_close_to_total(self) -> None:
        """Marginal VaR contributions approximately sum to total portfolio VaR."""
        config = _make_portfolio_config()
        performances = [
            _make_performance("s1", "d1"),
            _make_performance("s2", "d2"),
        ]

        service = _build_service()
        result = service.compute_marginal_var(config, performances)

        total_contributions = sum(mv.pct_contribution for mv in result.marginal_vars)
        # Contributions should approximately sum to 1.0
        assert abs(total_contributions - 1.0) < 0.15


# ===========================================================================
# Test: Correlation Matrix
# ===========================================================================


class TestCorrelationMatrix:
    """Verify strategy correlation matrix computation."""

    def test_correlation_matrix_shape(self) -> None:
        """Correlation matrix is N×N where N = number of strategies."""
        config = _make_portfolio_config()
        performances = [
            _make_performance("s1", "d1"),
            _make_performance("s2", "d2"),
        ]

        service = _build_service()
        corr = service.compute_correlation_matrix(config, performances)

        assert len(corr.matrix) == 2
        assert len(corr.matrix[0]) == 2

    def test_correlation_diagonal_is_one(self) -> None:
        """Diagonal elements are 1.0 (self-correlation)."""
        config = _make_portfolio_config()
        performances = [
            _make_performance("s1", "d1"),
            _make_performance("s2", "d2"),
        ]

        service = _build_service()
        corr = service.compute_correlation_matrix(config, performances)

        for i in range(len(corr.matrix)):
            assert abs(corr.matrix[i][i] - 1.0) < 1e-9

    def test_correlation_symmetric(self) -> None:
        """Correlation matrix is symmetric."""
        configs = [
            _make_strategy_config("s1"),
            _make_strategy_config("s2"),
            _make_strategy_config("s3"),
        ]
        config = _make_portfolio_config(strategy_configs=configs)
        performances = [
            _make_performance("s1", "d1"),
            _make_performance("s2", "d2"),
            _make_performance("s3", "d3"),
        ]

        service = _build_service()
        corr = service.compute_correlation_matrix(config, performances)

        n = len(corr.matrix)
        for i in range(n):
            for j in range(n):
                assert abs(corr.matrix[i][j] - corr.matrix[j][i]) < 1e-9

    def test_high_correlation_pairs_detected(self) -> None:
        """Strategies with identical returns → flagged as high correlation."""
        config = _make_portfolio_config()
        # Same returns = perfect correlation
        shared_returns = [0.01, -0.005, 0.008, -0.003, 0.012] * 12
        performances = [
            _make_performance("s1", "d1", returns=shared_returns),
            _make_performance("s2", "d2", returns=shared_returns),
        ]

        service = _build_service()
        corr = service.compute_correlation_matrix(config, performances)

        assert len(corr.high_correlation_pairs) > 0
        pair = corr.high_correlation_pairs[0]
        assert pair[2] > 0.80  # Correlation value


# ===========================================================================
# Test: Drawdown Synchronization
# ===========================================================================


class TestDrawdownSync:
    """Verify drawdown synchronization detection."""

    def test_sync_detected_when_both_strategies_down(self) -> None:
        """Two strategies both in drawdown → sync event detected."""
        config = _make_portfolio_config()
        performances = [
            _make_performance("s1", "d1", max_drawdown=0.10),
            _make_performance("s2", "d2", max_drawdown=0.08),
        ]

        service = _build_service()
        events = service.detect_drawdown_sync(config, performances, drawdown_threshold=0.05)

        assert len(events) >= 1
        assert len(events[0].strategy_ids) == 2

    def test_no_sync_when_one_strategy_ok(self) -> None:
        """Only one strategy in drawdown → no sync event."""
        config = _make_portfolio_config()
        performances = [
            _make_performance("s1", "d1", max_drawdown=0.10),
            _make_performance("s2", "d2", max_drawdown=0.02),
        ]

        service = _build_service()
        events = service.detect_drawdown_sync(config, performances, drawdown_threshold=0.05)

        assert len(events) == 0

    def test_sync_avg_drawdown_computed(self) -> None:
        """Sync event has correct average drawdown."""
        config = _make_portfolio_config()
        performances = [
            _make_performance("s1", "d1", max_drawdown=0.10),
            _make_performance("s2", "d2", max_drawdown=0.20),
        ]

        service = _build_service()
        events = service.detect_drawdown_sync(config, performances, drawdown_threshold=0.05)

        assert len(events) == 1
        assert abs(events[0].avg_drawdown - 0.15) < 1e-9


# ===========================================================================
# Test: Optimization
# ===========================================================================


class TestOptimization:
    """Verify capital optimization suggestions."""

    def test_optimization_suggests_weights(self) -> None:
        """Optimization produces weight suggestions for all strategies."""
        config = _make_portfolio_config()
        performances = [
            _make_performance("s1", "d1"),
            _make_performance("s2", "d2"),
        ]

        service = _build_service()
        suggestion = service.suggest_optimization(config, performances)

        assert "s1" in suggestion.suggested_weights
        assert "s2" in suggestion.suggested_weights

    def test_optimization_weights_sum_to_one(self) -> None:
        """Suggested weights sum to approximately 1.0."""
        config = _make_portfolio_config()
        performances = [
            _make_performance("s1", "d1"),
            _make_performance("s2", "d2"),
        ]

        service = _build_service()
        suggestion = service.suggest_optimization(config, performances)

        total = sum(suggestion.suggested_weights.values())
        assert abs(total - 1.0) < 0.01

    def test_optimization_positive_sharpe(self) -> None:
        """Expected Sharpe from optimization is non-negative.

        Uses explicit return series with clearly positive mean to avoid
        flakiness from hash-seeded RNG in _make_performance (Python
        randomises hash() per process, so default returns vary across runs).
        """
        # Deterministic returns with positive daily mean (~0.1% / day)
        pos_returns_s1 = [
            0.002,
            -0.001,
            0.003,
            0.001,
            -0.002,
            0.004,
            0.001,
            0.002,
            -0.001,
            0.003,
            0.002,
            0.001,
            -0.001,
            0.003,
            0.001,
            0.002,
            -0.001,
            0.003,
            0.001,
            0.002,
        ] * 3  # 60 pts
        pos_returns_s2 = [
            0.001,
            0.002,
            -0.001,
            0.003,
            0.001,
            -0.002,
            0.004,
            0.001,
            0.002,
            -0.001,
            0.002,
            0.003,
            0.001,
            -0.001,
            0.002,
            0.001,
            0.003,
            -0.001,
            0.002,
            0.001,
        ] * 3

        config = _make_portfolio_config()
        performances = [
            _make_performance("s1", "d1", returns=pos_returns_s1),
            _make_performance("s2", "d2", returns=pos_returns_s2),
        ]

        service = _build_service()
        suggestion = service.suggest_optimization(config, performances)

        # With clearly positive expected returns, Sharpe should be non-negative
        assert suggestion.sharpe_ratio >= 0


# ===========================================================================
# Test: Edge Cases
# ===========================================================================


class TestEdgeCases:
    """Verify edge case handling."""

    def test_single_strategy_var(self) -> None:
        """Single strategy VaR works."""
        configs = [_make_strategy_config("s1")]
        config = _make_portfolio_config(strategy_configs=configs)
        performances = [_make_performance("s1", "d1")]

        service = _build_service()
        var = service.compute_portfolio_var(config, performances)

        assert var.var_95 > 0

    def test_single_strategy_correlation(self) -> None:
        """Single strategy → 1x1 correlation matrix with self-correlation = 1.0."""
        configs = [_make_strategy_config("s1")]
        config = _make_portfolio_config(strategy_configs=configs)
        performances = [_make_performance("s1", "d1")]

        service = _build_service()
        corr = service.compute_correlation_matrix(config, performances)

        assert len(corr.matrix) == 1
        assert abs(corr.matrix[0][0] - 1.0) < 1e-9

    def test_single_strategy_no_drawdown_sync(self) -> None:
        """Single strategy → no sync events possible."""
        configs = [_make_strategy_config("s1")]
        config = _make_portfolio_config(strategy_configs=configs)
        performances = [_make_performance("s1", "d1", max_drawdown=0.15)]

        service = _build_service()
        events = service.detect_drawdown_sync(config, performances, drawdown_threshold=0.05)

        assert len(events) == 0
