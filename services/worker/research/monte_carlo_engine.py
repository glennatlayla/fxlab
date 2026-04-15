"""
Monte Carlo simulation engine — confidence intervals and risk metrics (M11).

Responsibilities:
- Run N Monte Carlo simulations on a BacktestResult's trade sequence.
- Support trade sequence resampling and return bootstrapping methods.
- Compute confidence intervals for equity, drawdown, and Sharpe.
- Calculate probability of ruin (equity below threshold).
- Support deterministic seeding for reproducibility.

Does NOT:
- Run backtests (receives completed BacktestResult).
- Persist results (caller responsibility).
- Implement trading strategies.

Dependencies:
- numpy: Array operations for efficient simulation.
- libs.contracts.backtest: BacktestResult, BacktestTrade.
- libs.contracts.monte_carlo: MonteCarloConfig, MonteCarloResult.

Error conditions:
- ValueError: if trade resample method used with zero trades.

Example:
    engine = MonteCarloEngine()
    config = MonteCarloConfig(num_simulations=10000, random_seed=42)
    result = engine.run(backtest_result, config)
    print(f"P(ruin): {result.probability_of_ruin:.2%}")
    print(f"Median equity: {result.median_final_equity:.2f}")
"""

from __future__ import annotations

import numpy as np
import structlog

from libs.contracts.backtest import BacktestResult
from libs.contracts.interfaces.monte_carlo_engine import MonteCarloEngineInterface
from libs.contracts.monte_carlo import MonteCarloConfig, MonteCarloResult, SimulationMethod

logger = structlog.get_logger(__name__)


