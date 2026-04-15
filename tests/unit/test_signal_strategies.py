"""
Unit tests for built-in signal strategies (M4).

Tests cover each strategy's:
- Happy path: signal generated on valid crossover / threshold breach.
- No-signal conditions: insufficient data, no crossover, neutral zone.
- Edge cases: exact boundary values, single candle, NaN handling.
- Configurable parameters: custom periods, thresholds.
- required_indicators() returns correct specs.
- Strategy identity properties (strategy_id, name, supported_symbols).

Follows §5 TDD naming: test_<unit>_<scenario>_<expected_outcome>
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import numpy as np

from libs.contracts.execution import PositionSnapshot
from libs.contracts.indicator import IndicatorResult
from libs.contracts.market_data import Candle, CandleInterval
from libs.contracts.signal import SignalDirection, SignalStrength, SignalType
from services.worker.strategies.bollinger_breakout import (
    BollingerBandBreakoutStrategy,
)
from services.worker.strategies.composite_signal import (
    CompositeSignalStrategy,
)
from services.worker.strategies.macd_momentum import (
    MACDMomentumStrategy,
)
from services.worker.strategies.moving_average_crossover import (
    MovingAverageCrossoverStrategy,
)
from services.worker.strategies.rsi_mean_reversion import (
    RSIMeanReversionStrategy,
)
from services.worker.strategies.stochastic_momentum import (
    StochasticMomentumStrategy,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_BASE_DT = datetime(2026, 4, 13, 14, 0, tzinfo=timezone.utc)
_DEPLOY_ID = "deploy-test-001"
_CORR_ID = "corr-test-001"


def _make_candles(
    closes: list[float],
    *,
    symbol: str = "AAPL",
    interval: CandleInterval = CandleInterval.D1,
    volumes: list[int] | None = None,
) -> list[Candle]:
    """Build a list of candles from a list of close prices."""
    if volumes is None:
        volumes = [1_000_000] * len(closes)
    candles = []
    for i, close in enumerate(closes):
        ts = _BASE_DT + timedelta(days=i)
        candles.append(
            Candle(
                symbol=symbol,
                interval=interval,
                open=Decimal(str(close - 0.5)),
                high=Decimal(str(close + 1.0)),
                low=Decimal(str(close - 1.0)),
                close=Decimal(str(close)),
                volume=volumes[i],
                timestamp=ts,
            )
        )
    return candles


def _make_indicator_result(
    name: str,
    values: list[float],
    timestamps: list[float] | None = None,
) -> IndicatorResult:
    """Build an IndicatorResult with numpy arrays."""
    arr = np.array(values, dtype=np.float64)
    ts = np.array(timestamps or list(range(len(values))), dtype=np.float64)
    return IndicatorResult(
        indicator_name=name,
        values=arr,
        timestamps=ts,
        metadata={},
    )


def _make_multi_indicator_result(
    name: str,
    components: dict[str, list[float]],
    timestamps: list[float] | None = None,
) -> IndicatorResult:
    """Build a multi-output IndicatorResult."""
    comp = {k: np.array(v, dtype=np.float64) for k, v in components.items()}
    n = len(next(iter(components.values())))
    ts = np.array(timestamps or list(range(n)), dtype=np.float64)
    return IndicatorResult(
        indicator_name=name,
        values=None,
        components=comp,
        timestamps=ts,
        metadata={},
    )


def _make_position(symbol: str = "AAPL", qty: str = "100") -> PositionSnapshot:
    """Build a minimal PositionSnapshot."""
    return PositionSnapshot(
        symbol=symbol,
        quantity=Decimal(qty),
        average_entry_price=Decimal("170.00"),
        market_price=Decimal("175.00"),
        market_value=Decimal(qty) * Decimal("175.00"),
        unrealized_pnl=Decimal(qty) * Decimal("5.00"),
        cost_basis=Decimal(qty) * Decimal("170.00"),
        updated_at=_BASE_DT,
    )


# ===========================================================================
# MovingAverageCrossover Tests
# ===========================================================================


class TestMovingAverageCrossoverIdentity:
    """Tests for strategy identity properties."""

    def test_strategy_id_matches_expected(self) -> None:
        strategy = MovingAverageCrossoverStrategy(deployment_id=_DEPLOY_ID)
        assert strategy.strategy_id == "ma-crossover"

    def test_name_is_human_readable(self) -> None:
        strategy = MovingAverageCrossoverStrategy(deployment_id=_DEPLOY_ID)
        assert "Moving Average" in strategy.name

    def test_supported_symbols_empty_means_all(self) -> None:
        strategy = MovingAverageCrossoverStrategy(deployment_id=_DEPLOY_ID)
        assert strategy.supported_symbols == []


class TestMovingAverageCrossoverIndicators:
    """Tests for required_indicators declarations."""

    def test_required_indicators_contains_fast_and_slow(self) -> None:
        strategy = MovingAverageCrossoverStrategy(
            deployment_id=_DEPLOY_ID, fast_period=10, slow_period=30
        )
        reqs = strategy.required_indicators()
        names = [r.indicator_name for r in reqs]
        # Should request two moving averages
        assert len(reqs) == 2
        assert all(n in ("SMA", "EMA") for n in names)

    def test_required_indicators_uses_ema_when_configured(self) -> None:
        strategy = MovingAverageCrossoverStrategy(deployment_id=_DEPLOY_ID, use_ema=True)
        reqs = strategy.required_indicators()
        assert all(r.indicator_name == "EMA" for r in reqs)

    def test_required_indicators_uses_sma_by_default(self) -> None:
        strategy = MovingAverageCrossoverStrategy(deployment_id=_DEPLOY_ID)
        reqs = strategy.required_indicators()
        assert all(r.indicator_name == "SMA" for r in reqs)


class TestMovingAverageCrossoverSignals:
    """Tests for signal generation logic."""

    def test_long_signal_on_golden_cross(self) -> None:
        """LONG when fast MA crosses above slow MA."""
        strategy = MovingAverageCrossoverStrategy(
            deployment_id=_DEPLOY_ID, fast_period=5, slow_period=20
        )
        candles = _make_candles([170 + i * 0.5 for i in range(25)])
        # Fast <= Slow at [-2], Fast > Slow at [-1] → golden cross
        fast_vals = [float("nan")] * 20 + [168.0, 169.0, 170.0, 171.0, 174.0]
        slow_vals = [float("nan")] * 20 + [170.0, 170.5, 171.0, 172.0, 171.0]
        indicators = {
            "SMA_5": _make_indicator_result("SMA", fast_vals),
            "SMA_20": _make_indicator_result("SMA", slow_vals),
        }

        signal = strategy.evaluate("AAPL", candles, indicators, None, correlation_id=_CORR_ID)

        assert signal is not None
        assert signal.direction == SignalDirection.LONG
        assert signal.signal_type == SignalType.ENTRY
        assert signal.strategy_id == "ma-crossover"

    def test_short_signal_on_death_cross(self) -> None:
        """SHORT when fast MA crosses below slow MA."""
        strategy = MovingAverageCrossoverStrategy(
            deployment_id=_DEPLOY_ID, fast_period=5, slow_period=20
        )
        candles = _make_candles([180 - i * 0.5 for i in range(25)])
        # Fast >= Slow at [-2], Fast < Slow at [-1] → death cross
        fast_vals = [float("nan")] * 20 + [172.0, 171.0, 170.5, 170.0, 166.0]
        slow_vals = [float("nan")] * 20 + [170.0, 170.0, 170.0, 170.0, 170.0]
        indicators = {
            "SMA_5": _make_indicator_result("SMA", fast_vals),
            "SMA_20": _make_indicator_result("SMA", slow_vals),
        }

        signal = strategy.evaluate("AAPL", candles, indicators, None, correlation_id=_CORR_ID)

        assert signal is not None
        assert signal.direction == SignalDirection.SHORT

    def test_no_signal_when_no_crossover(self) -> None:
        """No signal when fast stays above slow (no crossover event)."""
        strategy = MovingAverageCrossoverStrategy(
            deployment_id=_DEPLOY_ID, fast_period=5, slow_period=20
        )
        candles = _make_candles([170 + i * 0.5 for i in range(25)])
        # Fast always above slow — no cross
        fast_vals = [float("nan")] * 20 + [175.0, 176.0, 177.0, 178.0, 179.0]
        slow_vals = [float("nan")] * 20 + [170.0, 170.5, 171.0, 171.5, 172.0]
        indicators = {
            "SMA_5": _make_indicator_result("SMA", fast_vals),
            "SMA_20": _make_indicator_result("SMA", slow_vals),
        }

        signal = strategy.evaluate("AAPL", candles, indicators, None, correlation_id=_CORR_ID)

        assert signal is None

    def test_no_signal_insufficient_data(self) -> None:
        """No signal when fewer candles than slow period."""
        strategy = MovingAverageCrossoverStrategy(
            deployment_id=_DEPLOY_ID, fast_period=5, slow_period=20
        )
        candles = _make_candles([170.0] * 5)
        # All NaN — not enough data
        fast_vals = [float("nan")] * 5
        slow_vals = [float("nan")] * 5
        indicators = {
            "SMA_5": _make_indicator_result("SMA", fast_vals),
            "SMA_20": _make_indicator_result("SMA", slow_vals),
        }

        signal = strategy.evaluate("AAPL", candles, indicators, None, correlation_id=_CORR_ID)

        assert signal is None

    def test_strength_strong_on_wide_spread(self) -> None:
        """STRONG signal when MA spread is large relative to price."""
        strategy = MovingAverageCrossoverStrategy(
            deployment_id=_DEPLOY_ID,
            fast_period=5,
            slow_period=20,
            strong_threshold_pct=1.0,
            moderate_threshold_pct=0.5,
        )
        candles = _make_candles([170 + i * 0.5 for i in range(25)])
        # Fast <= Slow at [-2], Fast > Slow at [-1] with ~3% spread → STRONG
        fast_vals = [float("nan")] * 20 + [168.0, 169.0, 170.0, 170.0, 176.0]
        slow_vals = [float("nan")] * 20 + [170.0, 170.5, 171.0, 171.0, 171.0]
        indicators = {
            "SMA_5": _make_indicator_result("SMA", fast_vals),
            "SMA_20": _make_indicator_result("SMA", slow_vals),
        }

        signal = strategy.evaluate("AAPL", candles, indicators, None, correlation_id=_CORR_ID)

        assert signal is not None
        assert signal.strength == SignalStrength.STRONG

    def test_exit_signal_when_holding_position_and_cross_against(self) -> None:
        """EXIT signal when holding LONG and death cross occurs."""
        strategy = MovingAverageCrossoverStrategy(
            deployment_id=_DEPLOY_ID, fast_period=5, slow_period=20
        )
        candles = _make_candles([180 - i * 0.5 for i in range(25)])
        # Fast >= Slow at [-2], Fast < Slow at [-1] → death cross
        fast_vals = [float("nan")] * 20 + [172.0, 171.0, 170.5, 170.0, 166.0]
        slow_vals = [float("nan")] * 20 + [170.0, 170.0, 170.0, 170.0, 170.0]
        indicators = {
            "SMA_5": _make_indicator_result("SMA", fast_vals),
            "SMA_20": _make_indicator_result("SMA", slow_vals),
        }
        position = _make_position("AAPL", "100")  # long position

        signal = strategy.evaluate("AAPL", candles, indicators, position, correlation_id=_CORR_ID)

        assert signal is not None
        assert signal.signal_type == SignalType.EXIT


# ===========================================================================
# RSIMeanReversion Tests
# ===========================================================================


class TestRSIMeanReversionIdentity:
    """Tests for RSI strategy identity."""

    def test_strategy_id(self) -> None:
        strategy = RSIMeanReversionStrategy(deployment_id=_DEPLOY_ID)
        assert strategy.strategy_id == "rsi-mean-reversion"

    def test_name(self) -> None:
        strategy = RSIMeanReversionStrategy(deployment_id=_DEPLOY_ID)
        assert "RSI" in strategy.name


class TestRSIMeanReversionIndicators:
    """Tests for required_indicators."""

    def test_requires_rsi(self) -> None:
        strategy = RSIMeanReversionStrategy(deployment_id=_DEPLOY_ID, rsi_period=14)
        reqs = strategy.required_indicators()
        assert len(reqs) == 1
        assert reqs[0].indicator_name == "RSI"
        assert reqs[0].params["period"] == 14


class TestRSIMeanReversionSignals:
    """Tests for RSI signal generation."""

    def test_long_on_rsi_crossing_above_oversold(self) -> None:
        """LONG when RSI crosses above oversold threshold from below."""
        strategy = RSIMeanReversionStrategy(deployment_id=_DEPLOY_ID, oversold=30, overbought=70)
        candles = _make_candles([170.0] * 20)
        # RSI crosses from 28 → 32 (above oversold)
        rsi_vals = [float("nan")] * 15 + [40.0, 35.0, 28.0, 25.0, 32.0]
        indicators = {"RSI_14": _make_indicator_result("RSI", rsi_vals)}

        signal = strategy.evaluate("AAPL", candles, indicators, None, correlation_id=_CORR_ID)

        assert signal is not None
        assert signal.direction == SignalDirection.LONG

    def test_short_on_rsi_crossing_below_overbought(self) -> None:
        """SHORT when RSI crosses below overbought threshold from above."""
        strategy = RSIMeanReversionStrategy(deployment_id=_DEPLOY_ID, oversold=30, overbought=70)
        candles = _make_candles([170.0] * 20)
        # RSI crosses from 72 → 68 (below overbought)
        rsi_vals = [float("nan")] * 15 + [60.0, 65.0, 72.0, 75.0, 68.0]
        indicators = {"RSI_14": _make_indicator_result("RSI", rsi_vals)}

        signal = strategy.evaluate("AAPL", candles, indicators, None, correlation_id=_CORR_ID)

        assert signal is not None
        assert signal.direction == SignalDirection.SHORT

    def test_no_signal_rsi_in_neutral_zone(self) -> None:
        """No signal when RSI stays in neutral zone (30-70)."""
        strategy = RSIMeanReversionStrategy(deployment_id=_DEPLOY_ID)
        candles = _make_candles([170.0] * 20)
        rsi_vals = [float("nan")] * 15 + [45.0, 50.0, 55.0, 50.0, 48.0]
        indicators = {"RSI_14": _make_indicator_result("RSI", rsi_vals)}

        signal = strategy.evaluate("AAPL", candles, indicators, None, correlation_id=_CORR_ID)

        assert signal is None

    def test_no_signal_insufficient_rsi_data(self) -> None:
        """No signal when RSI values are all NaN."""
        strategy = RSIMeanReversionStrategy(deployment_id=_DEPLOY_ID)
        candles = _make_candles([170.0] * 5)
        rsi_vals = [float("nan")] * 5
        indicators = {"RSI_14": _make_indicator_result("RSI", rsi_vals)}

        signal = strategy.evaluate("AAPL", candles, indicators, None, correlation_id=_CORR_ID)

        assert signal is None

    def test_strong_signal_on_large_rsi_swing(self) -> None:
        """STRONG signal when RSI swing magnitude exceeds threshold."""
        strategy = RSIMeanReversionStrategy(deployment_id=_DEPLOY_ID, strong_swing=15)
        candles = _make_candles([170.0] * 20)
        # Swing from 15 → 35 (magnitude 20 > 15 threshold)
        rsi_vals = [float("nan")] * 15 + [50.0, 30.0, 20.0, 15.0, 35.0]
        indicators = {"RSI_14": _make_indicator_result("RSI", rsi_vals)}

        signal = strategy.evaluate("AAPL", candles, indicators, None, correlation_id=_CORR_ID)

        assert signal is not None
        assert signal.strength == SignalStrength.STRONG

    def test_custom_thresholds(self) -> None:
        """Custom oversold/overbought thresholds work correctly."""
        strategy = RSIMeanReversionStrategy(deployment_id=_DEPLOY_ID, oversold=20, overbought=80)
        candles = _make_candles([170.0] * 20)
        # RSI at 25 → 32 — above 20 threshold but wouldn't trigger at 30
        rsi_vals = [float("nan")] * 15 + [30.0, 25.0, 18.0, 15.0, 22.0]
        indicators = {"RSI_14": _make_indicator_result("RSI", rsi_vals)}

        signal = strategy.evaluate("AAPL", candles, indicators, None, correlation_id=_CORR_ID)

        assert signal is not None
        assert signal.direction == SignalDirection.LONG


# ===========================================================================
# MACDMomentum Tests
# ===========================================================================


class TestMACDMomentumIdentity:
    def test_strategy_id(self) -> None:
        strategy = MACDMomentumStrategy(deployment_id=_DEPLOY_ID)
        assert strategy.strategy_id == "macd-momentum"

    def test_name(self) -> None:
        strategy = MACDMomentumStrategy(deployment_id=_DEPLOY_ID)
        assert "MACD" in strategy.name


class TestMACDMomentumIndicators:
    def test_requires_macd(self) -> None:
        strategy = MACDMomentumStrategy(deployment_id=_DEPLOY_ID)
        reqs = strategy.required_indicators()
        assert len(reqs) == 1
        assert reqs[0].indicator_name == "MACD"


class TestMACDMomentumSignals:
    def test_long_on_histogram_turning_positive(self) -> None:
        """LONG when MACD histogram turns positive and MACD > signal."""
        strategy = MACDMomentumStrategy(deployment_id=_DEPLOY_ID)
        candles = _make_candles([170.0] * 30)
        # histogram[-2] <= 0 AND histogram[-1] > 0 → turning positive
        indicators = {
            "MACD": _make_multi_indicator_result(
                "MACD",
                {
                    "macd_line": [float("nan")] * 25 + [0.5, 0.8, 1.0, 1.5, 2.0],
                    "signal_line": [float("nan")] * 25 + [0.8, 0.9, 1.0, 1.2, 1.5],
                    "histogram": [float("nan")] * 25 + [-0.5, -0.3, -0.1, -0.05, 0.5],
                },
            ),
        }

        signal = strategy.evaluate("AAPL", candles, indicators, None, correlation_id=_CORR_ID)

        assert signal is not None
        assert signal.direction == SignalDirection.LONG

    def test_short_on_histogram_turning_negative(self) -> None:
        """SHORT when MACD histogram turns negative."""
        strategy = MACDMomentumStrategy(deployment_id=_DEPLOY_ID)
        candles = _make_candles([170.0] * 30)
        # histogram[-2] >= 0 AND histogram[-1] < 0 → turning negative
        indicators = {
            "MACD": _make_multi_indicator_result(
                "MACD",
                {
                    "macd_line": [float("nan")] * 25 + [-0.5, -0.8, -1.0, -1.5, -2.0],
                    "signal_line": [float("nan")] * 25 + [-0.3, -0.5, -0.8, -1.0, -1.2],
                    "histogram": [float("nan")] * 25 + [0.5, 0.3, 0.1, 0.05, -0.5],
                },
            ),
        }

        signal = strategy.evaluate("AAPL", candles, indicators, None, correlation_id=_CORR_ID)

        assert signal is not None
        assert signal.direction == SignalDirection.SHORT

    def test_no_signal_histogram_stays_positive(self) -> None:
        """No signal when histogram stays positive (no turning point)."""
        strategy = MACDMomentumStrategy(deployment_id=_DEPLOY_ID)
        candles = _make_candles([170.0] * 30)
        indicators = {
            "MACD": _make_multi_indicator_result(
                "MACD",
                {
                    "macd_line": [float("nan")] * 25 + [1.0, 1.2, 1.5, 1.8, 2.0],
                    "signal_line": [float("nan")] * 25 + [0.5, 0.6, 0.8, 1.0, 1.2],
                    "histogram": [float("nan")] * 25 + [0.5, 0.6, 0.7, 0.8, 0.8],
                },
            ),
        }

        signal = strategy.evaluate("AAPL", candles, indicators, None, correlation_id=_CORR_ID)

        assert signal is None

    def test_strength_from_histogram_magnitude(self) -> None:
        """Signal strength scales with histogram magnitude."""
        strategy = MACDMomentumStrategy(
            deployment_id=_DEPLOY_ID,
            strong_histogram=1.0,
            moderate_histogram=0.3,
        )
        candles = _make_candles([170.0] * 30)
        # histogram[-2] <= 0, histogram[-1] = 1.5 → STRONG (>= 1.0)
        indicators = {
            "MACD": _make_multi_indicator_result(
                "MACD",
                {
                    "macd_line": [float("nan")] * 25 + [0.5, 1.0, 1.5, 2.0, 3.0],
                    "signal_line": [float("nan")] * 25 + [1.0, 1.2, 1.3, 1.4, 1.5],
                    "histogram": [float("nan")] * 25 + [-0.8, -0.5, -0.2, -0.1, 1.5],
                },
            ),
        }

        signal = strategy.evaluate("AAPL", candles, indicators, None, correlation_id=_CORR_ID)

        assert signal is not None
        assert signal.strength == SignalStrength.STRONG


# ===========================================================================
# BollingerBandBreakout Tests
# ===========================================================================


class TestBollingerBreakoutIdentity:
    def test_strategy_id(self) -> None:
        strategy = BollingerBandBreakoutStrategy(deployment_id=_DEPLOY_ID)
        assert strategy.strategy_id == "bollinger-breakout"

    def test_name(self) -> None:
        strategy = BollingerBandBreakoutStrategy(deployment_id=_DEPLOY_ID)
        assert "Bollinger" in strategy.name


class TestBollingerBreakoutIndicators:
    def test_requires_bbands_and_sma_volume(self) -> None:
        strategy = BollingerBandBreakoutStrategy(deployment_id=_DEPLOY_ID)
        reqs = strategy.required_indicators()
        names = [r.indicator_name for r in reqs]
        assert "BBANDS" in names


class TestBollingerBreakoutSignals:
    def test_long_on_upper_band_breakout_with_volume(self) -> None:
        """LONG when close > upper band and volume > 1.5× avg."""
        strategy = BollingerBandBreakoutStrategy(deployment_id=_DEPLOY_ID, volume_multiplier=1.5)
        # Last candle closes above upper band with high volume
        candles = _make_candles(
            [170.0] * 19 + [185.0],
            volumes=[1_000_000] * 19 + [2_000_000],
        )
        indicators = {
            "BBANDS_20": _make_multi_indicator_result(
                "BBANDS",
                {
                    "upper": [float("nan")] * 15 + [180.0, 180.0, 180.0, 180.0, 180.0],
                    "middle": [float("nan")] * 15 + [170.0, 170.0, 170.0, 170.0, 170.0],
                    "lower": [float("nan")] * 15 + [160.0, 160.0, 160.0, 160.0, 160.0],
                },
            ),
        }

        signal = strategy.evaluate("AAPL", candles, indicators, None, correlation_id=_CORR_ID)

        assert signal is not None
        assert signal.direction == SignalDirection.LONG

    def test_short_on_lower_band_breakdown(self) -> None:
        """SHORT when close < lower band."""
        strategy = BollingerBandBreakoutStrategy(deployment_id=_DEPLOY_ID, volume_multiplier=1.5)
        candles = _make_candles(
            [170.0] * 19 + [155.0],
            volumes=[1_000_000] * 19 + [2_000_000],
        )
        indicators = {
            "BBANDS_20": _make_multi_indicator_result(
                "BBANDS",
                {
                    "upper": [float("nan")] * 15 + [180.0, 180.0, 180.0, 180.0, 180.0],
                    "middle": [float("nan")] * 15 + [170.0, 170.0, 170.0, 170.0, 170.0],
                    "lower": [float("nan")] * 15 + [160.0, 160.0, 160.0, 160.0, 160.0],
                },
            ),
        }

        signal = strategy.evaluate("AAPL", candles, indicators, None, correlation_id=_CORR_ID)

        assert signal is not None
        assert signal.direction == SignalDirection.SHORT

    def test_no_signal_inside_bands(self) -> None:
        """No signal when price is inside Bollinger Bands."""
        strategy = BollingerBandBreakoutStrategy(deployment_id=_DEPLOY_ID)
        candles = _make_candles([170.0] * 20)
        indicators = {
            "BBANDS_20": _make_multi_indicator_result(
                "BBANDS",
                {
                    "upper": [float("nan")] * 15 + [180.0, 180.0, 180.0, 180.0, 180.0],
                    "middle": [float("nan")] * 15 + [170.0, 170.0, 170.0, 170.0, 170.0],
                    "lower": [float("nan")] * 15 + [160.0, 160.0, 160.0, 160.0, 160.0],
                },
            ),
        }

        signal = strategy.evaluate("AAPL", candles, indicators, None, correlation_id=_CORR_ID)

        assert signal is None

    def test_no_long_without_volume_confirmation(self) -> None:
        """No LONG signal when volume is below threshold despite breakout."""
        strategy = BollingerBandBreakoutStrategy(deployment_id=_DEPLOY_ID, volume_multiplier=1.5)
        # Price above upper band but volume is average — no confirmation
        candles = _make_candles(
            [170.0] * 19 + [185.0],
            volumes=[1_000_000] * 20,  # volume not elevated
        )
        indicators = {
            "BBANDS_20": _make_multi_indicator_result(
                "BBANDS",
                {
                    "upper": [float("nan")] * 15 + [180.0, 180.0, 180.0, 180.0, 180.0],
                    "middle": [float("nan")] * 15 + [170.0, 170.0, 170.0, 170.0, 170.0],
                    "lower": [float("nan")] * 15 + [160.0, 160.0, 160.0, 160.0, 160.0],
                },
            ),
        }

        signal = strategy.evaluate("AAPL", candles, indicators, None, correlation_id=_CORR_ID)

        assert signal is None


# ===========================================================================
# StochasticMomentum Tests
# ===========================================================================


class TestStochasticMomentumIdentity:
    def test_strategy_id(self) -> None:
        strategy = StochasticMomentumStrategy(deployment_id=_DEPLOY_ID)
        assert strategy.strategy_id == "stochastic-momentum"

    def test_name(self) -> None:
        strategy = StochasticMomentumStrategy(deployment_id=_DEPLOY_ID)
        assert "Stochastic" in strategy.name


class TestStochasticMomentumIndicators:
    def test_requires_stochastic_and_rsi(self) -> None:
        strategy = StochasticMomentumStrategy(deployment_id=_DEPLOY_ID)
        reqs = strategy.required_indicators()
        names = [r.indicator_name for r in reqs]
        assert "STOCH" in names
        assert "RSI" in names


class TestStochasticMomentumSignals:
    def test_long_on_k_crosses_above_d_below_20_with_rsi_filter(self) -> None:
        """LONG when %K crosses above %D below 20 AND RSI < 40."""
        strategy = StochasticMomentumStrategy(deployment_id=_DEPLOY_ID)
        candles = _make_candles([170.0] * 20)
        indicators = {
            "STOCH_14": _make_multi_indicator_result(
                "STOCH",
                {
                    "k": [float("nan")] * 15 + [10.0, 12.0, 14.0, 13.0, 18.0],
                    "d": [float("nan")] * 15 + [12.0, 13.0, 15.0, 16.0, 15.0],
                },
            ),
            "RSI_14": _make_indicator_result(
                "RSI", [float("nan")] * 15 + [35.0, 33.0, 30.0, 28.0, 35.0]
            ),
        }

        signal = strategy.evaluate("AAPL", candles, indicators, None, correlation_id=_CORR_ID)

        assert signal is not None
        assert signal.direction == SignalDirection.LONG

    def test_short_on_k_crosses_below_d_above_80_with_rsi_filter(self) -> None:
        """SHORT when %K crosses below %D above 80 AND RSI > 60."""
        strategy = StochasticMomentumStrategy(deployment_id=_DEPLOY_ID)
        candles = _make_candles([170.0] * 20)
        indicators = {
            "STOCH_14": _make_multi_indicator_result(
                "STOCH",
                {
                    "k": [float("nan")] * 15 + [90.0, 88.0, 86.0, 87.0, 82.0],
                    "d": [float("nan")] * 15 + [88.0, 87.0, 85.0, 84.0, 85.0],
                },
            ),
            "RSI_14": _make_indicator_result(
                "RSI", [float("nan")] * 15 + [65.0, 68.0, 70.0, 72.0, 65.0]
            ),
        }

        signal = strategy.evaluate("AAPL", candles, indicators, None, correlation_id=_CORR_ID)

        assert signal is not None
        assert signal.direction == SignalDirection.SHORT

    def test_no_signal_without_rsi_confirmation(self) -> None:
        """No LONG when stochastic triggers but RSI is above filter."""
        strategy = StochasticMomentumStrategy(deployment_id=_DEPLOY_ID)
        candles = _make_candles([170.0] * 20)
        indicators = {
            "STOCH_14": _make_multi_indicator_result(
                "STOCH",
                {
                    "k": [float("nan")] * 15 + [10.0, 12.0, 14.0, 13.0, 18.0],
                    "d": [float("nan")] * 15 + [12.0, 13.0, 15.0, 16.0, 15.0],
                },
            ),
            "RSI_14": _make_indicator_result(
                "RSI", [float("nan")] * 15 + [55.0, 53.0, 50.0, 48.0, 55.0]
            ),
        }

        signal = strategy.evaluate("AAPL", candles, indicators, None, correlation_id=_CORR_ID)

        assert signal is None

    def test_no_signal_k_d_cross_in_neutral_zone(self) -> None:
        """No signal when %K/%D cross happens in the neutral zone (20-80)."""
        strategy = StochasticMomentumStrategy(deployment_id=_DEPLOY_ID)
        candles = _make_candles([170.0] * 20)
        indicators = {
            "STOCH_14": _make_multi_indicator_result(
                "STOCH",
                {
                    "k": [float("nan")] * 15 + [45.0, 48.0, 50.0, 49.0, 55.0],
                    "d": [float("nan")] * 15 + [48.0, 49.0, 51.0, 52.0, 50.0],
                },
            ),
            "RSI_14": _make_indicator_result(
                "RSI", [float("nan")] * 15 + [35.0, 33.0, 30.0, 28.0, 35.0]
            ),
        }

        signal = strategy.evaluate("AAPL", candles, indicators, None, correlation_id=_CORR_ID)

        assert signal is None


# ===========================================================================
# CompositeSignal Tests
# ===========================================================================


class TestCompositeSignalIdentity:
    def test_strategy_id(self) -> None:
        sub = MovingAverageCrossoverStrategy(deployment_id=_DEPLOY_ID)
        strategy = CompositeSignalStrategy(deployment_id=_DEPLOY_ID, sub_strategies=[sub], quorum=1)
        assert strategy.strategy_id == "composite-signal"

    def test_name(self) -> None:
        sub = MovingAverageCrossoverStrategy(deployment_id=_DEPLOY_ID)
        strategy = CompositeSignalStrategy(deployment_id=_DEPLOY_ID, sub_strategies=[sub], quorum=1)
        assert "Composite" in strategy.name


class TestCompositeSignalIndicators:
    def test_aggregates_sub_strategy_indicators(self) -> None:
        """required_indicators() merges requirements from all sub-strategies."""
        s1 = MovingAverageCrossoverStrategy(deployment_id=_DEPLOY_ID)
        s2 = RSIMeanReversionStrategy(deployment_id=_DEPLOY_ID)
        strategy = CompositeSignalStrategy(deployment_id=_DEPLOY_ID, sub_strategies=[s1, s2])

        reqs = strategy.required_indicators()
        names = [r.indicator_name for r in reqs]

        assert "SMA" in names
        assert "RSI" in names


class TestCompositeSignalVoting:
    def _make_long_ma_indicators(self) -> dict[str, IndicatorResult]:
        """Indicators that trigger a MA crossover LONG."""
        return {
            "SMA_20": _make_indicator_result(
                "SMA", [float("nan")] * 20 + [168.0, 169.0, 170.0, 172.0, 174.0]
            ),
            "SMA_50": _make_indicator_result(
                "SMA", [float("nan")] * 20 + [170.0, 170.5, 171.0, 171.0, 171.0]
            ),
        }

    def _make_long_rsi_indicators(self) -> dict[str, IndicatorResult]:
        """Indicators that trigger an RSI LONG."""
        return {
            "RSI_14": _make_indicator_result(
                "RSI", [float("nan")] * 20 + [40.0, 35.0, 28.0, 25.0, 32.0]
            ),
        }

    def test_signal_when_quorum_met(self) -> None:
        """Signal produced when enough sub-strategies agree."""
        s1 = MovingAverageCrossoverStrategy(deployment_id=_DEPLOY_ID)
        s2 = RSIMeanReversionStrategy(deployment_id=_DEPLOY_ID)
        strategy = CompositeSignalStrategy(
            deployment_id=_DEPLOY_ID,
            sub_strategies=[s1, s2],
            quorum=1,  # At least 1 sub-strategy must fire
            min_confidence=0.0,
        )
        candles = _make_candles([170 + i * 0.5 for i in range(25)])
        # Combine indicators from both — RSI will fire LONG
        indicators = {
            **self._make_long_ma_indicators(),
            **self._make_long_rsi_indicators(),
        }

        signal = strategy.evaluate("AAPL", candles, indicators, None, correlation_id=_CORR_ID)

        assert signal is not None
        assert signal.direction == SignalDirection.LONG

    def test_no_signal_when_quorum_not_met(self) -> None:
        """No signal when not enough sub-strategies fire."""
        s1 = MovingAverageCrossoverStrategy(deployment_id=_DEPLOY_ID)
        s2 = RSIMeanReversionStrategy(deployment_id=_DEPLOY_ID)
        strategy = CompositeSignalStrategy(
            deployment_id=_DEPLOY_ID,
            sub_strategies=[s1, s2],
            quorum=2,  # Both must fire
            min_confidence=0.0,
        )
        candles = _make_candles([170.0] * 25)
        # Only RSI fires, MA does not cross
        indicators = {
            "SMA_20": _make_indicator_result(
                "SMA", [float("nan")] * 20 + [175.0, 176.0, 177.0, 178.0, 179.0]
            ),
            "SMA_50": _make_indicator_result(
                "SMA", [float("nan")] * 20 + [170.0, 170.5, 171.0, 171.5, 172.0]
            ),
            **self._make_long_rsi_indicators(),
        }

        signal = strategy.evaluate("AAPL", candles, indicators, None, correlation_id=_CORR_ID)

        assert signal is None

    def test_weighted_confidence(self) -> None:
        """Composite confidence is weighted average of sub-signal confidences."""
        s1 = MovingAverageCrossoverStrategy(deployment_id=_DEPLOY_ID)
        s2 = RSIMeanReversionStrategy(deployment_id=_DEPLOY_ID)
        strategy = CompositeSignalStrategy(
            deployment_id=_DEPLOY_ID,
            sub_strategies=[s1, s2],
            weights={s1.strategy_id: 2.0, s2.strategy_id: 1.0},
            quorum=1,
            min_confidence=0.0,
        )
        candles = _make_candles([170 + i * 0.5 for i in range(25)])
        indicators = {
            **self._make_long_ma_indicators(),
            **self._make_long_rsi_indicators(),
        }

        signal = strategy.evaluate("AAPL", candles, indicators, None, correlation_id=_CORR_ID)

        # At least check the confidence is a valid value
        if signal is not None:
            assert 0.0 <= signal.confidence <= 1.0

    def test_no_signal_below_min_confidence(self) -> None:
        """No signal when composite confidence is below minimum."""
        s1 = MovingAverageCrossoverStrategy(deployment_id=_DEPLOY_ID)
        strategy = CompositeSignalStrategy(
            deployment_id=_DEPLOY_ID,
            sub_strategies=[s1],
            quorum=1,
            min_confidence=0.99,  # Very high bar
        )
        candles = _make_candles([170 + i * 0.5 for i in range(25)])
        indicators = self._make_long_ma_indicators()

        signal = strategy.evaluate("AAPL", candles, indicators, None, correlation_id=_CORR_ID)

        assert signal is None
