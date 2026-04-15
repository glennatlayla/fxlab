"""
Backtest engine interface (port).

Responsibilities:
- Define the abstract contract for event-driven backtesting engines.
- Enable pluggable backtest implementations without changing caller code.

Does NOT:
- Implement backtest logic (engine layer responsibility).
- Define result contracts (libs.contracts.backtest).
- Fetch market data (repository layer responsibility).

Dependencies:
- libs.contracts.backtest: BacktestConfig, BacktestResult

Example:
    engine: BacktestEngineInterface = BacktestEngine(
        signal_strategy=strategy,
        market_data_repository=repo,
        indicator_engine=engine,
    )
    result = engine.run(config)
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from libs.contracts.backtest import BacktestConfig, BacktestResult


class BacktestEngineInterface(ABC):
    """
    Port interface for event-driven backtesting engines.

    A backtest engine replays historical bars through a signal strategy
    and simulated broker to produce performance metrics and signal
    attribution data.

    Responsibilities:
    - Accept a BacktestConfig and execute a full historical simulation.
    - Return a BacktestResult with metrics, trades, equity curve, and
      signal attribution summary.

    Does NOT:
    - Stream live data (historical replay only).
    - Implement strategy logic (uses injected SignalStrategyInterface).
    - Persist results (caller responsibility).

    Example:
        result = engine.run(config)
        print(f"Return: {result.total_return_pct}%")
    """

    @abstractmethod
    def run(self, config: BacktestConfig) -> BacktestResult:
        """
        Execute a backtest run and return results.

        Replays historical bars through the configured signal strategy
        and simulated broker. Computes performance metrics, equity curve,
        drawdown curve, and signal attribution data.

        Args:
            config: Backtest configuration specifying strategy, symbols,
                date range, interval, initial equity, and cost parameters.

        Returns:
            BacktestResult with performance metrics, trade list, equity
            curve, signal attribution summary, and computed indicator names.

        Raises:
            ValueError: If config has invalid parameters (e.g., end < start).
            ExternalServiceError: If market data repository fails.

        Example:
            config = BacktestConfig(
                strategy_id="ma-crossover",
                symbols=["AAPL"],
                start_date=date(2025, 1, 1),
                end_date=date(2025, 12, 31),
            )
            result = engine.run(config)
        """
