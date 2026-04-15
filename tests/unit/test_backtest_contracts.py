"""
Unit tests for backtesting contracts (Phase 7 — M12).

Verifies:
- BacktestInterval enum values and string representation.
- BacktestConfig default values, custom values, validation, and immutability.
- BacktestBar default values, custom values, and indicator storage.
- BacktestTrade validation (side, quantity, price).
- BacktestResult default values, computed_at auto-population, and serialization.

Dependencies:
- libs/contracts/backtest.py: All backtest contract models.
- pydantic.ValidationError: Expected on invalid inputs.

Example:
    pytest tests/unit/test_backtest_contracts.py -v
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal

import pytest
from pydantic import ValidationError

from libs.contracts.backtest import (
    BacktestBar,
    BacktestConfig,
    BacktestInterval,
    BacktestResult,
    BacktestTrade,
)

# ---------------------------------------------------------------------------
# BacktestInterval
# ---------------------------------------------------------------------------


class TestBacktestInterval:
    """Tests for BacktestInterval enum."""

    def test_all_intervals_have_expected_values(self) -> None:
        """All enum members map to their canonical interval strings."""
        expected = {
            "ONE_MINUTE": "1m",
            "FIVE_MINUTES": "5m",
            "FIFTEEN_MINUTES": "15m",
            "ONE_HOUR": "1h",
            "ONE_DAY": "1d",
        }
        for name, value in expected.items():
            assert BacktestInterval[name].value == value

    def test_interval_count(self) -> None:
        """Exactly 5 intervals are defined."""
        assert len(BacktestInterval) == 5

    def test_interval_string_representation(self) -> None:
        """Interval values work as plain strings."""
        assert BacktestInterval.ONE_DAY == "1d"
        assert BacktestInterval.ONE_HOUR.value == "1h"


# ---------------------------------------------------------------------------
# BacktestConfig
# ---------------------------------------------------------------------------


class TestBacktestConfig:
    """Tests for BacktestConfig frozen model."""

    def test_config_with_defaults(self) -> None:
        """Config accepts only required fields, applies defaults."""
        config = BacktestConfig(
            strategy_id="01HSTRAT000000000000000000",
            symbols=["AAPL"],
            start_date=date(2025, 1, 1),
            end_date=date(2025, 12, 31),
        )
        assert config.interval == BacktestInterval.ONE_DAY
        assert config.initial_equity == Decimal("100000")
        assert config.lookback_buffer_days == 30
        assert config.indicator_cache_size == 100
        assert config.commission_per_trade == Decimal("0")
        assert config.slippage_pct == Decimal("0")

    def test_config_with_custom_values(self) -> None:
        """Config accepts all custom values."""
        config = BacktestConfig(
            strategy_id="01HSTRAT000000000000000001",
            symbols=["AAPL", "MSFT", "GOOG"],
            start_date=date(2024, 6, 1),
            end_date=date(2024, 12, 31),
            interval=BacktestInterval.ONE_HOUR,
            initial_equity=Decimal("500000"),
            lookback_buffer_days=60,
            indicator_cache_size=500,
            commission_per_trade=Decimal("1.50"),
            slippage_pct=Decimal("0.05"),
        )
        assert config.symbols == ["AAPL", "MSFT", "GOOG"]
        assert config.interval == BacktestInterval.ONE_HOUR
        assert config.initial_equity == Decimal("500000")
        assert config.lookback_buffer_days == 60
        assert config.indicator_cache_size == 500
        assert config.commission_per_trade == Decimal("1.50")
        assert config.slippage_pct == Decimal("0.05")

    def test_config_is_frozen(self) -> None:
        """Config is immutable after creation."""
        config = BacktestConfig(
            strategy_id="01HSTRAT000000000000000000",
            symbols=["AAPL"],
            start_date=date(2025, 1, 1),
            end_date=date(2025, 12, 31),
        )
        with pytest.raises(ValidationError):
            config.initial_equity = Decimal("200000")  # type: ignore[misc]

    def test_config_rejects_empty_strategy_id(self) -> None:
        """Strategy ID must be non-empty."""
        with pytest.raises(ValidationError, match="strategy_id"):
            BacktestConfig(
                strategy_id="",
                symbols=["AAPL"],
                start_date=date(2025, 1, 1),
                end_date=date(2025, 12, 31),
            )

    def test_config_rejects_empty_symbols(self) -> None:
        """At least one symbol is required."""
        with pytest.raises(ValidationError, match="symbols"):
            BacktestConfig(
                strategy_id="01HSTRAT000000000000000000",
                symbols=[],
                start_date=date(2025, 1, 1),
                end_date=date(2025, 12, 31),
            )

    def test_config_rejects_zero_equity(self) -> None:
        """Initial equity must be positive."""
        with pytest.raises(ValidationError, match="initial_equity"):
            BacktestConfig(
                strategy_id="01HSTRAT000000000000000000",
                symbols=["AAPL"],
                start_date=date(2025, 1, 1),
                end_date=date(2025, 12, 31),
                initial_equity=Decimal("0"),
            )

    def test_config_rejects_negative_lookback(self) -> None:
        """Lookback buffer days must be >= 0."""
        with pytest.raises(ValidationError, match="lookback_buffer_days"):
            BacktestConfig(
                strategy_id="01HSTRAT000000000000000000",
                symbols=["AAPL"],
                start_date=date(2025, 1, 1),
                end_date=date(2025, 12, 31),
                lookback_buffer_days=-1,
            )

    def test_config_rejects_excessive_lookback(self) -> None:
        """Lookback buffer days capped at 500."""
        with pytest.raises(ValidationError, match="lookback_buffer_days"):
            BacktestConfig(
                strategy_id="01HSTRAT000000000000000000",
                symbols=["AAPL"],
                start_date=date(2025, 1, 1),
                end_date=date(2025, 12, 31),
                lookback_buffer_days=501,
            )

    def test_config_rejects_slippage_over_100(self) -> None:
        """Slippage percentage capped at 100."""
        with pytest.raises(ValidationError, match="slippage_pct"):
            BacktestConfig(
                strategy_id="01HSTRAT000000000000000000",
                symbols=["AAPL"],
                start_date=date(2025, 1, 1),
                end_date=date(2025, 12, 31),
                slippage_pct=Decimal("101"),
            )

    def test_config_serialization_roundtrip(self) -> None:
        """Config survives model_dump → model_validate roundtrip."""
        config = BacktestConfig(
            strategy_id="01HSTRAT000000000000000000",
            symbols=["AAPL", "MSFT"],
            start_date=date(2025, 1, 1),
            end_date=date(2025, 6, 30),
            interval=BacktestInterval.FIVE_MINUTES,
            initial_equity=Decimal("250000"),
        )
        data = config.model_dump()
        restored = BacktestConfig.model_validate(data)
        assert restored == config


# ---------------------------------------------------------------------------
# BacktestBar
# ---------------------------------------------------------------------------


class TestBacktestBar:
    """Tests for BacktestBar frozen model."""

    def test_bar_with_defaults(self) -> None:
        """Bar accepts OHLCV and applies defaults for optional fields."""
        ts = datetime(2025, 6, 15, 16, 0, tzinfo=timezone.utc)
        bar = BacktestBar(
            timestamp=ts,
            symbol="AAPL",
            open=Decimal("150.00"),
            high=Decimal("152.00"),
            low=Decimal("149.00"),
            close=Decimal("151.50"),
        )
        assert bar.volume == 0
        assert bar.indicators == {}
        assert bar.signal == 0
        assert bar.position == Decimal("0")
        assert bar.equity == Decimal("0")

    def test_bar_with_indicators(self) -> None:
        """Bar can store indicator values."""
        ts = datetime(2025, 6, 15, 16, 0, tzinfo=timezone.utc)
        bar = BacktestBar(
            timestamp=ts,
            symbol="AAPL",
            open=Decimal("150.00"),
            high=Decimal("152.00"),
            low=Decimal("149.00"),
            close=Decimal("151.50"),
            volume=1000000,
            indicators={
                "SMA_20": Decimal("150.25"),
                "RSI_14": Decimal("55.30"),
                "MACD": None,
            },
            signal=1,
            position=Decimal("100"),
            equity=Decimal("115000"),
        )
        assert bar.indicators["SMA_20"] == Decimal("150.25")
        assert bar.indicators["MACD"] is None
        assert bar.signal == 1

    def test_bar_is_frozen(self) -> None:
        """Bar is immutable after creation."""
        ts = datetime(2025, 6, 15, 16, 0, tzinfo=timezone.utc)
        bar = BacktestBar(
            timestamp=ts,
            symbol="AAPL",
            open=Decimal("150.00"),
            high=Decimal("152.00"),
            low=Decimal("149.00"),
            close=Decimal("151.50"),
        )
        with pytest.raises(ValidationError):
            bar.close = Decimal("160.00")  # type: ignore[misc]

    def test_bar_rejects_invalid_signal(self) -> None:
        """Signal must be -1, 0, or 1."""
        ts = datetime(2025, 6, 15, 16, 0, tzinfo=timezone.utc)
        with pytest.raises(ValidationError, match="signal"):
            BacktestBar(
                timestamp=ts,
                symbol="AAPL",
                open=Decimal("150.00"),
                high=Decimal("152.00"),
                low=Decimal("149.00"),
                close=Decimal("151.50"),
                signal=2,
            )

    def test_bar_rejects_negative_volume(self) -> None:
        """Volume must be >= 0."""
        ts = datetime(2025, 6, 15, 16, 0, tzinfo=timezone.utc)
        with pytest.raises(ValidationError, match="volume"):
            BacktestBar(
                timestamp=ts,
                symbol="AAPL",
                open=Decimal("150.00"),
                high=Decimal("152.00"),
                low=Decimal("149.00"),
                close=Decimal("151.50"),
                volume=-1,
            )


# ---------------------------------------------------------------------------
# BacktestTrade
# ---------------------------------------------------------------------------


class TestBacktestTrade:
    """Tests for BacktestTrade frozen model."""

    def test_trade_buy(self) -> None:
        """Buy trade is created with required fields."""
        ts = datetime(2025, 6, 15, 16, 0, tzinfo=timezone.utc)
        trade = BacktestTrade(
            timestamp=ts,
            symbol="AAPL",
            side="buy",
            quantity=Decimal("100"),
            price=Decimal("151.50"),
        )
        assert trade.side == "buy"
        assert trade.commission == Decimal("0")
        assert trade.slippage == Decimal("0")

    def test_trade_sell_with_costs(self) -> None:
        """Sell trade with commission and slippage."""
        ts = datetime(2025, 6, 15, 16, 0, tzinfo=timezone.utc)
        trade = BacktestTrade(
            timestamp=ts,
            symbol="AAPL",
            side="sell",
            quantity=Decimal("50"),
            price=Decimal("155.00"),
            commission=Decimal("1.50"),
            slippage=Decimal("0.25"),
        )
        assert trade.side == "sell"
        assert trade.commission == Decimal("1.50")
        assert trade.slippage == Decimal("0.25")

    def test_trade_rejects_invalid_side(self) -> None:
        """Side must be 'buy' or 'sell'."""
        ts = datetime(2025, 6, 15, 16, 0, tzinfo=timezone.utc)
        with pytest.raises(ValidationError, match="side"):
            BacktestTrade(
                timestamp=ts,
                symbol="AAPL",
                side="hold",
                quantity=Decimal("100"),
                price=Decimal("150.00"),
            )

    def test_trade_rejects_zero_quantity(self) -> None:
        """Quantity must be positive."""
        ts = datetime(2025, 6, 15, 16, 0, tzinfo=timezone.utc)
        with pytest.raises(ValidationError, match="quantity"):
            BacktestTrade(
                timestamp=ts,
                symbol="AAPL",
                side="buy",
                quantity=Decimal("0"),
                price=Decimal("150.00"),
            )

    def test_trade_rejects_zero_price(self) -> None:
        """Price must be positive."""
        ts = datetime(2025, 6, 15, 16, 0, tzinfo=timezone.utc)
        with pytest.raises(ValidationError, match="price"):
            BacktestTrade(
                timestamp=ts,
                symbol="AAPL",
                side="buy",
                quantity=Decimal("100"),
                price=Decimal("0"),
            )

    def test_trade_is_frozen(self) -> None:
        """Trade is immutable after creation."""
        ts = datetime(2025, 6, 15, 16, 0, tzinfo=timezone.utc)
        trade = BacktestTrade(
            timestamp=ts,
            symbol="AAPL",
            side="buy",
            quantity=Decimal("100"),
            price=Decimal("150.00"),
        )
        with pytest.raises(ValidationError):
            trade.price = Decimal("200.00")  # type: ignore[misc]


# ---------------------------------------------------------------------------
# BacktestResult
# ---------------------------------------------------------------------------


class TestBacktestResult:
    """Tests for BacktestResult frozen model."""

    @pytest.fixture()
    def sample_config(self) -> BacktestConfig:
        """Minimal BacktestConfig for result tests."""
        return BacktestConfig(
            strategy_id="01HSTRAT000000000000000000",
            symbols=["AAPL"],
            start_date=date(2025, 1, 1),
            end_date=date(2025, 12, 31),
        )

    def test_result_with_defaults(self, sample_config: BacktestConfig) -> None:
        """Result populates defaults for all optional fields."""
        result = BacktestResult(config=sample_config)
        assert result.total_return_pct == Decimal("0")
        assert result.annualized_return_pct == Decimal("0")
        assert result.max_drawdown_pct == Decimal("0")
        assert result.sharpe_ratio == Decimal("0")
        assert result.total_trades == 0
        assert result.win_rate == Decimal("0")
        assert result.profit_factor == Decimal("0")
        assert result.final_equity == Decimal("0")
        assert result.trades == []
        assert result.equity_curve == []
        assert result.indicators_computed == []
        assert result.bars_processed == 0
        assert result.computed_at is not None

    def test_result_with_metrics(self, sample_config: BacktestConfig) -> None:
        """Result accepts performance metrics."""
        result = BacktestResult(
            config=sample_config,
            total_return_pct=Decimal("15.50"),
            annualized_return_pct=Decimal("15.50"),
            max_drawdown_pct=Decimal("-8.20"),
            sharpe_ratio=Decimal("1.45"),
            total_trades=42,
            win_rate=Decimal("0.55"),
            profit_factor=Decimal("1.80"),
            final_equity=Decimal("115500"),
            indicators_computed=["SMA", "RSI", "MACD"],
            bars_processed=252,
        )
        assert result.total_return_pct == Decimal("15.50")
        assert result.max_drawdown_pct == Decimal("-8.20")
        assert result.total_trades == 42
        assert len(result.indicators_computed) == 3

    def test_result_computed_at_auto_populated(self, sample_config: BacktestConfig) -> None:
        """computed_at is auto-set to current UTC time."""
        before = datetime.now(timezone.utc)
        result = BacktestResult(config=sample_config)
        after = datetime.now(timezone.utc)
        assert before <= result.computed_at <= after

    def test_result_is_frozen(self, sample_config: BacktestConfig) -> None:
        """Result is immutable after creation."""
        result = BacktestResult(config=sample_config)
        with pytest.raises(ValidationError):
            result.total_trades = 99  # type: ignore[misc]

    def test_result_rejects_positive_drawdown(self, sample_config: BacktestConfig) -> None:
        """Max drawdown must be <= 0 (negative or zero)."""
        with pytest.raises(ValidationError, match="max_drawdown_pct"):
            BacktestResult(
                config=sample_config,
                max_drawdown_pct=Decimal("5.0"),
            )

    def test_result_rejects_win_rate_over_one(self, sample_config: BacktestConfig) -> None:
        """Win rate must be between 0 and 1."""
        with pytest.raises(ValidationError, match="win_rate"):
            BacktestResult(
                config=sample_config,
                win_rate=Decimal("1.5"),
            )

    def test_result_serialization_roundtrip(self, sample_config: BacktestConfig) -> None:
        """Result survives model_dump → model_validate roundtrip."""
        result = BacktestResult(
            config=sample_config,
            total_return_pct=Decimal("10.00"),
            max_drawdown_pct=Decimal("-5.00"),
            sharpe_ratio=Decimal("1.20"),
            total_trades=20,
            win_rate=Decimal("0.60"),
            profit_factor=Decimal("1.50"),
            final_equity=Decimal("110000"),
            bars_processed=252,
        )
        data = result.model_dump()
        restored = BacktestResult.model_validate(data)
        assert restored.total_return_pct == result.total_return_pct
        assert restored.config == result.config

    def test_result_with_trades(self, sample_config: BacktestConfig) -> None:
        """Result stores trade log."""
        ts = datetime(2025, 6, 15, 16, 0, tzinfo=timezone.utc)
        trade = BacktestTrade(
            timestamp=ts,
            symbol="AAPL",
            side="buy",
            quantity=Decimal("100"),
            price=Decimal("151.50"),
        )
        result = BacktestResult(
            config=sample_config,
            trades=[trade],
            total_trades=1,
        )
        assert len(result.trades) == 1
        assert result.trades[0].side == "buy"
