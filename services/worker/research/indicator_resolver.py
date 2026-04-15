"""
Indicator resolver for backtest engine integration (Phase 7 — M12).

Responsibilities:
- Fetch historical candle data from the market data repository.
- Compute technical indicators via the IndicatorEngine.
- Cache computed results within a single backtest run to avoid redundant computation.
- Automatically handle lookback buffer for indicator warm-up periods.
- Align indicator output to the requested date range (trim warm-up bars).

Does NOT:
- Execute trades (research engine responsibility).
- Persist results (caller responsibility).
- Validate strategy DSL (DSL validator responsibility).

Dependencies:
- MarketDataRepositoryInterface (injected): Candle data source.
- IndicatorEngine (injected): Indicator computation.

Error conditions:
- IndicatorNotFoundError: indicator not registered in the engine's registry.
- ValidationError: insufficient data for the requested date range.

Example:
    resolver = IndicatorResolver(
        market_data_repo=repo,
        engine=engine,
        lookback_buffer_days=30,
    )
    values = resolver.resolve("SMA", "AAPL", start, end, period=20)
"""

from __future__ import annotations

import logging
import threading
from collections import OrderedDict
from datetime import datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

from libs.contracts.interfaces.indicator_resolver import IndicatorResolverInterface
from libs.contracts.interfaces.market_data_repository import (
    MarketDataRepositoryInterface,
)
from libs.contracts.market_data import MarketDataQuery
from libs.indicators.engine import IndicatorEngine

logger = logging.getLogger(__name__)


