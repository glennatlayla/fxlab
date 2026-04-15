"""
Signal strategy interface (port).

Responsibilities:
- Define the abstract contract for trading signal generation strategies.
- Enable pluggable signal strategies without changing evaluation pipeline code.

Does NOT:
- Execute trades or manage positions.
- Evaluate risk gates (service layer responsibility).
- Persist signals (repository layer responsibility).

Dependencies:
- libs.contracts.market_data: Candle
- libs.contracts.indicator: IndicatorRequest, IndicatorResult
- libs.contracts.execution: PositionSnapshot
- libs.contracts.signal: Signal

Example:
    class SmaCrossoverStrategy(SignalStrategyInterface):
        def evaluate(self, symbol, candles, indicators, position) -> Signal | None:
            ...
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from libs.contracts.execution import PositionSnapshot
from libs.contracts.indicator import IndicatorRequest, IndicatorResult
from libs.contracts.market_data import Candle
from libs.contracts.signal import Signal


class SignalStrategyInterface(ABC):
    """
    Port interface for trading signal generation strategies.

    Each strategy encapsulates a specific trading approach (e.g., moving
    average crossover, RSI mean reversion) and produces Signal objects
    when market conditions meet its criteria.

    Responsibilities:
    - Evaluate candle data and indicator values to produce trading signals.
    - Declare required indicators so the framework can pre-compute them.
    - Expose strategy identity metadata.

    Does NOT:
    - Manage positions or execute orders.
    - Evaluate risk or size positions.

    Example:
        strategy = SmaCrossoverStrategy(fast=20, slow=50)
        signal = strategy.evaluate("AAPL", candles, indicators, position)
    """

    @abstractmethod
    def evaluate(
        self,
        symbol: str,
        candles: list[Candle],
        indicators: dict[str, IndicatorResult],
        current_position: PositionSnapshot | None,
        *,
        correlation_id: str,
    ) -> Signal | None:
        """
        Evaluate market data and indicators, optionally produce a signal.

        Args:
            symbol: Ticker symbol being evaluated.
            candles: Recent candle data for the symbol.
            indicators: Pre-computed indicator results keyed by indicator name.
            current_position: Current position snapshot (None if flat).
            correlation_id: Request correlation ID for tracing.

        Returns:
            A Signal if conditions are met, None otherwise.

        Example:
            signal = strategy.evaluate("AAPL", candles, indicators, None, correlation_id="c1")
        """

    @abstractmethod
    def required_indicators(self) -> list[IndicatorRequest]:
        """
        Declare which indicators this strategy needs computed.

        Returns:
            List of IndicatorRequest objects describing required indicators.

        Example:
            requests = strategy.required_indicators()
            # [IndicatorRequest(indicator_name="sma", params={"period": 20})]
        """

    @property
    @abstractmethod
    def strategy_id(self) -> str:
        """Unique identifier for this strategy."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Human-readable name for this strategy."""

    @property
    @abstractmethod
    def supported_symbols(self) -> list[str]:
        """List of symbols this strategy can trade (empty = all)."""
