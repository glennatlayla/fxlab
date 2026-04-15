"""
Backtesting contracts and value objects (Phase 7 M12, extended Phase 8 M9).

Responsibilities:
- Define backtest configuration parameters.
- Define backtest result with performance metrics and indicator usage.
- Define per-bar data structure for backtest time series.
- Define signal attribution types for backtest→signal→trade tracing (M9).
- Define drawdown curve and equity curve point types (M9).
- Provide frozen Pydantic models for immutable value objects.

Does NOT:
- Execute backtests (research engine responsibility).
- Compute indicators (IndicatorEngine responsibility).
- Fetch market data (repository responsibility).

Dependencies:
- pydantic: BaseModel, Field.
- Standard library: Decimal, datetime, enum.

Error conditions:
- ValidationError: invalid field values (Pydantic enforcement).

Example:
    config = BacktestConfig(
        strategy_id="01HSTRAT000000000000000000",
        symbols=["AAPL", "MSFT"],
        start_date=date(2025, 1, 1),
        end_date=date(2025, 12, 31),
        interval="1d",
        initial_equity=Decimal("100000"),
    )
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
from enum import Enum

from pydantic import BaseModel, Field


class BacktestInterval(str, Enum):  # noqa: UP042 — StrEnum requires Python 3.11+
    """
    Supported backtest bar intervals.

    Values correspond to candle intervals stored in the market data repository.
    """

    ONE_MINUTE = "1m"
    FIVE_MINUTES = "5m"
    FIFTEEN_MINUTES = "15m"
    ONE_HOUR = "1h"
    ONE_DAY = "1d"


class BacktestConfig(BaseModel):
    """
    Configuration for a backtest run.

    Specifies the strategy, symbols, date range, interval, and equity
    parameters needed to execute a historical backtest.

    Attributes:
        strategy_id: ULID of the strategy to backtest.
        symbols: List of symbols to include in the backtest universe.
        start_date: Start date for the backtest period (inclusive).
        end_date: End date for the backtest period (inclusive).
        interval: Bar interval for the backtest.
        initial_equity: Starting equity for the simulated portfolio.
        lookback_buffer_days: Extra days of data to fetch before start_date
            so that indicators with long lookback periods (e.g., SMA(200))
            have enough historical data. Defaults to 30.
        indicator_cache_size: Maximum number of cached indicator results
            per backtest run. Prevents memory exhaustion on strategies
            with many indicator references. Defaults to 100.
        commission_per_trade: Commission per trade in dollars. Defaults to 0.
        slippage_pct: Slippage as percentage of trade value. Defaults to 0.

    Example:
        config = BacktestConfig(
            strategy_id="01HSTRAT000000000000000000",
            symbols=["AAPL"],
            start_date=date(2025, 1, 1),
            end_date=date(2025, 12, 31),
        )
    """

    model_config = {"frozen": True}

    strategy_id: str = Field(..., min_length=1, description="Strategy ULID.")
    symbols: list[str] = Field(..., min_length=1, description="Universe of symbols.")
    start_date: date = Field(..., description="Backtest start date (inclusive).")
    end_date: date = Field(..., description="Backtest end date (inclusive).")
    interval: BacktestInterval = Field(
        default=BacktestInterval.ONE_DAY,
        description="Bar interval.",
    )
    initial_equity: Decimal = Field(
        default=Decimal("100000"),
        gt=0.0,
        description="Starting equity.",
    )
    lookback_buffer_days: int = Field(
        default=30,
        ge=0,
        le=500,
        description="Extra lookback days for indicator warm-up.",
    )
    indicator_cache_size: int = Field(
        default=100,
        ge=1,
        le=10000,
        description="Max cached indicator results per run.",
    )
    commission_per_trade: Decimal = Field(
        default=Decimal("0"),
        ge=0.0,
        description="Commission per trade (dollars).",
    )
    slippage_pct: Decimal = Field(
        default=Decimal("0"),
        ge=0.0,
        le=100.0,
        description="Slippage as percentage of trade value.",
    )


class BacktestBar(BaseModel):
    """
    A single bar in a backtest time series.

    Represents one evaluation point with OHLCV data plus any computed
    indicator values and signal/position state.

    Attributes:
        timestamp: Bar timestamp.
        symbol: Instrument symbol.
        open: Opening price.
        high: High price.
        low: Low price.
        close: Closing price.
        volume: Bar volume.
        indicators: Dict of indicator_name → computed value for this bar.
        signal: Trading signal (-1=sell, 0=flat, 1=buy).
        position: Current position size after this bar.
        equity: Portfolio equity at this bar.

    Example:
        bar = BacktestBar(
            timestamp=datetime(2025, 6, 15, 16, 0),
            symbol="AAPL",
            open=Decimal("150.00"), high=Decimal("152.00"),
            low=Decimal("149.00"), close=Decimal("151.50"),
            volume=1000000,
        )
    """

    model_config = {"frozen": True}

    timestamp: datetime
    symbol: str
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: int = Field(default=0, ge=0)
    indicators: dict[str, Decimal | None] = Field(default_factory=dict)
    signal: int = Field(default=0, ge=-1, le=1)
    position: Decimal = Field(default=Decimal("0"))
    equity: Decimal = Field(default=Decimal("0"))


class BacktestTrade(BaseModel):
    """
    A simulated trade executed during a backtest.

    Attributes:
        timestamp: When the trade was executed.
        symbol: Instrument symbol.
        side: Trade side ('buy' or 'sell').
        quantity: Number of shares/contracts.
        price: Execution price.
        commission: Commission paid.
        slippage: Estimated slippage cost.

    Example:
        trade = BacktestTrade(
            timestamp=datetime(2025, 6, 15, 16, 0),
            symbol="AAPL", side="buy",
            quantity=Decimal("100"), price=Decimal("151.50"),
        )
    """

    model_config = {"frozen": True}

    timestamp: datetime
    symbol: str
    side: str = Field(..., pattern=r"^(buy|sell)$")
    quantity: Decimal = Field(..., gt=0.0)
    price: Decimal = Field(..., gt=0.0)
    commission: Decimal = Field(default=Decimal("0"), ge=0.0)
    slippage: Decimal = Field(default=Decimal("0"), ge=0.0)


class BacktestResult(BaseModel):
    """
    Result of a completed backtest run.

    Contains performance metrics, trade log, equity curve, and
    metadata about indicators computed during the run.

    Attributes:
        config: Backtest configuration used.
        total_return_pct: Total return as percentage.
        annualized_return_pct: Annualized return percentage.
        max_drawdown_pct: Maximum drawdown percentage.
        sharpe_ratio: Annualized Sharpe ratio (risk-free rate = 0).
        total_trades: Number of trades executed.
        win_rate: Fraction of winning trades (0-1).
        profit_factor: Gross profit / gross loss.
        final_equity: Ending portfolio equity.
        trades: List of simulated trades.
        equity_curve: Time series of equity values.
        indicators_computed: List of indicator names used in the backtest.
        bars_processed: Number of bars evaluated.
        computed_at: When the backtest completed.

    Example:
        result = BacktestResult(
            config=config,
            total_return_pct=Decimal("15.50"),
            max_drawdown_pct=Decimal("8.20"),
            sharpe_ratio=Decimal("1.45"),
            total_trades=42,
            win_rate=Decimal("0.55"),
            profit_factor=Decimal("1.80"),
            final_equity=Decimal("115500"),
        )
    """

    model_config = {"frozen": True}

    config: BacktestConfig
    total_return_pct: Decimal = Field(default=Decimal("0"), description="Total return %.")
    annualized_return_pct: Decimal = Field(default=Decimal("0"), description="Annualized return %.")
    max_drawdown_pct: Decimal = Field(
        default=Decimal("0"), le=0.0, description="Max drawdown % (negative)."
    )
    sharpe_ratio: Decimal = Field(default=Decimal("0"), description="Annualized Sharpe ratio.")
    total_trades: int = Field(default=0, ge=0)
    win_rate: Decimal = Field(default=Decimal("0"), ge=0.0, le=1.0)
    profit_factor: Decimal = Field(default=Decimal("0"), ge=0.0)
    final_equity: Decimal = Field(default=Decimal("0"), ge=0.0)
    trades: list[BacktestTrade] = Field(default_factory=list)
    equity_curve: list[BacktestBar] = Field(default_factory=list)
    indicators_computed: list[str] = Field(default_factory=list)
    bars_processed: int = Field(default=0, ge=0)
    signal_summary: BacktestSignalSummary | None = Field(
        default=None,
        description="Signal attribution and drawdown data (M9 extension).",
    )
    computed_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc),
    )


# ---------------------------------------------------------------------------
# Phase 8 M9 — Signal-attribution extensions
# ---------------------------------------------------------------------------


class EquityCurvePoint(BaseModel):
    """
    A single point on the equity curve.

    Attributes:
        timestamp: When this snapshot was taken.
        equity: Total portfolio equity at this point.

    Example:
        point = EquityCurvePoint(
            timestamp=datetime(2025, 6, 15, 16, 0, tzinfo=timezone.utc),
            equity=Decimal("105000"),
        )
    """

    model_config = {"frozen": True}

    timestamp: datetime
    equity: Decimal = Field(..., ge=0.0)


class DrawdownPoint(BaseModel):
    """
    A single point on the drawdown curve.

    Attributes:
        timestamp: When this drawdown was measured.
        drawdown_pct: Drawdown as a percentage (negative or zero).

    Example:
        point = DrawdownPoint(
            timestamp=datetime(2025, 6, 15, 16, 0, tzinfo=timezone.utc),
            drawdown_pct=Decimal("-3.50"),
        )
    """

    model_config = {"frozen": True}

    timestamp: datetime
    drawdown_pct: Decimal = Field(..., le=0.0)


class SignalAttribution(BaseModel):
    """
    Links a signal to the trade it produced during backtesting.

    Provides full traceability from signal generation through evaluation
    to the resulting trade, including indicator state at signal time.

    Attributes:
        signal_id: ID of the signal.
        strategy_id: Which strategy produced the signal.
        symbol: Instrument ticker.
        direction: Signal direction (long/short/flat).
        signal_type: Entry or exit.
        confidence: Signal confidence (0-1).
        approved: Whether the signal passed risk gates.
        rejection_reason: Why the signal was rejected (if applicable).
        trade_index: Index into BacktestResult.trades (None if rejected).
        bar_timestamp: Candle timestamp that produced the signal.
        indicators_at_signal: Snapshot of indicator values when signal was generated.

    Example:
        attr = SignalAttribution(
            signal_id="sig-001",
            strategy_id="ma-crossover",
            symbol="AAPL",
            direction="long",
            signal_type="entry",
            confidence=0.85,
            approved=True,
            trade_index=0,
            bar_timestamp=datetime(2025, 6, 15, 16, 0, tzinfo=timezone.utc),
            indicators_at_signal={"sma_20": Decimal("175.50")},
        )
    """

    model_config = {"frozen": True}

    signal_id: str = Field(..., min_length=1)
    strategy_id: str = Field(..., min_length=1)
    symbol: str = Field(..., min_length=1)
    direction: str = Field(..., description="Signal direction (long/short/flat).")
    signal_type: str = Field(..., description="Signal type (entry/exit).")
    confidence: float = Field(..., ge=0.0, le=1.0)
    approved: bool
    rejection_reason: str | None = None
    trade_index: int | None = Field(default=None, ge=0, description="Index into trades list.")
    bar_timestamp: datetime
    indicators_at_signal: dict[str, Decimal | float | None] = Field(default_factory=dict)


class BacktestSignalSummary(BaseModel):
    """
    Summary of signal activity during a backtest.

    Attributes:
        signals_generated: Total raw signals produced by the strategy.
        signals_approved: Signals that passed all risk gates.
        signals_rejected: Signals rejected by the evaluation pipeline.
        signal_attributions: Per-signal traceability records.
        drawdown_curve: Time series of drawdown values.
        equity_curve_points: Time series of equity values.

    Example:
        summary = BacktestSignalSummary(
            signals_generated=50,
            signals_approved=40,
            signals_rejected=10,
        )
    """

    model_config = {"frozen": True}

    signals_generated: int = Field(default=0, ge=0)
    signals_approved: int = Field(default=0, ge=0)
    signals_rejected: int = Field(default=0, ge=0)
    signal_attributions: list[SignalAttribution] = Field(default_factory=list)
    drawdown_curve: list[DrawdownPoint] = Field(default_factory=list)
    equity_curve_points: list[EquityCurvePoint] = Field(default_factory=list)


# Rebuild BacktestResult model to resolve forward reference to BacktestSignalSummary
BacktestResult.model_rebuild()