class IndicatorResolver(IndicatorResolverInterface):
    """
    Production implementation of indicator resolution for backtesting.

    Bridges the market data repository and the indicator engine. Fetches
    candles with extra lookback, computes the indicator, and trims the
    result to the requested date range.

    Uses an LRU cache to avoid redundant computation when the same indicator
    is referenced multiple times in a strategy's DSL rules.

    Responsibilities:
    - Fetch candles with lookback buffer.
    - Compute indicators via IndicatorEngine.
    - Cache results (LRU, configurable max size).
    - Trim output to requested date range.

    Does NOT:
    - Execute trades.
    - Persist results.

    Dependencies:
    - MarketDataRepositoryInterface (injected).
    - IndicatorEngine (injected).

    Example:
        resolver = IndicatorResolver(
            market_data_repo=repo, engine=engine,
        )
        sma_values = resolver.resolve("SMA", "AAPL", start, end, period=20)
    """

    def __init__(
        self,
        *,
        market_data_repo: MarketDataRepositoryInterface,
        engine: IndicatorEngine,
        lookback_buffer_days: int = 30,
        cache_max_size: int = 100,
    ) -> None:
        """
        Initialize the indicator resolver.

        Args:
            market_data_repo: Repository for fetching candle data.
            engine: IndicatorEngine for computing indicators.
            lookback_buffer_days: Default extra days to fetch for warm-up.
            cache_max_size: Maximum number of cached indicator results.
        """
        self._repo = market_data_repo
        self._engine = engine
        self._lookback_buffer_days = lookback_buffer_days
        self._cache_max_size = cache_max_size

        # LRU cache: key → list of (timestamp, value) pairs
        self._cache: OrderedDict[str, list[tuple[datetime, Decimal | None]]] = OrderedDict()
        self._lock = threading.Lock()
        self._hits = 0
        self._misses = 0

    def resolve(
        self,
        indicator_name: str,
        symbol: str,
        start: datetime,
        end: datetime,
        interval: str = "1d",
        **params: int | float,
    ) -> list[Decimal | None]:
        """
        Resolve indicator values for a symbol over a date range.

        Fetches candle data with lookback buffer, computes the indicator,
        and returns values aligned to bars within [start, end].

        Args:
            indicator_name: Canonical indicator name (e.g., "SMA", "MACD").
            symbol: Instrument ticker.
            start: Start of the evaluation period.
            end: End of the evaluation period.
            interval: Candle interval (default "1d").
            **params: Indicator-specific parameters.

        Returns:
            List of Decimal values, one per bar in [start, end].
            None for bars with insufficient lookback data.

        Raises:
            IndicatorNotFoundError: If the indicator is not registered.
        """
        cache_key = self._make_cache_key(indicator_name, symbol, start, end, interval, params)

        # Check cache first (lock protects all shared mutable state — §0.6)
        with self._lock:
            if cache_key in self._cache:
                self._hits += 1
                self._cache.move_to_end(cache_key)
                cached = self._cache[cache_key]
                return [v for _, v in cached]
            self._misses += 1

        # Fetch candles with lookback buffer
        buffer_start = start - timedelta(days=self._lookback_buffer_days)
        candles = self._fetch_candles(symbol, buffer_start, end, interval)

        if not candles:
            logger.warning(
                "No candle data available",
                extra={
                    "operation": "resolve",
                    "component": "IndicatorResolver",
                    "symbol": symbol,
                    "start": str(start),
                    "end": str(end),
                },
            )
            return []

        # Compute indicator
        result = self._engine.compute(indicator_name, candles, **params)

        # Map values to timestamps and trim to requested range
        values_with_ts: list[tuple[datetime, Decimal | None]] = []
        output_values = result.values if isinstance(result.values, list) else list(result.values)

        for i, candle in enumerate(candles):
            ts = candle.timestamp
            if ts < start or ts > end:
                continue
            if i < len(output_values):
                raw = output_values[i]
                if raw is None or (hasattr(raw, "__class__") and str(raw) == "nan"):
                    values_with_ts.append((ts, None))
                else:
                    try:
                        dec_val = Decimal(str(raw)).quantize(
                            Decimal("0.000001"), rounding=ROUND_HALF_UP
                        )
                        values_with_ts.append((ts, dec_val))
                    except Exception:
                        values_with_ts.append((ts, None))
            else:
                values_with_ts.append((ts, None))

        # Store in cache
        with self._lock:
            self._cache[cache_key] = values_with_ts
            if len(self._cache) > self._cache_max_size:
                self._cache.popitem(last=False)

        logger.debug(
            "Indicator resolved",
            extra={
                "operation": "resolve",
                "component": "IndicatorResolver",
                "indicator": indicator_name,
                "symbol": symbol,
                "bars": len(values_with_ts),
                "params": params,
            },
        )

        return [v for _, v in values_with_ts]

    def resolve_at_bar(
        self,
        indicator_name: str,
        symbol: str,
        bar_timestamp: datetime,
        interval: str = "1d",
        lookback_bars: int = 300,
        **params: int | float,
    ) -> Decimal | None:
        """
        Resolve a single indicator value at a specific bar timestamp.

        Fetches enough history for the indicator's lookback requirement
        and returns the value at the target timestamp.

        Args:
            indicator_name: Indicator name.
            symbol: Instrument ticker.
            bar_timestamp: Target bar timestamp.
            interval: Candle interval.
            lookback_bars: Number of bars to fetch.
            **params: Indicator-specific parameters.

        Returns:
            Indicator value at the bar, or None if insufficient data.

        Raises:
            IndicatorNotFoundError: If the indicator is not registered.
        """
        # Compute lookback period based on interval
        lookback_days = self._bars_to_days(lookback_bars, interval)
        start = bar_timestamp - timedelta(days=lookback_days)

        candles = self._fetch_candles(symbol, start, bar_timestamp, interval)
        if not candles:
            return None

        result = self._engine.compute(indicator_name, candles, **params)
        output_values = result.values if isinstance(result.values, list) else list(result.values)

        if not output_values:
            return None

        # Return last computed value (aligned to bar_timestamp)
        last_val = output_values[-1]
        if last_val is None or str(last_val) == "nan":
            return None

        try:
            return Decimal(str(last_val)).quantize(Decimal("0.000001"), rounding=ROUND_HALF_UP)
        except Exception:
            return None

    def clear_cache(self) -> None:
        """Clear the internal indicator result cache."""
        with self._lock:
            self._cache.clear()
            self._hits = 0
            self._misses = 0

    def get_cache_stats(self) -> dict[str, int]:
        """
        Return cache statistics.

        Returns:
            Dict with 'hits', 'misses', 'size' keys.
        """
        with self._lock:
            return {
                "hits": self._hits,
                "misses": self._misses,
                "size": len(self._cache),
            }

    # ------------------------------------------------------------------
    # Private helpers
    # ------------------------------------------------------------------

    def _fetch_candles(
        self,
        symbol: str,
        start: datetime,
        end: datetime,
        interval: str,
    ) -> list[Any]:
        """
        Fetch candles from the market data repository.

        Args:
            symbol: Instrument ticker.
            start: Start timestamp.
            end: End timestamp.
            interval: Candle interval string.

        Returns:
            List of Candle objects ordered by ascending timestamp.
        """
        from libs.contracts.market_data import CandleInterval

        try:
            candle_interval = CandleInterval(interval)
        except ValueError:
            candle_interval = CandleInterval.D1

        query = MarketDataQuery(
            symbol=symbol,
            interval=candle_interval,
            start=start,
            end=end,
        )
        page = self._repo.query_candles(query)
        return page.candles

    @staticmethod
    def _make_cache_key(
        indicator_name: str,
        symbol: str,
        start: datetime,
        end: datetime,
        interval: str,
        params: dict[str, Any],
    ) -> str:
        """
        Build a deterministic cache key for indicator resolution.

        Args:
            indicator_name: Indicator name.
            symbol: Symbol.
            start: Period start.
            end: Period end.
            interval: Bar interval.
            params: Indicator parameters.

        Returns:
            String cache key.
        """
        param_str = "|".join(f"{k}={v}" for k, v in sorted(params.items()))
        return f"{indicator_name}:{symbol}:{interval}:{start.isoformat()}:{end.isoformat()}:{param_str}"

    @staticmethod
    def _bars_to_days(bars: int, interval: str) -> int:
        """
        Estimate calendar days needed for N bars at given interval.

        Accounts for weekends and holidays with a safety factor.

        Args:
            bars: Number of bars needed.
            interval: Bar interval string.

        Returns:
            Estimated calendar days.
        """
        # Map interval to approximate bars-per-calendar-day
        bars_per_day = {
            "1m": 390,  # ~6.5 hours of 1-min bars
            "5m": 78,
            "15m": 26,
            "1h": 7,
            "1d": 1,
        }
        bpd = bars_per_day.get(interval, 1)
        # Use 1.5x safety factor for weekends/holidays
        return max(1, int(bars / bpd * 1.5) + 1)
