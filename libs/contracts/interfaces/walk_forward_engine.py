"""
Walk-forward engine interface (port).

Responsibilities:
- Define the abstract contract for walk-forward analysis engines.
- Enable pluggable implementations without changing caller code.

Does NOT:
- Implement walk-forward logic (engine layer responsibility).
- Define result contracts (libs.contracts.walk_forward).
- Run backtests (BacktestEngine responsibility).

Dependencies:
- libs.contracts.walk_forward: WalkForwardConfig, WalkForwardResult

Example:
    engine: WalkForwardEngineInterface = WalkForwardEngine(
        backtest_engine=bt_engine,
        strategy_factory=factory,
    )
    result = engine.run(config)
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from libs.contracts.walk_forward import WalkForwardConfig, WalkForwardResult


class WalkForwardEngineInterface(ABC):
    """
    Port interface for walk-forward analysis engines.

    Walk-forward analysis splits historical data into rolling windows,
    optimizes strategy parameters on in-sample data, and validates on
    out-of-sample data to prevent overfitting.

    Responsibilities:
    - Accept a WalkForwardConfig and execute the full analysis.
    - Return a WalkForwardResult with per-window results and stability.

    Does NOT:
    - Implement strategy logic.
    - Persist results.

    Example:
        result = engine.run(config)
        print(f"Stability: {result.stability_score}")
    """

    @abstractmethod
    def run(self, config: WalkForwardConfig) -> WalkForwardResult:
        """
        Execute a walk-forward analysis and return results.

        Args:
            config: Walk-forward configuration specifying windows,
                parameter grid, and optimization metric.

        Returns:
            WalkForwardResult with per-window results, aggregate OOS
            metric, stability score, and consensus parameters.

        Raises:
            ValueError: If config produces zero windows.

        Example:
            result = engine.run(config)
        """
