"""
Event-driven backtesting engine — replays historical bars through signal pipeline (M9).

Responsibilities:
- Execute full historical backtests using the same SignalStrategy pipeline as live trading.
- Replay candles from MarketDataRepository through signal evaluation and simulated broker.
- Track equity curve, drawdown curve, and signal attribution per bar.
- Compute performance metrics (return, Sharpe, win rate, profit factor, max drawdown).
- Support configurable slippage and commission via BacktestConfig.

Does NOT:
- Stream live data (historical replay only).
- Implement strategy logic (uses injected SignalStrategyInterface).
- Persist results (caller responsibility).
- Manage multiple concurrent backtests (caller orchestrates).

Dependencies (all injected):
- SignalStrategyInterface: strategy to generate signals.
- MarketDataRepositoryInterface: historical candle source.
- IndicatorEngine: compute indicators from candle buffers.

Self-managed:
- PaperBrokerAdapter: created from BacktestConfig for simulated fills.

Error conditions:
- ValueError: if config has invalid parameters.
- ExternalServiceError: if market data repository fails during candle fetch.

Example:
    engine = BacktestEngine(
        signal_strategy=ma_crossover_strategy,
        market_data_repository=sql_market_repo,
        indicator_engine=indicator_engine,
    )
    config = BacktestConfig(
        strategy_id="ma-crossover",
        symbols=["AAPL"],
        start_date=date(2025, 1, 1),
        end_date=date(2025, 12, 31),
    )
    result = engine.run(config)
    print(f"Return: {result.total_return_pct}%, Sharpe: {result.sharpe_ratio}")
"""

from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone
from decimal import ROUND_HALF_UP, Decimal
from typing import TYPE_CHECKING

import structlog
import ulid

from libs.broker.paper_broker_adapter import PaperBrokerAdapter
from libs.contracts.backtest import (
    BacktestConfig,
    BacktestResult,
    BacktestSignalSummary,
    BacktestTrade,
    DrawdownPoint,
    EquityCurvePoint,
    SignalAttribution,
)
from libs.contracts.execution import (
    ExecutionMode,
    OrderRequest,
    OrderSide,
    OrderType,
    TimeInForce,
)
from libs.contracts.interfaces.backtest_engine import BacktestEngineInterface
from libs.contracts.market_data import CandleInterval, MarketDataQuery
from libs.contracts.signal import SignalDirection

if TYPE_CHECKING:
    from libs.contracts.indicator import IndicatorResult
    from libs.contracts.interfaces.market_data_repository import (
        MarketDataRepositoryInterface,
    )
    from libs.contracts.interfaces.signal_strategy import SignalStrategyInterface
    from libs.contracts.market_data import Candle
    from libs.contracts.signal import Signal
    from libs.indicators.engine import IndicatorEngine

logger = structlog.get_logger(__name__)

# Map BacktestInterval string values to CandleInterval members.
# Both enums share identical string values (1m, 5m, 15m, 1h, 1d).
_INTERVAL_MAP: dict[str, CandleInterval] = {ci.value: ci for ci in CandleInterval}


