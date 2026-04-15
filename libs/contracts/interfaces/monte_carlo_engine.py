"""
Monte Carlo engine interface (port).

Responsibilities:
- Define the abstract contract for Monte Carlo simulation engines.

Does NOT:
- Implement simulation logic (engine layer responsibility).
- Define result contracts (libs.contracts.monte_carlo).

Dependencies:
- libs.contracts.monte_carlo: MonteCarloConfig, MonteCarloResult
- libs.contracts.backtest: BacktestResult

Example:
    engine: MonteCarloEngineInterface = MonteCarloEngine()
    result = engine.run(backtest_result, config)
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from libs.contracts.backtest import BacktestResult
from libs.contracts.monte_carlo import MonteCarloConfig, MonteCarloResult


class MonteCarloEngineInterface(ABC):
    """
    Port interface for Monte Carlo simulation engines.

    Takes a completed BacktestResult and runs Monte Carlo simulations
    to produce confidence intervals and risk metrics.

    Responsibilities:
    - Accept a BacktestResult and MonteCarloConfig.
    - Return MonteCarloResult with percentile-based confidence intervals.

    Does NOT:
    - Run backtests.
    - Persist results.

    Example:
        result = engine.run(backtest_result, config)
    """

    @abstractmethod
    def run(
        self,
        backtest_result: BacktestResult,
        config: MonteCarloConfig,
    ) -> MonteCarloResult:
        """
        Execute Monte Carlo simulation on a backtest result.

        Args:
            backtest_result: Completed backtest with trades and equity data.
            config: Simulation parameters (iterations, method, thresholds).

        Returns:
            MonteCarloResult with confidence intervals and ruin probability.

        Raises:
            ValueError: If backtest_result has no trades and method is TRADE_RESAMPLE.

        Example:
            result = engine.run(bt_result, MonteCarloConfig())
        """
