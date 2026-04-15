"""
Indicator calculation engine — dispatch and orchestration layer.

Responsibilities:
- Extract OHLCV numpy arrays from Candle lists (one-time conversion).
- Dispatch compute() calls to the correct IndicatorCalculator via the registry.
- Support batch computation (compute_batch) for multiple indicators in one pass.
- Wrap raw numpy outputs into IndicatorResult containers.
- Remain stateless and thread-safe — safe for concurrent use.

Does NOT:
- Implement any indicator math (calculators do that).
- Manage indicator registration (registry does that).
- Access databases, APIs, or any I/O.

Dependencies:
- libs.indicators.registry.IndicatorRegistry: calculator dispatch.
- libs.contracts.indicator: IndicatorResult, IndicatorRequest, IndicatorCalculator.
- libs.contracts.market_data.Candle: input data model.
- libs.contracts.errors.IndicatorNotFoundError: unregistered indicator name.
- numpy: array extraction and type conversion.

Error conditions:
- IndicatorNotFoundError: compute() or compute_batch() with unregistered name.
- ValueError: empty candle list.

Example:
    from libs.indicators.engine import IndicatorEngine
    from libs.indicators.registry import IndicatorRegistry

    registry = IndicatorRegistry()
    # ... register indicators ...
    engine = IndicatorEngine(registry)

    result = engine.compute("SMA", candles, period=20)
    batch = engine.compute_batch(
        [IndicatorRequest(indicator_name="SMA", params={"period": 20}),
         IndicatorRequest(indicator_name="RSI", params={"period": 14})],
        candles,
    )
"""

from __future__ import annotations

from typing import Any

import numpy as np

from libs.contracts.indicator import IndicatorRequest, IndicatorResult
from libs.contracts.market_data import Candle
from libs.indicators.registry import IndicatorRegistry


