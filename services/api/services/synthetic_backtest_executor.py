"""
Synthetic backtest executor (M2.D3 wire-up of the M3.X1 pipeline).

Purpose:
    Provide a reusable orchestration class that drives a single Strategy IR
    through the deterministic synthetic-FX backtest pipeline (the same
    pipeline the M3.X1 CLI uses) and returns a populated
    :class:`libs.contracts.backtest.BacktestResult`. This is the engine
    the API layer calls from ``POST /runs/from-ir`` so the M2.C3 GET
    sub-resources (equity-curve, blotter, metrics) return real data
    instead of empty bodies.

    The executor is a pure orchestrator -- it owns no state, holds no
    locks, and never writes to disk. Persistence of the resulting
    BacktestResult onto a ResearchRunRecord is the caller's
    responsibility (see :class:`ResearchRunService.submit_from_ir`).

Pipeline (one bar at a time, in chronological order):
    1.  Sanitise the raw IR dict via the M3.X1 CLI's
        :class:`services.cli.run_synthetic_backtest._IRPreprocessor`
        and validate the result via
        :class:`libs.contracts.strategy_ir.StrategyIR`.
    2.  Resolve symbols (intersection of caller-supplied symbols and the
        synthetic provider's supported set) and timeframe (normalised
        IR primary timeframe).
    3.  Construct
        :class:`libs.strategy_ir.synthetic_market_data_provider.SyntheticFxMarketDataProvider`
        seeded with ``seed`` and
        :class:`libs.strategy_ir.paper_broker_adapter.PaperBrokerAdapter`
        with the requested starting balance.
    4.  Compile the IR via :class:`StrategyIRCompiler` (with a
        :class:`NullBroker` for the compiler's pip-value port and a
        fresh :class:`BarClock`).
    5.  Replay every bar in chronological order: submit the bar to the
        broker first (so any pending market order from the previous bar
        fills at this bar's open), evaluate the compiled strategy, then
        translate emitted signals into paper-broker orders. Sample the
        broker's mark-to-market equity once per processed bar.
    6.  Pair entry/exit fills into round-trip trades, build the equity
        curve, compute headline metrics, and return a frozen
        :class:`BacktestResult`.

Determinism contract:
    Same IR + same symbols + same window + same seed = byte-identical
    BacktestResult.trades and BacktestResult.equity_curve. The executor
    never reads a wall clock and never calls a random number generator
    of its own; all randomness flows from the seed through the synthetic
    provider.

Responsibilities:
    - Orchestrate the IR + provider + broker + indicator engine into
      a single deterministic backtest.
    - Convert paper-broker fills into a chronological list of
      :class:`BacktestTrade` objects (one entry-row + one exit-row per
      paired round-trip).
    - Sample portfolio equity per processed bar into a list of
      :class:`BacktestBar` objects so the M2.C3 equity-curve endpoint
      has data to project.
    - Compute headline metrics (total_return_pct, max_drawdown_pct,
      sharpe_ratio, win_rate, profit_factor) from the closed-trade
      list and the equity curve.

Does NOT:
    - Touch the network, an external broker, or any database.
    - Persist anything. The caller (ResearchRunService) is responsible
      for saving the resulting BacktestResult onto a
      ResearchRunRecord.
    - Provide any kind of asynchronous / background execution mode.
      Execution is synchronous and blocking; the caller decides whether
      to dispatch it on a thread pool or background task.
    - Run a real risk gate, signal-summary attribution pipeline, or
      paper-fill commission model. The executor is the deterministic
      synthetic-data smoke path the API uses while the production
      backtest engine (M3.X2 viable-candidate path) is being built.

Dependencies (all imported, none injected):
    - :mod:`services.cli.run_synthetic_backtest`: shares its
      ``_IRPreprocessor``, ``_IRIndicatorComputer``, ``_TradePairer``,
      ``_resolve_symbols``, ``_resolve_timeframe``,
      ``_position_snapshot``, ``_signal_to_order_side``,
      ``_PAPER_ORDER_UNITS``, and ``SyntheticBacktestError`` so the
      CLI and executor never drift.
    - :mod:`libs.strategy_ir.compiler`,
      :mod:`libs.strategy_ir.clock`,
      :mod:`libs.strategy_ir.broker`,
      :mod:`libs.strategy_ir.paper_broker_adapter`,
      :mod:`libs.strategy_ir.synthetic_market_data_provider`.
    - :mod:`libs.contracts.backtest` for the result/trade/bar contracts.

Raises:
    - :class:`services.cli.run_synthetic_backtest.SyntheticBacktestError`:
      any expected failure (IR fails to compile, no candles produced,
      paper broker rejects an order, etc.). The caller catches this and
      transitions the run to FAILED.

Example::

    from services.api.services.synthetic_backtest_executor import (
        SyntheticBacktestExecutor,
        SyntheticBacktestRequest,
    )

    executor = SyntheticBacktestExecutor()
    result = executor.execute(
        SyntheticBacktestRequest(
            strategy_ir_dict=ir_json,
            symbols=["EURUSD"],
            timeframe="H1",
            start=date(2026, 1, 1),
            end=date(2026, 3, 1),
            seed=42,
        )
    )
    assert result.total_trades >= 0
    assert result.equity_curve  # one BacktestBar per processed bar
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any

import structlog

from libs.contracts.backtest import (
    BacktestBar,
    BacktestConfig,
    BacktestResult,
    BacktestTrade,
)
from libs.contracts.market_data import Candle
from libs.contracts.strategy_ir import StrategyIR
from libs.strategy_ir.broker import NullBroker
from libs.strategy_ir.clock import BarClock
from libs.strategy_ir.compiler import IRStrategy, StrategyIRCompiler
from libs.strategy_ir.interfaces.broker_adapter_interface import OrderType
from libs.strategy_ir.paper_broker_adapter import PaperBrokerAdapter
from libs.strategy_ir.synthetic_market_data_provider import (
    SyntheticFxMarketDataProvider,
)
from services.cli.run_synthetic_backtest import (
    _PAPER_ORDER_UNITS,
    SyntheticBacktestError,
    _IRIndicatorComputer,
    _IRPreprocessor,
    _position_snapshot,
    _resolve_symbols,
    _resolve_timeframe,
    _signal_to_order_side,
    _TradePairer,
    _TradeRecord,
)

logger = structlog.get_logger(__name__)


# ---------------------------------------------------------------------------
# Inputs (frozen dataclass; not on the wire)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SyntheticBacktestRequest:
    """
    Self-describing input bundle for :meth:`SyntheticBacktestExecutor.execute`.

    Carrying these as a frozen dataclass (rather than as positional or
    keyword args) keeps the call site readable when six or more
    parameters are needed and lets callers introspect what they passed
    when they file a bug.

    Attributes:
        strategy_ir_dict: Raw IR dict (e.g. ``json.loads(ir_json)``).
            Will be sanitised via :class:`_IRPreprocessor` then
            validated via :class:`StrategyIR`.
        symbols: Caller-supplied symbol list. Intersected with the
            synthetic provider's supported set internally; pass the IR
            universe symbols (or a subset) here. An empty list falls
            back to the IR's own ``universe.symbols``.
        timeframe: IR-style timeframe label (e.g. ``"H1"`` or ``"4h"``).
            Normalised by the CLI's ``_resolve_timeframe`` helper.
        start: Inclusive UTC start date for the replay window.
        end: Inclusive UTC end date for the replay window.
        seed: Master seed for the synthetic provider; same seed =
            byte-identical output.
        starting_balance: Paper-broker starting balance in the broker's
            account currency (USD). Defaults to 100000.
        deployment_id: Deployment id stamped on every emitted Signal.
            Defaults to ``"m2d3-executor"`` so server-side logs are
            distinguishable from the M3.X1 CLI's ``"m3x1-cli"`` runs.
    """

    strategy_ir_dict: dict[str, Any]
    symbols: list[str]
    timeframe: str
    start: date
    end: date
    seed: int
    starting_balance: Decimal = Decimal("100000")
    deployment_id: str = "m2d3-executor"


# ---------------------------------------------------------------------------
# Executor
# ---------------------------------------------------------------------------


class SyntheticBacktestExecutor:
    """
    Stateless orchestrator that runs one IR through the synthetic
    backtest pipeline.

    Responsibilities:
        - Drive the M3.X1 pipeline end-to-end and return a populated
          :class:`BacktestResult`.

    Does NOT:
        - Persist results.
        - Hold any per-run mutable state on ``self`` (each call to
          :meth:`execute` constructs its own provider, broker, and
          compiled strategy).
        - Write to stdout or stderr. The CLI wraps the executor for
          that.

    Dependencies:
        - :mod:`services.cli.run_synthetic_backtest` helpers (shared
          with the CLI so behaviour cannot drift).

    Example::

        executor = SyntheticBacktestExecutor()
        result = executor.execute(
            SyntheticBacktestRequest(
                strategy_ir_dict=ir_dict,
                symbols=["EURUSD"],
                timeframe="H1",
                start=date(2026, 1, 1),
                end=date(2026, 3, 1),
                seed=42,
            )
        )
    """

    def execute(self, request: SyntheticBacktestRequest) -> BacktestResult:
        """
        Run one synthetic backtest end-to-end and return the result.

        Args:
            request: All inputs needed to drive the pipeline.

        Returns:
            A frozen :class:`BacktestResult` populated with:
              * ``trades``: chronological list of :class:`BacktestTrade`
                rows (entry + exit row per paired round-trip).
              * ``equity_curve``: list of :class:`BacktestBar` samples
                (one per processed bar across all symbols).
              * Headline metrics: ``total_return_pct``,
                ``max_drawdown_pct``, ``sharpe_ratio``, ``win_rate``,
                ``profit_factor``, ``total_trades``, ``final_equity``,
                ``bars_processed``.
              * ``config``: a :class:`BacktestConfig` describing the
                replay window and resolved symbol set.

        Raises:
            SyntheticBacktestError: when the IR fails to validate or
                compile, the resolved symbol set is empty, the synthetic
                provider returns no candles for the window, or the
                paper broker rejects an order. The caller is expected
                to catch this and transition the run to FAILED.
        """
        # 1. Validate window. Fail fast on bad inputs before constructing
        #    any expensive collaborator.
        if request.end < request.start:
            raise SyntheticBacktestError(f"end ({request.end}) precedes start ({request.start})")

        # 2. Sanitise + validate the IR. The preprocessor deep-copies
        #    so the caller's dict is untouched.
        sanitised, _report = _IRPreprocessor().sanitize(request.strategy_ir_dict)
        try:
            ir = StrategyIR.model_validate(sanitised)
        except Exception as exc:
            raise SyntheticBacktestError(
                f"IR failed schema validation: {type(exc).__name__}: {exc}"
            ) from exc

        # 3. Resolve symbols and timeframe via the CLI's helpers so the
        #    intersection rules (synthetic-supported pairs only) stay
        #    identical between CLI and API call sites. _resolve_symbols
        #    accepts a comma-separated override OR None to fall back to
        #    ir.universe.symbols.
        override = ",".join(request.symbols) if request.symbols else None
        symbols = _resolve_symbols(ir, override)
        timeframe = _resolve_timeframe(ir, request.timeframe)

        # 4. Build the synthetic provider, paper broker, and compiled
        #    IR strategy. Each call to execute() gets its own instances
        #    so two concurrent executions are fully isolated.
        provider = SyntheticFxMarketDataProvider(seed=request.seed)
        broker = PaperBrokerAdapter(
            starting_balance=request.starting_balance,
            market_data=provider,
        )
        clock = BarClock()
        try:
            compiled: IRStrategy = StrategyIRCompiler(clock=clock, broker=NullBroker()).compile(
                ir, deployment_id=request.deployment_id
            )
        except Exception as exc:
            raise SyntheticBacktestError(
                f"IR compilation failed: {type(exc).__name__}: {exc}"
            ) from exc

        indicator_computer = _IRIndicatorComputer(ir.indicators)
        pairer = _TradePairer()

        # 5. Fetch bars per symbol, sort chronologically, replay.
        start_dt = datetime.combine(request.start, datetime.min.time(), tzinfo=timezone.utc)
        end_dt = datetime.combine(request.end, datetime.min.time(), tzinfo=timezone.utc)

        all_candles: list[Candle] = []
        for symbol in symbols:
            bars = provider.fetch_bars(
                symbol=symbol,
                timeframe=timeframe,
                start=start_dt,
                end=end_dt,
            )
            all_candles.extend(bars)
        if not all_candles:
            raise SyntheticBacktestError(
                f"synthetic provider returned no candles for symbols={symbols} "
                f"timeframe={timeframe!r} window=[{request.start}..{request.end}]"
            )
        # Stable, deterministic ordering: timestamp first then symbol.
        all_candles.sort(key=lambda c: (c.timestamp, c.symbol))

        per_symbol_buf: dict[str, list[Candle]] = {sym: [] for sym in symbols}
        equity_samples: list[BacktestBar] = []
        extension_counter = 0
        correlation_id = f"m2d3-executor-{request.seed}"
        bars_processed = 0

        for candle in all_candles:
            symbol = candle.symbol
            buf = per_symbol_buf[symbol]
            buf.append(candle)
            if len(buf) > 600:
                del buf[: len(buf) - 600]

            # Submit the bar to the broker FIRST so any pending market
            # order placed last bar fills at THIS bar's open. The
            # compiled strategy then evaluates against the same bar,
            # mirroring the BacktestEngine ordering and the M3.X1.5
            # parity precondition.
            fills = broker.submit_bar(symbol, candle)
            for fill in fills:
                pairer.record_fill(fill, candle.timestamp)

            indicators = indicator_computer.compute(buf)
            position_snapshot = _position_snapshot(broker, symbol, candle)

            signal = compiled.evaluate(
                symbol,
                buf,
                indicators,
                position_snapshot,
                correlation_id=correlation_id,
            )

            # Sample equity per processed bar AFTER fills have been
            # recorded so the curve reflects the latest realised PnL.
            equity = self._mark_to_market_equity(broker, symbol, candle)
            equity_samples.append(
                BacktestBar(
                    timestamp=candle.timestamp,
                    symbol=symbol,
                    open=candle.open,
                    high=candle.high,
                    low=candle.low,
                    close=candle.close,
                    volume=int(candle.volume),
                    equity=equity,
                )
            )
            bars_processed += 1

            if signal is None:
                continue

            side = _signal_to_order_side(signal.signal_type, signal.direction, position_snapshot)
            if side is None:
                # Exit signal with no open position; skip rather than
                # placing a phantom order.
                continue
            extension_counter += 1
            ext_id = f"{correlation_id}-{extension_counter:08d}"
            try:
                broker.place_order(
                    symbol,
                    side,
                    _PAPER_ORDER_UNITS,
                    order_type=OrderType.MARKET,
                    client_extension_id=ext_id,
                )
            except Exception as exc:
                raise SyntheticBacktestError(
                    f"paper-broker rejected order for {symbol} on bar "
                    f"{candle.timestamp.isoformat()}: {type(exc).__name__}: {exc}"
                ) from exc

        # 6. Finalise: build the BacktestResult from the trade pairer's
        #    output plus the equity series we collected.
        trade_records = pairer.finalise()
        backtest_trades = self._records_to_backtest_trades(trade_records)
        ending_balance = broker.realized_balance()
        metrics = self._compute_metrics(
            trade_records=trade_records,
            ending_balance=ending_balance,
            starting_balance=request.starting_balance,
            equity_samples=equity_samples,
        )

        config = BacktestConfig(
            strategy_id=ir.metadata.strategy_name or "synthetic-backtest",
            symbols=symbols,
            start_date=request.start,
            end_date=request.end,
        )

        result = BacktestResult(
            config=config,
            total_return_pct=metrics["total_return_pct"],
            annualized_return_pct=metrics["annualized_return_pct"],
            max_drawdown_pct=metrics["max_drawdown_pct"],
            sharpe_ratio=metrics["sharpe_ratio"],
            total_trades=metrics["total_trades"],
            win_rate=metrics["win_rate"],
            profit_factor=metrics["profit_factor"],
            final_equity=ending_balance,
            trades=backtest_trades,
            equity_curve=equity_samples,
            indicators_computed=[ind.id for ind in ir.indicators],
            bars_processed=bars_processed,
        )

        logger.info(
            "synthetic_backtest.execute.completed",
            symbols=symbols,
            timeframe=timeframe,
            seed=request.seed,
            bars_processed=bars_processed,
            trade_count=len(backtest_trades),
            equity_points=len(equity_samples),
            total_return_pct=str(metrics["total_return_pct"]),
            component="synthetic_backtest_executor",
        )

        return result

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _mark_to_market_equity(broker: PaperBrokerAdapter, symbol: str, candle: Candle) -> Decimal:
        """
        Return the broker's realised balance plus any open position's
        unrealised PnL at the candle's close.

        Args:
            broker: Source of position state and realised balance.
            symbol: The bar's instrument.
            candle: The bar being sampled.

        Returns:
            Decimal equity value, never negative (clamped to 0 to
            satisfy :class:`BacktestBar`'s ``Field(ge=0)``).
        """
        realized = broker.realized_balance()
        pos = broker.get_position(symbol)
        if pos is None or pos.units == 0:
            return realized if realized >= Decimal("0") else Decimal("0")
        quantity = Decimal(pos.units)
        unrealised = (candle.close - pos.average_price) * quantity
        equity = realized + unrealised
        if equity < Decimal("0"):
            return Decimal("0")
        return equity

    @staticmethod
    def _records_to_backtest_trades(
        records: list[_TradeRecord],
    ) -> list[BacktestTrade]:
        """
        Convert paired :class:`_TradeRecord`s into a flat chronological
        list of :class:`BacktestTrade` rows the M2.C3 blotter endpoint
        can paginate.

        Each closed round-trip produces TWO rows: an entry row stamped
        with the entry fill, and an exit row stamped with the exit
        fill. Open positions at end-of-stream produce a single entry
        row -- consumers detect them by the absence of an exit row at
        a later timestamp for the same symbol.

        The two-row encoding mirrors how a production blotter records
        every fill (one row per fill, paired up via order ids upstream).
        """
        out: list[BacktestTrade] = []
        for record in records:
            entry_side = "buy" if record.side == "long" else "sell"
            out.append(
                BacktestTrade(
                    timestamp=record.entry_timestamp,
                    symbol=record.symbol,
                    side=entry_side,
                    quantity=Decimal(record.units),
                    price=record.entry_price,
                )
            )
            if record.exit_timestamp is None or record.exit_price is None:
                continue
            exit_side = "sell" if record.side == "long" else "buy"
            out.append(
                BacktestTrade(
                    timestamp=record.exit_timestamp,
                    symbol=record.symbol,
                    side=exit_side,
                    quantity=Decimal(record.units),
                    price=record.exit_price,
                )
            )
        # Sort chronologically so the blotter endpoint's stable sort
        # has a clean input. Tie-break on symbol then side for full
        # determinism.
        out.sort(key=lambda t: (t.timestamp, t.symbol, t.side))
        return out

    @staticmethod
    def _compute_metrics(
        *,
        trade_records: list[_TradeRecord],
        ending_balance: Decimal,
        starting_balance: Decimal,
        equity_samples: list[BacktestBar],
    ) -> dict[str, Any]:
        """
        Compute headline metrics from the trade pairer's output.

        Returns:
            Dict keyed by BacktestResult field name with Decimal /
            int values ready to feed into the BacktestResult
            constructor.

        Notes:
            * total_return_pct / annualized_return_pct are computed from
              starting -> ending balance only (no time-weighting -- this
              is the synthetic smoke path, not a production performance
              attribution).
            * max_drawdown_pct is computed from the equity sample series
              and clamped to <= 0 because BacktestResult.max_drawdown_pct
              is constrained ``Field(le=0)``.
            * sharpe_ratio uses sample stdev (ddof=1) of per-trade PnL
              and is 0 when fewer than 2 closed trades or zero variance.
            * profit_factor is gross_profit / gross_loss; surfaces 0
              when there are no losing trades (undefined ratio).
        """
        closed = [t for t in trade_records if t.pnl is not None]
        total_trades = len(closed)
        wins = sum(1 for t in closed if t.pnl is not None and t.pnl > Decimal(0))
        win_rate = Decimal(wins) / Decimal(total_trades) if total_trades else Decimal("0")

        if starting_balance > Decimal("0"):
            total_return = (ending_balance - starting_balance) / starting_balance * Decimal("100")
        else:
            total_return = Decimal("0")
        # Annualised return placeholder: synthetic windows are short so
        # we pass through the raw total_return rather than annualising
        # against the bar window. The value is still meaningful for
        # comparison across runs over the same window.
        annualised = total_return

        # Max drawdown from the equity sample series, walking the curve
        # and tracking the running peak.
        max_dd = Decimal("0")
        peak = starting_balance
        for sample in equity_samples:
            if sample.equity > peak:
                peak = sample.equity
            if peak > Decimal("0"):
                dd_pct = (sample.equity - peak) / peak * Decimal("100")
                if dd_pct < max_dd:
                    max_dd = dd_pct

        # Sharpe ratio: per-trade-PnL Sharpe (mean / stdev * sqrt(N))
        # using sample stdev. Returns 0 for fewer than 2 trades.
        if total_trades < 2:
            sharpe = Decimal("0")
        else:
            pnls = [float(t.pnl) for t in closed if t.pnl is not None]
            mean = sum(pnls) / len(pnls)
            var = sum((p - mean) ** 2 for p in pnls) / (len(pnls) - 1)
            if var <= 0.0:
                sharpe = Decimal("0")
            else:
                sharpe_float = mean / math.sqrt(var) * math.sqrt(len(pnls))
                # Quantize to 6 places so the wire shape is stable.
                sharpe = Decimal(str(round(sharpe_float, 6)))

        gross_profit = sum(
            (t.pnl for t in closed if t.pnl is not None and t.pnl > Decimal("0")),
            Decimal("0"),
        )
        gross_loss = sum(
            (-t.pnl for t in closed if t.pnl is not None and t.pnl < Decimal("0")),
            Decimal("0"),
        )
        # No losing trades -> profit factor undefined. Surface as 0 to
        # keep BacktestResult.profit_factor's Field(ge=0) happy while
        # clearly distinguishable from a real ratio.
        profit_factor = gross_profit / gross_loss if gross_loss > Decimal("0") else Decimal("0")

        return {
            "total_return_pct": total_return,
            "annualized_return_pct": annualised,
            "max_drawdown_pct": max_dd,
            "sharpe_ratio": sharpe,
            "total_trades": total_trades,
            "win_rate": win_rate,
            "profit_factor": profit_factor,
        }


__all__ = [
    "SyntheticBacktestExecutor",
    "SyntheticBacktestRequest",
    "SyntheticBacktestError",
]