class BacktestEngine(BacktestEngineInterface):
    """
    Event-driven backtesting engine with backtest-live parity.

    Replays historical candles through the same SignalStrategy pipeline
    used in live execution (M7), with a PaperBrokerAdapter for simulated
    order fills. Produces BacktestResult with full signal attribution,
    equity curve, and drawdown tracking.

    Responsibilities:
    - Fetch historical candles for all symbols in the config date range.
    - Replay bars chronologically, computing indicators and evaluating strategy.
    - Track equity, positions, and P&L through the simulated broker.
    - Compute performance metrics after all bars are processed.
    - Build signal attribution records linking signals to trades.

    Does NOT:
    - Implement strategy logic (uses injected SignalStrategy).
    - Persist results (returns BacktestResult to caller).
    - Handle live market data or real broker connections.

    Thread safety:
    - Not thread-safe. Each run() call is self-contained and sequential.
    - Callers must not share a BacktestEngine instance across threads.

    Example:
        engine = BacktestEngine(
            signal_strategy=ma_crossover,
            market_data_repository=market_repo,
            indicator_engine=indicator_engine,
        )
        result = engine.run(config)
    """

    def __init__(
        self,
        *,
        signal_strategy: SignalStrategyInterface,
        market_data_repository: MarketDataRepositoryInterface,
        indicator_engine: IndicatorEngine,
    ) -> None:
        """
        Initialize the backtest engine with required dependencies.

        Args:
            signal_strategy: Strategy to generate signals from candle data.
            market_data_repository: Source for historical candle data.
            indicator_engine: Engine to compute technical indicators.

        Example:
            engine = BacktestEngine(
                signal_strategy=strategy,
                market_data_repository=repo,
                indicator_engine=ind_engine,
            )
        """
        self._signal_strategy = signal_strategy
        self._market_data_repository = market_data_repository
        self._indicator_engine = indicator_engine

    def run(self, config: BacktestConfig) -> BacktestResult:
        """
        Execute a backtest run and return results.

        Pipeline per bar:
        1. Update broker market prices from candle close.
        2. Process pending orders (fills from previous bar signals).
        3. Maintain candle buffer for indicator lookback.
        4. Compute indicators via IndicatorEngine.
        5. Evaluate strategy for signal generation.
        6. If signal: record attribution, build order, submit to broker.
        7. Record equity curve and drawdown points.

        After all bars:
        8. Close any remaining positions at last bar close.
        9. Compute aggregate performance metrics.
        10. Build and return BacktestResult.

        Args:
            config: Backtest configuration (strategy, symbols, dates, costs).

        Returns:
            BacktestResult with metrics, trades, equity curve, and signal summary.

        Raises:
            ValueError: If config date range is empty or symbols are invalid.

        Example:
            result = engine.run(config)
            print(f"Return: {result.total_return_pct}%")
        """
        correlation_id = f"bt-{ulid.ULID()!s}"
        candle_interval = _INTERVAL_MAP[config.interval.value]

        logger.info(
            "Backtest started",
            strategy_id=config.strategy_id,
            symbols=config.symbols,
            start_date=str(config.start_date),
            end_date=str(config.end_date),
            interval=config.interval.value,
            initial_equity=str(config.initial_equity),
            correlation_id=correlation_id,
        )

        # 1. Fetch historical candles for all symbols
        all_candles = self._fetch_candles(config, candle_interval)

        if not all_candles:
            logger.warning(
                "No candles found for backtest",
                symbols=config.symbols,
                correlation_id=correlation_id,
            )
            return self._empty_result(config)

        # 2. Create PaperBrokerAdapter from config
        initial_prices = {sym: Decimal("0") for sym in config.symbols}
        broker = PaperBrokerAdapter(
            market_prices=initial_prices,
            initial_equity=config.initial_equity,
            commission_per_order=config.commission_per_trade,
        )

        # 3. Sort all candles by timestamp for chronological replay
        all_candles.sort(key=lambda c: (c.timestamp, c.symbol))

        # State tracking
        candle_buffer: dict[str, list[Candle]] = {sym: [] for sym in config.symbols}
        equity_curve_points: list[EquityCurvePoint] = []
        drawdown_curve: list[DrawdownPoint] = []
        signal_attributions: list[SignalAttribution] = []
        trades: list[BacktestTrade] = []
        bars_processed = 0
        signals_generated = 0
        signals_approved = 0
        peak_equity = config.initial_equity
        indicator_names: set[str] = set()
        # Required indicators from strategy
        required_indicators = self._signal_strategy.required_indicators()
        for req in required_indicators:
            indicator_names.add(req.indicator_name)

        # 4. Replay bars chronologically
        for candle in all_candles:
            bars_processed += 1

            # Update broker market price for this symbol
            broker.update_market_price(candle.symbol, candle.open)

            # Process pending orders (fills at this bar's open price)
            filled_responses = broker.process_pending_orders()

            # Record fills as BacktestTrade objects
            for fill_resp in filled_responses:
                if fill_resp.average_fill_price is not None:
                    # Apply slippage to the fill price
                    slippage_amount = self._compute_slippage(
                        fill_resp.average_fill_price,
                        fill_resp.filled_quantity,
                        config.slippage_pct,
                    )
                    effective_price = fill_resp.average_fill_price
                    if fill_resp.side == OrderSide.BUY:
                        effective_price += slippage_amount / max(
                            fill_resp.filled_quantity, Decimal("1")
                        )
                    else:
                        effective_price -= slippage_amount / max(
                            fill_resp.filled_quantity, Decimal("1")
                        )

                    # Deduct slippage from broker cash (broker doesn't model slippage natively)
                    # pylint: disable=protected-access
                    broker._cash -= slippage_amount

                    trade = BacktestTrade(
                        timestamp=candle.timestamp,
                        symbol=fill_resp.symbol,
                        side=fill_resp.side.value,
                        quantity=fill_resp.filled_quantity,
                        price=effective_price,
                        commission=config.commission_per_trade,
                        slippage=slippage_amount,
                    )
                    trades.append(trade)

            # Update broker market price to close for equity calculation
            broker.update_market_price(candle.symbol, candle.close)

            # Maintain candle buffer (max 500 bars per symbol)
            if candle.symbol in candle_buffer:
                buf = candle_buffer[candle.symbol]
                buf.append(candle)
                if len(buf) > 500:
                    candle_buffer[candle.symbol] = buf[-500:]

            # Compute indicators if strategy requires them
            indicators: dict[str, IndicatorResult] = {}
            if required_indicators and candle.symbol in candle_buffer:
                buf = candle_buffer[candle.symbol]
                if len(buf) >= 2:
                    indicators = self._indicator_engine.compute_batch(
                        required_indicators,
                        buf,
                    )

            # Get current position for this symbol
            positions = broker.get_positions()
            current_position = next(
                (p for p in positions if p.symbol == candle.symbol),
                None,
            )

            # Evaluate strategy
            signal = self._signal_strategy.evaluate(
                candle.symbol,
                candle_buffer.get(candle.symbol, [candle]),
                indicators,
                current_position,
                correlation_id=correlation_id,
            )

            # Process signal
            if signal is not None:
                signals_generated += 1
                signals_approved += 1

                # Build signal attribution
                trade_index = len(trades)  # Index of next trade that will be created
                attribution = SignalAttribution(
                    signal_id=signal.signal_id,
                    strategy_id=signal.strategy_id,
                    symbol=signal.symbol,
                    direction=signal.direction.value,
                    signal_type=signal.signal_type.value,
                    confidence=signal.confidence,
                    approved=True,
                    trade_index=trade_index,
                    bar_timestamp=candle.timestamp,
                    indicators_at_signal={
                        k: Decimal(str(v.values[-1]))
                        if len(v.values) > 0 and not math.isnan(float(v.values[-1]))
                        else None
                        for k, v in indicators.items()
                    },
                )
                signal_attributions.append(attribution)

                # Convert signal to order and submit
                self._submit_signal_order(
                    signal,
                    candle,
                    config,
                    broker,
                    correlation_id,
                )

            # Record equity curve point
            account = broker.get_account()
            current_equity = account.equity
            equity_curve_points.append(
                EquityCurvePoint(
                    timestamp=candle.timestamp,
                    equity=current_equity,
                )
            )

            # Track drawdown
            if current_equity > peak_equity:
                peak_equity = current_equity
            drawdown_pct = Decimal("0")
            if peak_equity > Decimal("0"):
                drawdown_pct = (
                    (current_equity - peak_equity) / peak_equity * Decimal("100")
                ).quantize(
                    Decimal("0.01"),
                    rounding=ROUND_HALF_UP,
                )
            drawdown_curve.append(
                DrawdownPoint(
                    timestamp=candle.timestamp,
                    drawdown_pct=drawdown_pct,
                )
            )

        # 5. Process any remaining pending orders at last bar close
        if all_candles:
            last_candle = all_candles[-1]
            broker.update_market_price(last_candle.symbol, last_candle.close)
            final_fills = broker.process_pending_orders()
            for fill_resp in final_fills:
                if fill_resp.average_fill_price is not None:
                    slippage_amount = self._compute_slippage(
                        fill_resp.average_fill_price,
                        fill_resp.filled_quantity,
                        config.slippage_pct,
                    )
                    trade = BacktestTrade(
                        timestamp=last_candle.timestamp,
                        symbol=fill_resp.symbol,
                        side=fill_resp.side.value,
                        quantity=fill_resp.filled_quantity,
                        price=fill_resp.average_fill_price,
                        commission=config.commission_per_trade,
                        slippage=slippage_amount,
                    )
                    trades.append(trade)

        # 6. Compute final metrics
        final_account = broker.get_account()
        final_equity = final_account.equity

        metrics = self._compute_metrics(
            config=config,
            final_equity=final_equity,
            trades=trades,
            equity_curve_points=equity_curve_points,
            drawdown_curve=drawdown_curve,
        )

        signal_summary = BacktestSignalSummary(
            signals_generated=signals_generated,
            signals_approved=signals_approved,
            signals_rejected=0,
            signal_attributions=signal_attributions,
            drawdown_curve=drawdown_curve,
            equity_curve_points=equity_curve_points,
        )

        result = BacktestResult(
            config=config,
            total_return_pct=metrics["total_return_pct"],
            annualized_return_pct=metrics["annualized_return_pct"],
            max_drawdown_pct=metrics["max_drawdown_pct"],
            sharpe_ratio=metrics["sharpe_ratio"],
            total_trades=len(trades),
            win_rate=metrics["win_rate"],
            profit_factor=metrics["profit_factor"],
            final_equity=final_equity,
            trades=trades,
            equity_curve=[],  # Full bar data not populated in M9 (equity_curve_points used instead)
            indicators_computed=sorted(indicator_names),
            bars_processed=bars_processed,
            signal_summary=signal_summary,
        )

        logger.info(
            "Backtest completed",
            strategy_id=config.strategy_id,
            bars_processed=bars_processed,
            total_trades=len(trades),
            total_return_pct=str(metrics["total_return_pct"]),
            sharpe_ratio=str(metrics["sharpe_ratio"]),
            max_drawdown_pct=str(metrics["max_drawdown_pct"]),
            correlation_id=correlation_id,
        )

        return result

    # ------------------------------------------------------------------
    # Internal: Fetch candles
    # ------------------------------------------------------------------

    def _fetch_candles(
        self,
        config: BacktestConfig,
        candle_interval: CandleInterval,
    ) -> list[Candle]:
        """
        Fetch historical candles for all symbols in the config.

        Includes lookback buffer days before start_date for indicator warm-up.

        Args:
            config: Backtest configuration.
            candle_interval: CandleInterval enum member.

        Returns:
            List of Candle objects across all symbols.
        """
        all_candles: list[Candle] = []
        buffer_start = datetime.combine(
            config.start_date - timedelta(days=config.lookback_buffer_days),
            datetime.min.time(),
        ).replace(tzinfo=timezone.utc)
        query_end = datetime.combine(
            config.end_date,
            datetime.max.time(),
        ).replace(tzinfo=timezone.utc)

        for symbol in config.symbols:
            query = MarketDataQuery(
                symbol=symbol,
                interval=candle_interval,
                start=buffer_start,
                end=query_end,
                limit=10000,
            )
            page = self._market_data_repository.query_candles(query)
            all_candles.extend(page.candles)

            # Paginate if needed
            while page.has_more and page.next_cursor:
                query = MarketDataQuery(
                    symbol=symbol,
                    interval=candle_interval,
                    start=buffer_start,
                    end=query_end,
                    limit=10000,
                    cursor=page.next_cursor,
                )
                page = self._market_data_repository.query_candles(query)
                all_candles.extend(page.candles)

        logger.debug(
            "Candles fetched for backtest",
            total_candles=len(all_candles),
            symbols=config.symbols,
        )
        return all_candles

    # ------------------------------------------------------------------
    # Internal: Submit order from signal
    # ------------------------------------------------------------------

    def _submit_signal_order(
        self,
        signal: Signal,
        candle: Candle,
        config: BacktestConfig,
        broker: PaperBrokerAdapter,
        correlation_id: str,
    ) -> None:
        """
        Convert a signal to an OrderRequest and submit to the broker.

        For LONG signals: submit a BUY market order.
        For SHORT/FLAT signals: submit a SELL market order to close position.

        Position sizing: uses a simple fixed-fraction approach — risk 2% of
        current equity per trade, with quantity = equity * 0.02 / price.
        Minimum 1 share.

        Args:
            signal: The trading signal to convert.
            candle: Current candle (used for price reference).
            config: Backtest configuration.
            broker: PaperBrokerAdapter for order submission.
            correlation_id: Correlation ID for tracing.
        """
        if signal.direction == SignalDirection.LONG:
            order_side = OrderSide.BUY
            # Size position: use fraction of equity
            account = broker.get_account()
            if candle.close > Decimal("0"):
                # Buy as many shares as equity allows (simple approach)
                max_shares = (account.cash * Decimal("0.95")) / candle.close
                quantity = max(
                    max_shares.quantize(Decimal("1"), rounding=ROUND_HALF_UP), Decimal("1")
                )
            else:
                quantity = Decimal("1")
        elif signal.direction in (SignalDirection.SHORT, SignalDirection.FLAT):
            order_side = OrderSide.SELL
            # Sell entire position
            positions = broker.get_positions()
            pos = next((p for p in positions if p.symbol == signal.symbol), None)
            if pos is None or pos.quantity <= Decimal("0"):
                return  # Nothing to sell
            quantity = pos.quantity
        else:
            return

        order = OrderRequest(
            client_order_id=f"ord-{ulid.ULID()!s}",
            symbol=signal.symbol,
            side=order_side,
            order_type=OrderType.MARKET,
            quantity=quantity,
            time_in_force=TimeInForce.DAY,
            deployment_id="backtest",
            strategy_id=config.strategy_id,
            correlation_id=correlation_id,
            execution_mode=ExecutionMode.PAPER,
        )
        broker.submit_order(order)

    # ------------------------------------------------------------------
    # Internal: Compute slippage
    # ------------------------------------------------------------------

    @staticmethod
    def _compute_slippage(
        fill_price: Decimal,
        quantity: Decimal,
        slippage_pct: Decimal,
    ) -> Decimal:
        """
        Compute slippage cost for a fill.

        Args:
            fill_price: Price at which the order was filled.
            quantity: Number of shares filled.
            slippage_pct: Slippage percentage (0-100).

        Returns:
            Slippage amount in dollars.

        Example:
            slippage = BacktestEngine._compute_slippage(
                Decimal("100"), Decimal("50"), Decimal("0.5"),
            )
            # slippage = 100 * 50 * 0.005 = 25.00
        """
        if slippage_pct <= Decimal("0"):
            return Decimal("0")
        return (fill_price * quantity * slippage_pct / Decimal("100")).quantize(
            Decimal("0.01"),
            rounding=ROUND_HALF_UP,
        )

    # ------------------------------------------------------------------
    # Internal: Compute performance metrics
    # ------------------------------------------------------------------

    def _compute_metrics(
        self,
        *,
        config: BacktestConfig,
        final_equity: Decimal,
        trades: list[BacktestTrade],
        equity_curve_points: list[EquityCurvePoint],
        drawdown_curve: list[DrawdownPoint],
    ) -> dict[str, Decimal]:
        """
        Compute aggregate performance metrics from backtest results.

        Args:
            config: Backtest configuration.
            final_equity: Final portfolio equity.
            trades: List of executed trades.
            equity_curve_points: Equity curve time series.
            drawdown_curve: Drawdown curve time series.

        Returns:
            Dict with keys: total_return_pct, annualized_return_pct,
            max_drawdown_pct, sharpe_ratio, win_rate, profit_factor.
        """
        initial = config.initial_equity

        # Total return
        if initial > Decimal("0"):
            total_return_pct = ((final_equity - initial) / initial * Decimal("100")).quantize(
                Decimal("0.01"),
                rounding=ROUND_HALF_UP,
            )
        else:
            total_return_pct = Decimal("0")

        # Annualized return
        days = (config.end_date - config.start_date).days
        if days > 0 and initial > Decimal("0"):
            total_return_ratio = float(final_equity / initial)
            if total_return_ratio > 0:
                annualized = (total_return_ratio ** (365.0 / days)) - 1.0
                annualized_return_pct = Decimal(str(annualized * 100)).quantize(
                    Decimal("0.01"),
                    rounding=ROUND_HALF_UP,
                )
            else:
                annualized_return_pct = Decimal("-100.00")
        else:
            annualized_return_pct = Decimal("0")

        # Max drawdown
        max_drawdown_pct = Decimal("0")
        for dd_point in drawdown_curve:
            if dd_point.drawdown_pct < max_drawdown_pct:
                max_drawdown_pct = dd_point.drawdown_pct

        # Win rate and profit factor from round-trip trades
        win_rate, profit_factor = self._compute_trade_metrics(trades)

        # Sharpe ratio (annualized, risk-free = 0)
        sharpe_ratio = self._compute_sharpe(equity_curve_points)

        return {
            "total_return_pct": total_return_pct,
            "annualized_return_pct": annualized_return_pct,
            "max_drawdown_pct": max_drawdown_pct,
            "sharpe_ratio": sharpe_ratio,
            "win_rate": win_rate,
            "profit_factor": profit_factor,
        }

    @staticmethod
    def _compute_trade_metrics(trades: list[BacktestTrade]) -> tuple[Decimal, Decimal]:
        """
        Compute win rate and profit factor from trade list.

        Pairs buy/sell trades for the same symbol into round trips.

        Args:
            trades: List of BacktestTrade objects.

        Returns:
            Tuple of (win_rate, profit_factor).
        """
        if not trades:
            return Decimal("0"), Decimal("0")

        # Pair buys with sells for round-trip P&L
        open_trades: dict[str, list[BacktestTrade]] = {}
        gross_profit = Decimal("0")
        gross_loss = Decimal("0")
        winners = 0
        total_round_trips = 0

        for trade in trades:
            if trade.side == "buy":
                open_trades.setdefault(trade.symbol, []).append(trade)
            elif trade.side == "sell":
                opens = open_trades.get(trade.symbol, [])
                if opens:
                    entry = opens.pop(0)
                    pnl = (trade.price - entry.price) * min(entry.quantity, trade.quantity)
                    pnl -= entry.commission + trade.commission
                    pnl -= entry.slippage + trade.slippage
                    total_round_trips += 1
                    if pnl > Decimal("0"):
                        gross_profit += pnl
                        winners += 1
                    else:
                        gross_loss += abs(pnl)

        if total_round_trips > 0:
            win_rate = Decimal(str(winners / total_round_trips)).quantize(
                Decimal("0.01"),
                rounding=ROUND_HALF_UP,
            )
        else:
            win_rate = Decimal("0")

        if gross_loss > Decimal("0"):
            profit_factor = (gross_profit / gross_loss).quantize(
                Decimal("0.01"),
                rounding=ROUND_HALF_UP,
            )
        elif gross_profit > Decimal("0"):
            # All winners, infinite profit factor — cap at 999
            profit_factor = Decimal("999.00")
        else:
            profit_factor = Decimal("0")

        return win_rate, profit_factor

    @staticmethod
    def _compute_sharpe(equity_curve_points: list[EquityCurvePoint]) -> Decimal:
        """
        Compute annualized Sharpe ratio from equity curve.

        Uses daily returns from equity curve points. Risk-free rate = 0.

        Args:
            equity_curve_points: Time series of equity values.

        Returns:
            Annualized Sharpe ratio as Decimal.
        """
        if len(equity_curve_points) < 2:
            return Decimal("0")

        # Compute daily returns
        returns: list[float] = []
        for i in range(1, len(equity_curve_points)):
            prev_eq = float(equity_curve_points[i - 1].equity)
            curr_eq = float(equity_curve_points[i].equity)
            if prev_eq > 0:
                returns.append((curr_eq - prev_eq) / prev_eq)

        if not returns:
            return Decimal("0")

        mean_return = sum(returns) / len(returns)
        if len(returns) < 2:
            return Decimal("0")

        variance = sum((r - mean_return) ** 2 for r in returns) / (len(returns) - 1)
        std_return = math.sqrt(variance)

        if std_return == 0:
            return Decimal("0")

        # Annualize: assuming 252 trading days
        sharpe = (mean_return / std_return) * math.sqrt(252)
        return Decimal(str(sharpe)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    # ------------------------------------------------------------------
    # Internal: Empty result for no-data cases
    # ------------------------------------------------------------------

    @staticmethod
    def _empty_result(config: BacktestConfig) -> BacktestResult:
        """
        Build an empty BacktestResult for cases with no candle data.

        Args:
            config: Backtest configuration.

        Returns:
            BacktestResult with zero metrics and empty collections.
        """
        return BacktestResult(
            config=config,
            total_return_pct=Decimal("0"),
            annualized_return_pct=Decimal("0"),
            max_drawdown_pct=Decimal("0"),
            sharpe_ratio=Decimal("0"),
            total_trades=0,
            win_rate=Decimal("0"),
            profit_factor=Decimal("0"),
            final_equity=config.initial_equity,
            trades=[],
            equity_curve=[],
            indicators_computed=[],
            bars_processed=0,
            signal_summary=BacktestSignalSummary(
                signals_generated=0,
                signals_approved=0,
                signals_rejected=0,
            ),
        )