class IndicatorEngine:
    """
    Stateless engine that computes technical indicators from candle data.

    Converts Candle lists to aligned numpy arrays once, then dispatches to
    registered IndicatorCalculator instances via the registry. Safe for
    concurrent use — no mutable state beyond the registry reference.

    Responsibilities:
    - OHLCV extraction from Candle models to numpy arrays.
    - Single-indicator and batch-indicator computation.
    - Wrapping raw outputs into IndicatorResult containers.

    Does NOT:
    - Contain indicator math.
    - Manage registration.
    - Perform I/O.

    Dependencies:
    - IndicatorRegistry: lookup of calculator by name.

    Example:
        engine = IndicatorEngine(registry)
        result = engine.compute("SMA", candles, period=20)
        assert result.indicator_name == "SMA"
        assert len(result.values) == len(candles)
    """

    def __init__(self, registry: IndicatorRegistry) -> None:
        self._registry = registry

    def compute(
        self,
        indicator_name: str,
        candles: list[Candle],
        **params: Any,
    ) -> IndicatorResult:
        """
        Compute a single indicator from candle data.

        Extracts OHLCV arrays, dispatches to the registered calculator,
        and wraps the output in an IndicatorResult.

        Args:
            indicator_name: Canonical indicator name (case-insensitive).
            candles: List of Candle models, ordered by ascending timestamp.
            **params: Indicator-specific parameters (e.g. period=20).

        Returns:
            IndicatorResult with values/components, timestamps, and metadata.

        Raises:
            IndicatorNotFoundError: If indicator_name is not registered.
            ValueError: If candles list is empty.

        Example:
            result = engine.compute("SMA", candles, period=20)
            print(result.values[-1])  # Latest SMA value
        """
        if not candles:
            raise ValueError("Cannot compute indicator on empty candle list")

        ohlcv = self._extract_ohlcv(candles)
        calculator = self._registry.get(indicator_name)

        raw = calculator.calculate(
            open=ohlcv["open"],
            high=ohlcv["high"],
            low=ohlcv["low"],
            close=ohlcv["close"],
            volume=ohlcv["volume"],
            timestamps=ohlcv["timestamps"],
            **params,
        )

        return self._wrap_result(indicator_name, raw, ohlcv["timestamps"], params)

    def compute_batch(
        self,
        requests: list[IndicatorRequest],
        candles: list[Candle],
    ) -> dict[str, IndicatorResult]:
        """
        Compute multiple indicators from the same candle data in one pass.

        Extracts OHLCV arrays once, then dispatches each request to its
        calculator. Returns a dict keyed by a unique key for each request
        (indicator_name, or indicator_name with params if duplicated).

        Args:
            requests: List of IndicatorRequest specifying indicators and params.
            candles: List of Candle models, ordered by ascending timestamp.

        Returns:
            Dict mapping request keys to IndicatorResult instances.

        Raises:
            IndicatorNotFoundError: If any requested indicator is not registered.
            ValueError: If candles list is empty or requests list is empty.

        Example:
            results = engine.compute_batch(
                [IndicatorRequest(indicator_name="SMA", params={"period": 20}),
                 IndicatorRequest(indicator_name="RSI", params={"period": 14})],
                candles,
            )
            sma_result = results["SMA"]
            rsi_result = results["RSI"]
        """
        if not candles:
            raise ValueError("Cannot compute indicators on empty candle list")
        if not requests:
            raise ValueError("No indicator requests provided")

        ohlcv = self._extract_ohlcv(candles)
        results: dict[str, IndicatorResult] = {}

        for req in requests:
            calculator = self._registry.get(req.indicator_name)
            raw = calculator.calculate(
                open=ohlcv["open"],
                high=ohlcv["high"],
                low=ohlcv["low"],
                close=ohlcv["close"],
                volume=ohlcv["volume"],
                timestamps=ohlcv["timestamps"],
                **req.params,
            )
            result = self._wrap_result(req.indicator_name, raw, ohlcv["timestamps"], req.params)
            key = self._make_batch_key(req, results)
            results[key] = result

        return results

    @property
    def registry(self) -> IndicatorRegistry:
        """Access the underlying registry for introspection."""
        return self._registry

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _extract_ohlcv(candles: list[Candle]) -> dict[str, np.ndarray]:
        """
        Extract aligned OHLCV numpy arrays from a list of Candle models.

        Converts Decimal prices to float64 for numpy computation. Candles
        are assumed to be pre-sorted by ascending timestamp.

        Args:
            candles: Non-empty list of Candle models.

        Returns:
            Dict with keys "open", "high", "low", "close", "volume",
            "timestamps" — each a 1-D float64 numpy array.
        """
        n = len(candles)
        open_arr = np.empty(n, dtype=np.float64)
        high_arr = np.empty(n, dtype=np.float64)
        low_arr = np.empty(n, dtype=np.float64)
        close_arr = np.empty(n, dtype=np.float64)
        volume_arr = np.empty(n, dtype=np.float64)
        ts_arr = np.empty(n, dtype=np.float64)

        for i, c in enumerate(candles):
            open_arr[i] = float(c.open)
            high_arr[i] = float(c.high)
            low_arr[i] = float(c.low)
            close_arr[i] = float(c.close)
            volume_arr[i] = float(c.volume)
            ts_arr[i] = c.timestamp.timestamp()

        return {
            "open": open_arr,
            "high": high_arr,
            "low": low_arr,
            "close": close_arr,
            "volume": volume_arr,
            "timestamps": ts_arr,
        }

    @staticmethod
    def _wrap_result(
        indicator_name: str,
        raw: np.ndarray | dict[str, np.ndarray],
        timestamps: np.ndarray,
        params: dict[str, Any],
    ) -> IndicatorResult:
        """
        Wrap raw calculator output into an IndicatorResult.

        Args:
            indicator_name: Name of the indicator.
            raw: Single array or dict of named arrays from the calculator.
            timestamps: Aligned timestamp array.
            params: Parameters used for the computation.

        Returns:
            IndicatorResult with values/components populated.
        """
        if isinstance(raw, dict):
            # Multi-output indicator (e.g. MACD, Bollinger)
            return IndicatorResult(
                indicator_name=indicator_name.upper(),
                values=None,
                components=raw,
                timestamps=timestamps,
                metadata=dict(params),
            )
        else:
            # Single-output indicator (e.g. SMA, RSI)
            return IndicatorResult(
                indicator_name=indicator_name.upper(),
                values=raw,
                components={},
                timestamps=timestamps,
                metadata=dict(params),
            )

    @staticmethod
    def _make_batch_key(
        req: IndicatorRequest,
        existing: dict[str, Any],
    ) -> str:
        """
        Generate a unique key for a batch result entry.

        Uses the indicator name as-is if unique; otherwise appends a
        parameter hash to disambiguate (e.g. "SMA_period=20").

        Args:
            req: The indicator request.
            existing: Already-populated result keys.

        Returns:
            Unique string key for the result dict.
        """
        canonical = req.indicator_name.upper()
        if canonical not in existing:
            return canonical

        # Disambiguate with params
        param_str = "_".join(f"{k}={v}" for k, v in sorted(req.params.items()))
        key = f"{canonical}_{param_str}" if param_str else f"{canonical}_2"

        # Handle edge case of identical params
        counter = 2
        base_key = key
        while key in existing:
            key = f"{base_key}_{counter}"
            counter += 1

        return key