class MonteCarloEngine(MonteCarloEngineInterface):
    """
    Monte Carlo simulation engine for backtest statistical validation.

    Generates N alternative equity paths by either shuffling the trade
    sequence (TRADE_RESAMPLE) or resampling returns with replacement
    (RETURN_BOOTSTRAP), then computes percentile-based confidence
    intervals and probability of ruin.

    Responsibilities:
    - Parse trades from BacktestResult into P&L arrays.
    - Run N simulations with the configured method.
    - Compute per-simulation: final equity, max drawdown, Sharpe, losing streak.
    - Aggregate into percentile-based confidence intervals.
    - Calculate probability of ruin.

    Does NOT:
    - Run or modify backtests.
    - Persist results.

    Thread safety:
    - Thread-safe: each run() call creates its own RNG and local arrays.

    Example:
        engine = MonteCarloEngine()
        result = engine.run(bt_result, MonteCarloConfig(random_seed=42))
    """

    def run(
        self,
        backtest_result: BacktestResult,
        config: MonteCarloConfig,
    ) -> MonteCarloResult:
        """
        Execute Monte Carlo simulation on a backtest result.

        Args:
            backtest_result: Completed backtest with trades.
            config: Simulation configuration.

        Returns:
            MonteCarloResult with confidence intervals and ruin probability.

        Example:
            result = engine.run(bt_result, MonteCarloConfig())
        """
        initial_equity = float(backtest_result.config.initial_equity)
        trades = backtest_result.trades
        rng = np.random.default_rng(config.random_seed)

        logger.info(
            "Monte Carlo simulation started",
            num_simulations=config.num_simulations,
            method=config.method.value,
            num_trades=len(trades),
            initial_equity=initial_equity,
        )

        # Handle zero trades: all simulations return initial equity
        if not trades:
            return self._zero_trade_result(config, initial_equity)

        # Compute per-trade P&L from round trips
        trade_pnls = self._compute_trade_pnls(trades)

        # If no P&L changes (e.g., only buy trades with no sells), return initial
        if not trade_pnls:
            return self._zero_trade_result(config, initial_equity, num_trades=len(trades))

        # Run simulations
        if config.method == SimulationMethod.TRADE_RESAMPLE:
            sim_results = self._run_trade_resample(
                trade_pnls,
                initial_equity,
                config.num_simulations,
                rng,
            )
        else:
            # RETURN_BOOTSTRAP: compute returns from trade PnLs
            sim_results = self._run_return_bootstrap(
                trade_pnls,
                initial_equity,
                config.num_simulations,
                rng,
            )

        # Compute confidence intervals and metrics
        return self._build_result(
            config=config,
            num_trades=len(trades),
            initial_equity=initial_equity,
            sim_results=sim_results,
        )

    # ------------------------------------------------------------------
    # Internal: Compute trade P&Ls
    # ------------------------------------------------------------------

    @staticmethod
    def _compute_trade_pnls(trades: list) -> list[float]:
        """
        Extract P&L from round-trip trade pairs.

        Pairs buy→sell trades for each symbol. Each pair produces a P&L:
        (sell_price - buy_price) * quantity - commission - slippage.

        Args:
            trades: List of BacktestTrade objects.

        Returns:
            List of float P&L values per round trip.
        """
        open_trades: dict[str, list] = {}
        pnls: list[float] = []

        for trade in trades:
            if trade.side == "buy":
                open_trades.setdefault(trade.symbol, []).append(trade)
            elif trade.side == "sell":
                opens = open_trades.get(trade.symbol, [])
                if opens:
                    entry = opens.pop(0)
                    qty = min(float(entry.quantity), float(trade.quantity))
                    pnl = (float(trade.price) - float(entry.price)) * qty
                    pnl -= float(entry.commission) + float(trade.commission)
                    pnl -= float(entry.slippage) + float(trade.slippage)
                    pnls.append(pnl)

        return pnls

    # ------------------------------------------------------------------
    # Internal: Trade resample simulation
    # ------------------------------------------------------------------

    @staticmethod
    def _run_trade_resample(
        trade_pnls: list[float],
        initial_equity: float,
        num_simulations: int,
        rng: np.random.Generator,
    ) -> dict[str, np.ndarray]:
        """
        Run trade sequence resampling simulations.

        For each simulation, shuffle the trade P&L sequence and compute
        the cumulative equity path.

        Args:
            trade_pnls: P&L per round trip.
            initial_equity: Starting equity.
            num_simulations: Number of iterations.
            rng: NumPy random generator.

        Returns:
            Dict with arrays: final_equities, max_drawdowns, sharpes,
            losing_streaks.
        """
        pnl_array = np.array(trade_pnls)

        final_equities = np.empty(num_simulations)
        max_drawdowns = np.empty(num_simulations)
        sharpes = np.empty(num_simulations)
        losing_streaks = np.empty(num_simulations)

        for i in range(num_simulations):
            # Shuffle trade order
            shuffled = rng.permutation(pnl_array)

            # Compute equity path
            equity = initial_equity + np.cumsum(shuffled)
            equity_with_init = np.concatenate([[initial_equity], equity])

            final_equities[i] = equity_with_init[-1]

            # Max drawdown
            peak = np.maximum.accumulate(equity_with_init)
            drawdowns = (equity_with_init - peak) / np.where(peak > 0, peak, 1)
            max_drawdowns[i] = np.min(drawdowns)

            # Sharpe (from trade returns)
            returns = shuffled / np.where(equity_with_init[:-1] > 0, equity_with_init[:-1], 1)
            if len(returns) > 1 and np.std(returns) > 0:
                sharpes[i] = (np.mean(returns) / np.std(returns)) * np.sqrt(252)
            else:
                sharpes[i] = 0.0

            # Longest losing streak
            losing = (shuffled < 0).astype(int)
            max_streak = 0
            current_streak = 0
            for val in losing:
                if val:
                    current_streak += 1
                    max_streak = max(max_streak, current_streak)
                else:
                    current_streak = 0
            losing_streaks[i] = max_streak

        return {
            "final_equities": final_equities,
            "max_drawdowns": max_drawdowns,
            "sharpes": sharpes,
            "losing_streaks": losing_streaks,
        }

    # ------------------------------------------------------------------
    # Internal: Return bootstrap simulation
    # ------------------------------------------------------------------

    @staticmethod
    def _run_return_bootstrap(
        trade_pnls: list[float],
        initial_equity: float,
        num_simulations: int,
        rng: np.random.Generator,
    ) -> dict[str, np.ndarray]:
        """
        Run return bootstrapping simulations.

        Resamples trade P&Ls with replacement to create alternative
        trade sequences of the same length.

        Args:
            trade_pnls: P&L per round trip.
            initial_equity: Starting equity.
            num_simulations: Number of iterations.
            rng: NumPy random generator.

        Returns:
            Same dict structure as _run_trade_resample.
        """
        pnl_array = np.array(trade_pnls)
        num_pnls = len(pnl_array)

        final_equities = np.empty(num_simulations)
        max_drawdowns = np.empty(num_simulations)
        sharpes = np.empty(num_simulations)
        losing_streaks = np.empty(num_simulations)

        for i in range(num_simulations):
            # Resample with replacement
            indices = rng.integers(0, num_pnls, size=num_pnls)
            resampled = pnl_array[indices]

            # Compute equity path
            equity = initial_equity + np.cumsum(resampled)
            equity_with_init = np.concatenate([[initial_equity], equity])

            final_equities[i] = equity_with_init[-1]

            # Max drawdown
            peak = np.maximum.accumulate(equity_with_init)
            drawdowns = (equity_with_init - peak) / np.where(peak > 0, peak, 1)
            max_drawdowns[i] = np.min(drawdowns)

            # Sharpe
            returns = resampled / np.where(equity_with_init[:-1] > 0, equity_with_init[:-1], 1)
            if len(returns) > 1 and np.std(returns) > 0:
                sharpes[i] = (np.mean(returns) / np.std(returns)) * np.sqrt(252)
            else:
                sharpes[i] = 0.0

            # Longest losing streak
            losing = (resampled < 0).astype(int)
            max_streak = 0
            current_streak = 0
            for val in losing:
                if val:
                    current_streak += 1
                    max_streak = max(max_streak, current_streak)
                else:
                    current_streak = 0
            losing_streaks[i] = max_streak

        return {
            "final_equities": final_equities,
            "max_drawdowns": max_drawdowns,
            "sharpes": sharpes,
            "losing_streaks": losing_streaks,
        }

    # ------------------------------------------------------------------
    # Internal: Build result from simulation arrays
    # ------------------------------------------------------------------

    def _build_result(
        self,
        *,
        config: MonteCarloConfig,
        num_trades: int,
        initial_equity: float,
        sim_results: dict[str, np.ndarray],
    ) -> MonteCarloResult:
        """
        Build MonteCarloResult from simulation output arrays.

        Args:
            config: Simulation configuration.
            num_trades: Number of trades in source backtest.
            initial_equity: Starting equity.
            sim_results: Dict of simulation output arrays.

        Returns:
            MonteCarloResult with confidence intervals.
        """
        final_equities = sim_results["final_equities"]
        max_drawdowns = sim_results["max_drawdowns"]
        sharpes = sim_results["sharpes"]
        losing_streaks = sim_results["losing_streaks"]

        # Percentile labels
        percentile_map = {level: f"p{int(level * 100)}" for level in config.confidence_levels}
        percentile_values = [level * 100 for level in config.confidence_levels]

        # Equity percentiles
        eq_pcts = np.percentile(final_equities, percentile_values)
        equity_percentiles = {
            percentile_map[level]: round(float(val), 2)
            for level, val in zip(config.confidence_levels, eq_pcts, strict=True)
        }

        # Max drawdown percentiles
        dd_pcts = np.percentile(max_drawdowns, percentile_values)
        max_drawdown_percentiles = {
            percentile_map[level]: round(float(val), 4)
            for level, val in zip(config.confidence_levels, dd_pcts, strict=True)
        }

        # Sharpe percentiles
        sh_pcts = np.percentile(sharpes, percentile_values)
        sharpe_percentiles = {
            percentile_map[level]: round(float(val), 4)
            for level, val in zip(config.confidence_levels, sh_pcts, strict=True)
        }

        # Losing streak percentiles
        ls_pcts = np.percentile(losing_streaks, percentile_values)
        losing_streak_percentiles = {
            percentile_map[level]: round(float(val), 1)
            for level, val in zip(config.confidence_levels, ls_pcts, strict=True)
        }

        # Probability of ruin
        ruin_threshold_equity = initial_equity * config.ruin_threshold
        ruin_count = np.sum(final_equities < ruin_threshold_equity)
        probability_of_ruin = round(float(ruin_count / len(final_equities)), 4)

        # Mean and median
        mean_equity = round(float(np.mean(final_equities)), 2)
        median_equity = round(float(np.median(final_equities)), 2)

        logger.info(
            "Monte Carlo simulation completed",
            num_simulations=config.num_simulations,
            mean_final_equity=mean_equity,
            probability_of_ruin=probability_of_ruin,
        )

        return MonteCarloResult(
            config=config,
            num_trades=num_trades,
            equity_percentiles=equity_percentiles,
            max_drawdown_percentiles=max_drawdown_percentiles,
            sharpe_percentiles=sharpe_percentiles,
            probability_of_ruin=probability_of_ruin,
            mean_final_equity=mean_equity,
            median_final_equity=median_equity,
            longest_losing_streak_percentiles=losing_streak_percentiles,
        )

    # ------------------------------------------------------------------
    # Internal: Zero-trade result
    # ------------------------------------------------------------------

    @staticmethod
    def _zero_trade_result(
        config: MonteCarloConfig,
        initial_equity: float,
        num_trades: int = 0,
    ) -> MonteCarloResult:
        """
        Build a result for zero-trade backtests.

        All simulations return initial equity, zero drawdown, zero Sharpe.

        Args:
            config: Simulation configuration.
            initial_equity: Starting equity.
            num_trades: Number of trades (0 for truly empty).

        Returns:
            MonteCarloResult with uniform initial equity.
        """
        percentile_map = {level: f"p{int(level * 100)}" for level in config.confidence_levels}
        equity_pcts = dict.fromkeys(percentile_map.values(), initial_equity)
        zero_pcts = dict.fromkeys(percentile_map.values(), 0.0)

        return MonteCarloResult(
            config=config,
            num_trades=num_trades,
            equity_percentiles=equity_pcts,
            max_drawdown_percentiles=zero_pcts,
            sharpe_percentiles=zero_pcts,
            probability_of_ruin=0.0,
            mean_final_equity=initial_equity,
            median_final_equity=initial_equity,
            longest_losing_streak_percentiles=zero_pcts,
        )
