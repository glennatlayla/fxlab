"""
Unit tests for Monte Carlo simulation contracts and engine (M11).

Tests cover:
1. Contract validation — config, result, enum.
2. Deterministic seed reproducibility — same seed → same output.
3. Distribution shape — confidence interval ordering (p5 < p50 < p95).
4. Trade resampling — shuffled trade sequence produces equity distribution.
5. Return bootstrapping — resampled returns produce equity distribution.
6. Ruin probability calculation — fraction below threshold.
7. Edge cases — zero trades, single trade, all winners, all losers.

Follows §5 TDD naming: test_<unit>_<scenario>_<expected_outcome>
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal

from libs.contracts.backtest import (
    BacktestConfig,
    BacktestInterval,
    BacktestResult,
    BacktestSignalSummary,
    BacktestTrade,
)
from libs.contracts.monte_carlo import (
    MonteCarloConfig,
    MonteCarloResult,
    SimulationMethod,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_trade(
    symbol: str = "AAPL",
    side: str = "buy",
    quantity: Decimal = Decimal("100"),
    price: Decimal = Decimal("100"),
    commission: Decimal = Decimal("0"),
) -> BacktestTrade:
    """Build a BacktestTrade for testing."""
    return BacktestTrade(
        timestamp=datetime(2025, 6, 15, 16, 0, tzinfo=timezone.utc),
        symbol=symbol,
        side=side,
        quantity=quantity,
        price=price,
        commission=commission,
        slippage=Decimal("0"),
    )


def _make_backtest_result(
    trades: list[BacktestTrade] | None = None,
    initial_equity: Decimal = Decimal("100000"),
    final_equity: Decimal = Decimal("110000"),
) -> BacktestResult:
    """Build a BacktestResult for Monte Carlo testing."""
    config = BacktestConfig(
        strategy_id="test-mc",
        symbols=["AAPL"],
        start_date=date(2025, 1, 1),
        end_date=date(2025, 12, 31),
        interval=BacktestInterval.ONE_DAY,
        initial_equity=initial_equity,
    )
    return BacktestResult(
        config=config,
        total_return_pct=Decimal("10"),
        final_equity=final_equity,
        total_trades=len(trades or []),
        trades=trades or [],
        bars_processed=252,
        signal_summary=BacktestSignalSummary(
            signals_generated=len(trades or []),
            signals_approved=len(trades or []),
        ),
    )


def _make_round_trip_trades(
    buy_price: Decimal = Decimal("100"),
    sell_price: Decimal = Decimal("110"),
    n_trips: int = 10,
) -> list[BacktestTrade]:
    """Build N buy-sell round trip trade pairs."""
    trades = []
    for _ in range(n_trips):
        trades.append(_make_trade(side="buy", price=buy_price))
        trades.append(_make_trade(side="sell", price=sell_price))
    return trades


def _build_engine():
    """Build a MonteCarloEngine."""
    from services.worker.research.monte_carlo_engine import MonteCarloEngine

    return MonteCarloEngine()


# ===========================================================================
# Test: Contract Validation
# ===========================================================================


class TestMonteCarloContracts:
    """Verify Monte Carlo contract validation."""

    def test_config_defaults(self) -> None:
        """Default config has expected values."""
        config = MonteCarloConfig()
        assert config.num_simulations == 10000
        assert config.method == SimulationMethod.TRADE_RESAMPLE
        assert 0.05 in config.confidence_levels
        assert config.ruin_threshold == 0.50

    def test_config_frozen(self) -> None:
        """Config is immutable."""
        config = MonteCarloConfig()
        try:
            config.num_simulations = 500  # type: ignore[misc]
            raise AssertionError("Should have raised")
        except (TypeError, ValueError, AttributeError):
            pass

    def test_simulation_method_enum(self) -> None:
        """Both simulation methods are defined."""
        assert SimulationMethod.TRADE_RESAMPLE.value == "trade_resample"
        assert SimulationMethod.RETURN_BOOTSTRAP.value == "return_bootstrap"

    def test_result_valid(self) -> None:
        """MonteCarloResult builds with valid data."""
        config = MonteCarloConfig()
        result = MonteCarloResult(
            config=config,
            num_trades=20,
            equity_percentiles={"p50": 110000.0},
            probability_of_ruin=0.05,
            mean_final_equity=110000.0,
            median_final_equity=109500.0,
        )
        assert result.probability_of_ruin == 0.05

    def test_config_with_seed(self) -> None:
        """Config with random seed for reproducibility."""
        config = MonteCarloConfig(random_seed=42)
        assert config.random_seed == 42


# ===========================================================================
# Test: Deterministic Seed Reproducibility
# ===========================================================================


class TestReproducibility:
    """Verify deterministic output with same seed."""

    def test_same_seed_same_result(self) -> None:
        """Two runs with same seed produce identical results."""
        trades = _make_round_trip_trades(n_trips=10)
        bt_result = _make_backtest_result(trades=trades)
        config = MonteCarloConfig(num_simulations=500, random_seed=42)

        engine = _build_engine()
        result1 = engine.run(bt_result, config)
        result2 = engine.run(bt_result, config)

        assert result1.mean_final_equity == result2.mean_final_equity
        assert result1.probability_of_ruin == result2.probability_of_ruin
        assert result1.equity_percentiles == result2.equity_percentiles

    def test_different_seed_different_result(self) -> None:
        """Two runs with different seeds produce different results (high probability).

        Uses RETURN_BOOTSTRAP with varied P&Ls so resampling with replacement
        creates different trade sequences (and therefore different mean equities).
        Trade resampling (permutation) preserves the sum, so identical P&Ls would
        always yield the same mean — bootstrap avoids this by sampling with replacement.
        """
        # Build trades with varied P&Ls: mix of winners and losers
        trades = []
        sell_prices = [
            Decimal("120"),
            Decimal("105"),
            Decimal("80"),
            Decimal("130"),
            Decimal("90"),
            Decimal("115"),
            Decimal("70"),
            Decimal("140"),
            Decimal("95"),
            Decimal("110"),
            Decimal("85"),
            Decimal("125"),
            Decimal("60"),
            Decimal("150"),
            Decimal("100"),
            Decimal("135"),
            Decimal("75"),
            Decimal("145"),
            Decimal("88"),
            Decimal("112"),
        ]
        for sp in sell_prices:
            trades.append(_make_trade(side="buy", price=Decimal("100")))
            trades.append(_make_trade(side="sell", price=sp))
        bt_result = _make_backtest_result(trades=trades)

        engine = _build_engine()
        result1 = engine.run(
            bt_result,
            MonteCarloConfig(
                num_simulations=500,
                method=SimulationMethod.RETURN_BOOTSTRAP,
                random_seed=1,
            ),
        )
        result2 = engine.run(
            bt_result,
            MonteCarloConfig(
                num_simulations=500,
                method=SimulationMethod.RETURN_BOOTSTRAP,
                random_seed=99,
            ),
        )

        # With replacement sampling of varied P&Ls: very unlikely to be identical
        assert result1.mean_final_equity != result2.mean_final_equity


# ===========================================================================
# Test: Confidence Interval Ordering
# ===========================================================================


class TestConfidenceIntervals:
    """Verify confidence interval structure."""

    def test_equity_percentiles_ordered(self) -> None:
        """Lower percentiles ≤ higher percentiles."""
        trades = _make_round_trip_trades(n_trips=20)
        bt_result = _make_backtest_result(trades=trades)
        config = MonteCarloConfig(
            num_simulations=500,
            random_seed=42,
            confidence_levels=[0.05, 0.25, 0.50, 0.75, 0.95],
        )

        engine = _build_engine()
        result = engine.run(bt_result, config)

        assert result.equity_percentiles["p5"] <= result.equity_percentiles["p50"]
        assert result.equity_percentiles["p50"] <= result.equity_percentiles["p95"]

    def test_all_confidence_levels_present(self) -> None:
        """All configured confidence levels appear in output."""
        trades = _make_round_trip_trades(n_trips=10)
        bt_result = _make_backtest_result(trades=trades)
        config = MonteCarloConfig(
            num_simulations=500,
            random_seed=42,
            confidence_levels=[0.05, 0.50, 0.95],
        )

        engine = _build_engine()
        result = engine.run(bt_result, config)

        assert "p5" in result.equity_percentiles
        assert "p50" in result.equity_percentiles
        assert "p95" in result.equity_percentiles

    def test_drawdown_percentiles_populated(self) -> None:
        """Max drawdown percentiles are populated."""
        trades = _make_round_trip_trades(n_trips=10)
        bt_result = _make_backtest_result(trades=trades)
        config = MonteCarloConfig(num_simulations=500, random_seed=42)

        engine = _build_engine()
        result = engine.run(bt_result, config)

        assert len(result.max_drawdown_percentiles) > 0


# ===========================================================================
# Test: Ruin Probability
# ===========================================================================


class TestRuinProbability:
    """Verify probability of ruin calculations."""

    def test_ruin_probability_in_range(self) -> None:
        """Ruin probability is between 0 and 1."""
        trades = _make_round_trip_trades(n_trips=10)
        bt_result = _make_backtest_result(trades=trades)
        config = MonteCarloConfig(num_simulations=500, random_seed=42)

        engine = _build_engine()
        result = engine.run(bt_result, config)

        assert 0.0 <= result.probability_of_ruin <= 1.0

    def test_all_winners_low_ruin(self) -> None:
        """All winning trades → low ruin probability."""
        trades = _make_round_trip_trades(
            buy_price=Decimal("100"),
            sell_price=Decimal("110"),
            n_trips=20,
        )
        bt_result = _make_backtest_result(trades=trades, final_equity=Decimal("120000"))
        config = MonteCarloConfig(
            num_simulations=500,
            random_seed=42,
            ruin_threshold=0.50,
        )

        engine = _build_engine()
        result = engine.run(bt_result, config)

        # All winners: very low ruin probability
        assert result.probability_of_ruin < 0.10

    def test_all_losers_high_ruin(self) -> None:
        """All losing trades → higher ruin probability."""
        trades = _make_round_trip_trades(
            buy_price=Decimal("110"),
            sell_price=Decimal("50"),
            n_trips=20,
        )
        bt_result = _make_backtest_result(trades=trades, final_equity=Decimal("50000"))
        config = MonteCarloConfig(
            num_simulations=500,
            random_seed=42,
            ruin_threshold=0.50,
        )

        engine = _build_engine()
        result = engine.run(bt_result, config)

        # All losers: high ruin
        assert result.probability_of_ruin > 0.50


# ===========================================================================
# Test: Simulation Methods
# ===========================================================================


class TestSimulationMethods:
    """Verify both simulation methods work."""

    def test_trade_resample_method(self) -> None:
        """Trade resample method produces results."""
        trades = _make_round_trip_trades(n_trips=10)
        bt_result = _make_backtest_result(trades=trades)
        config = MonteCarloConfig(
            num_simulations=500,
            method=SimulationMethod.TRADE_RESAMPLE,
            random_seed=42,
        )

        engine = _build_engine()
        result = engine.run(bt_result, config)

        assert result.mean_final_equity > 0
        assert result.num_trades == len(trades)

    def test_return_bootstrap_method(self) -> None:
        """Return bootstrap method produces results."""
        trades = _make_round_trip_trades(n_trips=10)
        bt_result = _make_backtest_result(trades=trades)
        config = MonteCarloConfig(
            num_simulations=500,
            method=SimulationMethod.RETURN_BOOTSTRAP,
            random_seed=42,
        )

        engine = _build_engine()
        result = engine.run(bt_result, config)

        assert result.mean_final_equity > 0


# ===========================================================================
# Test: Edge Cases
# ===========================================================================


class TestEdgeCases:
    """Verify edge case handling."""

    def test_zero_trades_returns_initial_equity(self) -> None:
        """Zero trades → all simulations return initial equity."""
        bt_result = _make_backtest_result(trades=[], final_equity=Decimal("100000"))
        config = MonteCarloConfig(num_simulations=500, random_seed=42)

        engine = _build_engine()
        result = engine.run(bt_result, config)

        assert result.mean_final_equity == 100000.0
        assert result.num_trades == 0

    def test_single_trade_no_crash(self) -> None:
        """Single trade doesn't crash the engine."""
        trades = [_make_trade(side="buy", price=Decimal("100"))]
        bt_result = _make_backtest_result(trades=trades)
        config = MonteCarloConfig(num_simulations=500, random_seed=42)

        engine = _build_engine()
        result = engine.run(bt_result, config)

        assert isinstance(result, MonteCarloResult)

    def test_completed_at_is_utc(self) -> None:
        """completed_at is timezone-aware UTC."""
        trades = _make_round_trip_trades(n_trips=5)
        bt_result = _make_backtest_result(trades=trades)
        config = MonteCarloConfig(num_simulations=500, random_seed=42)

        engine = _build_engine()
        result = engine.run(bt_result, config)

        assert result.completed_at.tzinfo is not None

    def test_config_preserved(self) -> None:
        """Result contains the original config."""
        trades = _make_round_trip_trades(n_trips=5)
        bt_result = _make_backtest_result(trades=trades)
        config = MonteCarloConfig(num_simulations=500, random_seed=42)

        engine = _build_engine()
        result = engine.run(bt_result, config)

        assert result.config == config

    def test_mean_and_median_populated(self) -> None:
        """Mean and median final equity are populated."""
        trades = _make_round_trip_trades(n_trips=10)
        bt_result = _make_backtest_result(trades=trades)
        config = MonteCarloConfig(num_simulations=500, random_seed=42)

        engine = _build_engine()
        result = engine.run(bt_result, config)

        assert result.mean_final_equity > 0
        assert result.median_final_equity > 0
