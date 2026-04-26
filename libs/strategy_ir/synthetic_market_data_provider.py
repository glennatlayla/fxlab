"""
Deterministic synthetic FX market-data provider (M3.X1 backtest backend).

Purpose:
    Provide a fully deterministic, byte-reproducible implementation of
    :class:`libs.strategy_ir.interfaces.market_data_provider_interface.MarketDataProviderInterface`
    so milestone M3.X1 (CLI backtest) can run end-to-end against the
    seven major FX pairs without any network, vendor SDK, or live
    Oanda credentials. When milestone M4.E2 lands the real
    :class:`OandaMarketDataProvider`, callers swap the constructor
    arg only -- this provider stays as the test/replay backend.

Responsibilities:
    - Generate OHLCV candles via a seeded geometric Brownian motion
      with a per-symbol drift / volatility table sized for FX (small
      numbers, JPY pairs anchored higher).
    - Cover the four production timeframes the Strategy Repo uses:
      ``"M15"`` / ``"15m"``, ``"H1"`` / ``"1h"``, ``"H4"`` / ``"4h"``,
      ``"D"`` / ``"D1"`` / ``"1d"``.
    - Honour the seven major FX pairs:
      EURUSD, GBPUSD, USDJPY, USDCHF, AUDUSD, USDCAD, NZDUSD.
    - Expose pip-size lookups (``0.01`` for JPY pairs, ``0.0001``
      otherwise) the risk translator and slippage estimators consume.

Does NOT:
    - Touch the wall clock. Every random draw flows from the seeded
      :class:`numpy.random.Generator`. Two calls with the same
      ``(symbol, timeframe, start, end, seed)`` quintuple produce
      byte-identical Candle lists.
    - Make any I/O. The provider holds only the seed, parameter
      table, and an instance lock for thread-safe call accounting.
    - Filter, paginate, or persist. Callers receive the full
      generated window every time.
    - Pretend to be live data. The synthetic prices are statistically
      well-behaved but should never be presented to a human as a real
      market quote.

Dependencies:
    - :mod:`numpy` for the seeded Generator and vectorised math.
    - :mod:`libs.contracts.market_data` for the :class:`Candle` and
      :class:`CandleInterval` value objects.
    - :mod:`libs.strategy_ir.interfaces.market_data_provider_interface`
      for the Protocol the provider satisfies.

Error conditions:
    - :class:`ValueError` when an unsupported symbol or timeframe is
      requested. Unsupported is fail-fast: the synthetic provider will
      not silently fall back to a default symbol or interval.
    - :class:`ValueError` when ``end < start`` -- callers must pass an
      ordered window.

Example::

    from datetime import datetime, timezone

    from libs.strategy_ir.synthetic_market_data_provider import (
        SyntheticFxMarketDataProvider,
    )

    provider = SyntheticFxMarketDataProvider(seed=42)
    bars = provider.fetch_bars(
        symbol="EURUSD",
        timeframe="H1",
        start=datetime(2026, 1, 1, tzinfo=timezone.utc),
        end=datetime(2026, 1, 31, tzinfo=timezone.utc),
    )

M4.E2 swap path:
    When Oanda credentials land, ``OandaMarketDataProvider`` will
    implement the same :class:`MarketDataProviderInterface`. The
    M3.X1 CLI swaps the constructor arg from
    :class:`SyntheticFxMarketDataProvider` to
    :class:`OandaMarketDataProvider` -- no other code changes.
"""

from __future__ import annotations

import threading
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import numpy as np

from libs.contracts.market_data import Candle, CandleInterval
from libs.strategy_ir.interfaces.market_data_provider_interface import (
    MarketDataProviderInterface,
)

# ---------------------------------------------------------------------------
# Constants -- the seven majors, pip sizes, timeframe table
# ---------------------------------------------------------------------------

#: The seven major FX pairs the synthetic provider serves. Anything
#: outside this set is rejected with :class:`ValueError`. Mirrors the
#: production scope of the M3.X1 CLI backtest.
_SUPPORTED_SYMBOLS: frozenset[str] = frozenset(
    {
        "EURUSD",
        "GBPUSD",
        "USDJPY",
        "USDCHF",
        "AUDUSD",
        "USDCAD",
        "NZDUSD",
    }
)

#: Pip-size lookup. JPY-quoted pairs use ``0.01``; everything else
#: uses ``0.0001``. Stored as :class:`Decimal` so callers preserve
#: precision when computing pip values.
_PIP_SIZES: dict[str, Decimal] = {
    "EURUSD": Decimal("0.0001"),
    "GBPUSD": Decimal("0.0001"),
    "USDJPY": Decimal("0.01"),
    "USDCHF": Decimal("0.0001"),
    "AUDUSD": Decimal("0.0001"),
    "USDCAD": Decimal("0.0001"),
    "NZDUSD": Decimal("0.0001"),
}


#: Per-symbol synthetic spread expressed in pips. The synthetic provider
#: must emit a spread on every candle so Strategy-IR conditions of the
#: form ``spread <= N units=pips`` can evaluate (the M3.X1 CLI relies
#: on this). The values mirror typical retail FX broker quotes:
#: roughly half a pip on majors, slightly wider on USDJPY where the
#: pip itself is two decimal places. The provider converts these pip
#: counts into price units (``pip_size * spread_pips``) before stamping
#: each :class:`Candle`.
#:
#: The numbers are deliberately conservative — small enough that the
#: Lien Double-Bollinger entry filter (``spread <= 2.0 pips``) passes
#: comfortably, large enough to round-trip cleanly through the Decimal
#: quantisation step.
_SYNTHETIC_SPREAD_PIPS: dict[str, float] = {
    "EURUSD": 0.5,
    "GBPUSD": 0.5,
    "USDJPY": 0.6,
    "USDCHF": 0.5,
    "AUDUSD": 0.5,
    "USDCAD": 0.5,
    "NZDUSD": 0.5,
}


#: Per-timeframe metadata. The first entry of each value is the bar
#: duration in seconds; the second is the :class:`CandleInterval`
#: enum value used to stamp the emitted Candle.
_TIMEFRAME_TABLE: dict[str, tuple[int, CandleInterval]] = {
    "M15": (15 * 60, CandleInterval.M15),
    "15m": (15 * 60, CandleInterval.M15),
    "H1": (60 * 60, CandleInterval.H1),
    "1h": (60 * 60, CandleInterval.H1),
    "H4": (4 * 60 * 60, CandleInterval.H4),
    "4h": (4 * 60 * 60, CandleInterval.H4),
    "D": (24 * 60 * 60, CandleInterval.D1),
    "D1": (24 * 60 * 60, CandleInterval.D1),
    "1d": (24 * 60 * 60, CandleInterval.D1),
}


#: Per-symbol GBM parameters. ``start_price`` anchors the synthetic
#: series in a realistic range. ``drift`` and ``vol`` are tuned for
#: low-volatility FX dynamics (annualised drift on the order of a few
#: percent, annualised vol on the order of 5-10%). Numbers are kept
#: small on purpose -- this provider must not generate prices that
#: drift to absurd values across a multi-month window.
_DEFAULT_SYMBOL_PARAMS: dict[str, dict[str, float]] = {
    "EURUSD": {"start_price": 1.1000, "drift": 0.02, "vol": 0.06},
    "GBPUSD": {"start_price": 1.2700, "drift": 0.015, "vol": 0.07},
    "USDJPY": {"start_price": 150.00, "drift": 0.01, "vol": 0.08},
    "USDCHF": {"start_price": 0.9000, "drift": -0.01, "vol": 0.06},
    "AUDUSD": {"start_price": 0.6600, "drift": 0.005, "vol": 0.075},
    "USDCAD": {"start_price": 1.3500, "drift": 0.01, "vol": 0.055},
    "NZDUSD": {"start_price": 0.6100, "drift": 0.0, "vol": 0.07},
}


#: Seconds in a year used when annualising drift / vol into the
#: per-bar GBM step. 365 days × 24 hours × 3600 seconds. Kept as a
#: fixed constant (no leap years) so the synthetic series is
#: calendar-independent and bit-stable across years.
_SECONDS_PER_YEAR: int = 365 * 24 * 60 * 60


# ---------------------------------------------------------------------------
# Provider
# ---------------------------------------------------------------------------


class SyntheticFxMarketDataProvider(MarketDataProviderInterface):
    """
    Deterministic synthetic FX market-data provider.

    Responsibilities:
        - Generate OHLCV candles for the seven major FX pairs at any
          of the four production timeframes (15m / 1h / 4h / 1d).
        - Produce byte-identical output for the same
          ``(symbol, timeframe, start, end, seed)`` quintuple.
        - Report the correct pip size per symbol.
        - Refuse unknown symbols or timeframes with ``ValueError``.

    Does NOT:
        - Use the wall clock or any unseeded randomness.
        - Make I/O of any kind.
        - Filter the returned window after generation -- the closed
          interval ``[start, end]`` IS the result.

    Dependencies:
        - ``seed`` (constructor): the sole entropy source.
        - ``symbol_params`` (constructor, optional): override the
          default drift/vol/start-price table per symbol. Useful for
          tests that need a hyper-volatile or flat-line series.

    Raises:
        ValueError: on unsupported symbol, unsupported timeframe, or
            inverted window (``end < start``).

    Thread safety:
        Each :meth:`fetch_bars` call constructs its own seeded
        :class:`numpy.random.Generator` from the
        ``(seed, symbol, timeframe, start, end)`` tuple, so concurrent
        calls are independent. The internal call log is guarded by a
        :class:`threading.Lock` so introspection helpers see a
        consistent view.

    Example::

        provider = SyntheticFxMarketDataProvider(seed=42)
        bars = provider.fetch_bars(
            symbol="EURUSD",
            timeframe="H1",
            start=datetime(2026, 1, 1, tzinfo=timezone.utc),
            end=datetime(2026, 1, 31, tzinfo=timezone.utc),
        )
    """

    def __init__(
        self,
        *,
        seed: int = 42,
        symbol_params: dict[str, dict[str, float]] | None = None,
    ) -> None:
        """
        Construct a deterministic synthetic provider.

        Args:
            seed: Master seed combined with the call arguments to
                derive the per-call :class:`numpy.random.Generator`.
                Same seed + same arguments => byte-identical output.
            symbol_params: Optional overrides for the per-symbol
                drift / vol / start-price table. Keys must be members
                of :data:`_SUPPORTED_SYMBOLS`. Each value must supply
                ``start_price``, ``drift``, and ``vol``. Symbols not
                present in the override use the built-in defaults.

        Raises:
            ValueError: If an override key is not a supported symbol
                or its value is missing a required field.
        """
        self._seed = int(seed)
        self._params: dict[str, dict[str, float]] = {
            sym: dict(p) for sym, p in _DEFAULT_SYMBOL_PARAMS.items()
        }
        if symbol_params:
            for sym, override in symbol_params.items():
                if sym not in _SUPPORTED_SYMBOLS:
                    raise ValueError(
                        f"symbol_params override for {sym!r} is not a supported "
                        f"FX major; supported symbols: {sorted(_SUPPORTED_SYMBOLS)}"
                    )
                missing = {"start_price", "drift", "vol"} - set(override)
                if missing:
                    raise ValueError(
                        f"symbol_params[{sym!r}] missing required keys: {sorted(missing)}"
                    )
                self._params[sym] = {
                    "start_price": float(override["start_price"]),
                    "drift": float(override["drift"]),
                    "vol": float(override["vol"]),
                }

        self._fetch_log: list[tuple[str, str, datetime, datetime]] = []
        self._lock = threading.Lock()

    # ------------------------------------------------------------------
    # Protocol implementation
    # ------------------------------------------------------------------

    def fetch_bars(
        self,
        *,
        symbol: str,
        timeframe: str,
        start: datetime,
        end: datetime,
    ) -> list[Candle]:
        """
        Generate deterministic synthetic candles for ``[start, end]``.

        Args:
            symbol: One of the seven supported majors (EURUSD,
                GBPUSD, USDJPY, USDCHF, AUDUSD, USDCAD, NZDUSD).
            timeframe: One of ``"M15"``/``"15m"``, ``"H1"``/``"1h"``,
                ``"H4"``/``"4h"``, ``"D"``/``"D1"``/``"1d"``.
            start: Inclusive start of the window, timezone-aware UTC.
                Will be aligned downward to the nearest timeframe
                boundary so consecutive calls with overlapping
                windows produce overlapping bars at the same
                timestamps.
            end: Inclusive end of the window, timezone-aware UTC.
                Aligned downward the same way.

        Returns:
            List of fully validated :class:`Candle` instances ordered
            by ascending timestamp. Empty list when the aligned
            window contains zero bar boundaries (e.g. ``end == start``
            below the timeframe granularity).

        Raises:
            ValueError: If the symbol or timeframe is unsupported,
                if either timestamp lacks a tzinfo, or if
                ``end < start`` after alignment.

        Example::

            bars = provider.fetch_bars(
                symbol="EURUSD",
                timeframe="H1",
                start=datetime(2026, 1, 1, tzinfo=timezone.utc),
                end=datetime(2026, 1, 2, tzinfo=timezone.utc),
            )
            # 25 bars (00:00 inclusive through 24:00 inclusive)
        """
        self._validate_symbol(symbol)
        bar_seconds, interval_enum = self._resolve_timeframe(timeframe)
        aligned_start, aligned_end = self._validate_window(start, end, bar_seconds)

        with self._lock:
            self._fetch_log.append((symbol, timeframe, start, end))

        # Bar count = number of bar boundaries in [aligned_start, aligned_end]
        # inclusive. A 1-hour window with bar_seconds=3600 yields two bars
        # (the boundary at start and the boundary at start+1h).
        span_seconds = int((aligned_end - aligned_start).total_seconds())
        bar_count = (span_seconds // bar_seconds) + 1
        if bar_count <= 0:
            return []

        rng = self._build_rng(symbol, timeframe, aligned_start, aligned_end)
        params = self._params[symbol]

        candles = self._generate_candles(
            symbol=symbol,
            interval_enum=interval_enum,
            bar_seconds=bar_seconds,
            bar_count=bar_count,
            aligned_start=aligned_start,
            params=params,
            rng=rng,
        )
        return candles

    def get_pip_size(self, symbol: str) -> Decimal:
        """
        Return the pip size for ``symbol``.

        Args:
            symbol: One of the seven supported majors.

        Returns:
            ``Decimal("0.01")`` for JPY-quoted pairs,
            ``Decimal("0.0001")`` for everything else.

        Raises:
            ValueError: If ``symbol`` is not in the supported set.

        Example::

            provider.get_pip_size("USDJPY")  # Decimal("0.01")
            provider.get_pip_size("EURUSD")  # Decimal("0.0001")
        """
        self._validate_symbol(symbol)
        return _PIP_SIZES[symbol]

    def supports(self, symbol: str) -> bool:
        """
        Report whether ``symbol`` is one of the seven supported majors.

        Args:
            symbol: Tradable instrument string.

        Returns:
            ``True`` if ``symbol`` is in
            ``{EURUSD, GBPUSD, USDJPY, USDCHF, AUDUSD, USDCAD, NZDUSD}``;
            ``False`` otherwise. Never raises.

        Example::

            provider.supports("EURUSD")  # True
            provider.supports("XYZ")     # False
        """
        return symbol in _SUPPORTED_SYMBOLS

    # ------------------------------------------------------------------
    # Introspection helpers
    # ------------------------------------------------------------------

    def fetch_calls(self) -> list[tuple[str, str, datetime, datetime]]:
        """
        Return a copy of the call log in chronological order.

        Each entry is ``(symbol, timeframe, start, end)`` exactly as
        the caller passed them (pre-alignment).

        Returns:
            List of tuples; safe to mutate without affecting the log.
        """
        with self._lock:
            return list(self._fetch_log)

    def clear_log(self) -> None:
        """Wipe the call log. Does not touch seed or parameters."""
        with self._lock:
            self._fetch_log.clear()

    # ------------------------------------------------------------------
    # Validation helpers (private)
    # ------------------------------------------------------------------

    def _validate_symbol(self, symbol: str) -> None:
        """Reject any symbol outside the supported majors."""
        if symbol not in _SUPPORTED_SYMBOLS:
            raise ValueError(
                f"Unsupported symbol {symbol!r}; supported: {sorted(_SUPPORTED_SYMBOLS)}"
            )

    def _resolve_timeframe(self, timeframe: str) -> tuple[int, CandleInterval]:
        """Look up the bar-second count and Candle interval enum."""
        try:
            return _TIMEFRAME_TABLE[timeframe]
        except KeyError as exc:
            raise ValueError(
                f"Unsupported timeframe {timeframe!r}; supported: {sorted(_TIMEFRAME_TABLE)}"
            ) from exc

    def _validate_window(
        self,
        start: datetime,
        end: datetime,
        bar_seconds: int,
    ) -> tuple[datetime, datetime]:
        """
        Verify the window is well-formed and align both ends.

        Alignment:
            Both ``start`` and ``end`` are floored to the nearest
            multiple of ``bar_seconds`` since the Unix epoch, in UTC.
            This makes the bar grid stable across calls regardless of
            whether the caller passes a "rounded" timestamp.

        Raises:
            ValueError: If either timestamp is naive or end < start.
        """
        if start.tzinfo is None or end.tzinfo is None:
            raise ValueError(
                "fetch_bars requires timezone-aware start and end "
                "(use datetime(..., tzinfo=timezone.utc))"
            )
        if end < start:
            raise ValueError(f"end ({end.isoformat()}) is before start ({start.isoformat()})")

        start_utc = start.astimezone(timezone.utc)
        end_utc = end.astimezone(timezone.utc)

        aligned_start = self._align_down(start_utc, bar_seconds)
        aligned_end = self._align_down(end_utc, bar_seconds)
        return aligned_start, aligned_end

    @staticmethod
    def _align_down(ts: datetime, bar_seconds: int) -> datetime:
        """Floor ``ts`` to the nearest multiple of ``bar_seconds`` UTC."""
        epoch_seconds = int(ts.timestamp())
        floored = (epoch_seconds // bar_seconds) * bar_seconds
        return datetime.fromtimestamp(floored, tz=timezone.utc)

    # ------------------------------------------------------------------
    # Determinism helpers (private)
    # ------------------------------------------------------------------

    def _build_rng(
        self,
        symbol: str,
        timeframe: str,
        aligned_start: datetime,
        aligned_end: datetime,
    ) -> np.random.Generator:
        """
        Construct the per-call seeded Generator.

        The seed sequence mixes:
            * the master seed,
            * the symbol's stable hash (computed from ASCII bytes so
              it is reproducible across processes -- ``hash()`` is
              salted by Python's PYTHONHASHSEED, so we cannot use
              it),
            * the timeframe's stable hash,
            * the aligned start / end Unix-second values.

        This guarantees that two calls with the same inputs derive
        the SAME Generator state and therefore emit byte-identical
        bars.
        """
        symbol_int = self._stable_int(symbol)
        timeframe_int = self._stable_int(timeframe)
        start_int = int(aligned_start.timestamp())
        end_int = int(aligned_end.timestamp())
        seed_seq = np.random.SeedSequence(
            entropy=[
                self._seed,
                symbol_int,
                timeframe_int,
                start_int,
                end_int,
            ]
        )
        return np.random.default_rng(seed_seq)

    @staticmethod
    def _stable_int(text: str) -> int:
        """
        Map ``text`` to a stable non-negative 64-bit integer.

        Python's built-in ``hash()`` is salted per-process via
        PYTHONHASHSEED, so it cannot anchor a deterministic seed.
        Instead we sum the ASCII byte values weighted by position --
        good enough to disambiguate "EURUSD" from "GBPUSD" and "H1"
        from "H4" while staying byte-stable across processes.
        """
        acc = 0
        for index, byte in enumerate(text.encode("utf-8"), start=1):
            acc = (acc * 1315423911) ^ (byte * (index + 7))
        return acc & 0xFFFFFFFFFFFFFFFF

    # ------------------------------------------------------------------
    # Bar generation (private)
    # ------------------------------------------------------------------

    def _generate_candles(
        self,
        *,
        symbol: str,
        interval_enum: CandleInterval,
        bar_seconds: int,
        bar_count: int,
        aligned_start: datetime,
        params: dict[str, float],
        rng: np.random.Generator,
    ) -> list[Candle]:
        """
        Run a seeded GBM walk and emit validated Candle instances.

        Algorithm:
            1. Convert annualised drift and vol into a per-bar step.
            2. For each bar, draw a normal sample from ``rng`` to
               advance the close price one GBM step.
            3. Synthesize OHLC by drawing a high/low excursion from
               the same generator. The excursion is bounded so the
               OHLC invariants always hold:
                   high >= max(open, close)
                   low  <= min(open, close)
            4. Volume is drawn from a small lognormal so it is
               always strictly positive and reasonable for FX bars.

        All math runs in float64 then is quantised to a fixed-decimal
        step appropriate for the symbol's pip size. JPY pairs quantise
        to 3 decimal places (sub-pip); non-JPY to 5 decimal places.
        """
        # Annualised parameters -> per-bar step.
        annual_drift = params["drift"]
        annual_vol = params["vol"]
        dt_years = bar_seconds / _SECONDS_PER_YEAR
        per_bar_drift = (annual_drift - 0.5 * annual_vol * annual_vol) * dt_years
        per_bar_vol = annual_vol * np.sqrt(dt_years)

        # Pre-draw all randomness in a single call. This is cheaper
        # than a Python loop AND keeps the byte-stability guarantee
        # tight (one draw per RNG call).
        # Layout:
        #   shocks[:, 0]  -> close-price log-return shock
        #   shocks[:, 1]  -> high excursion magnitude (>= 0)
        #   shocks[:, 2]  -> low excursion magnitude  (>= 0)
        #   shocks[:, 3]  -> volume noise (lognormal)
        shocks = rng.standard_normal(size=(bar_count, 4))

        # Convert each column into the right shape:
        log_returns = per_bar_drift + per_bar_vol * shocks[:, 0]
        # Range excursions are folded normals scaled by per-bar vol.
        # Half the per-bar vol is enough to give realistic-looking
        # candles without dwarfing the body.
        high_excursions = np.abs(shocks[:, 1]) * (per_bar_vol * 0.5)
        low_excursions = np.abs(shocks[:, 2]) * (per_bar_vol * 0.5)
        # Volume around a per-symbol baseline. JPY pairs trade in
        # different units but for the synthetic provider we just need
        # a positive integer.
        volume_noise = shocks[:, 3]

        # Walk the GBM in float64.
        close_prices = np.empty(bar_count, dtype=np.float64)
        prev_close = float(params["start_price"])
        for index in range(bar_count):
            new_close = prev_close * float(np.exp(log_returns[index]))
            close_prices[index] = new_close
            prev_close = new_close

        # Decide quantisation step. Sub-pip resolution -- one extra
        # decimal beyond the pip size -- so the synthetic series can
        # exhibit pip-fraction movement.
        is_jpy = symbol.endswith("JPY")
        quant_decimals = 3 if is_jpy else 5

        # Spread is constant per symbol and stamped on every emitted
        # bar. Computed once outside the loop because the synthetic
        # provider models a static broker quote: real Oanda-quoted
        # spread varies bar-to-bar but the synthetic backend is allowed
        # to be flat (the determinism contract takes precedence over
        # micro-realism).
        spread_pips = float(_SYNTHETIC_SPREAD_PIPS[symbol])
        pip_size_decimal = _PIP_SIZES[symbol]
        spread_value = self._quantise(spread_pips * float(pip_size_decimal), quant_decimals)

        # Build candles one bar at a time.
        candles: list[Candle] = []
        bar_open = float(params["start_price"])
        for index in range(bar_count):
            bar_close = float(close_prices[index])
            high_factor = float(np.exp(high_excursions[index]))
            low_factor = float(np.exp(-low_excursions[index]))
            raw_high = max(bar_open, bar_close) * high_factor
            raw_low = min(bar_open, bar_close) * low_factor

            # Clamp to be defensive against edge-case rounding that
            # could otherwise pull high below a price or low above
            # one. This keeps the OHLC invariants strictly true even
            # after Decimal quantisation.
            raw_high = max(raw_high, bar_open, bar_close)
            raw_low = min(raw_low, bar_open, bar_close)

            volume_value = max(1, int(round(10_000.0 * float(np.exp(0.5 * volume_noise[index])))))

            timestamp = aligned_start + timedelta(seconds=bar_seconds * index)

            candle = Candle(
                symbol=symbol,
                interval=interval_enum,
                open=self._quantise(bar_open, quant_decimals),
                high=self._quantise(raw_high, quant_decimals),
                low=self._quantise(raw_low, quant_decimals),
                close=self._quantise(bar_close, quant_decimals),
                volume=volume_value,
                timestamp=timestamp,
                spread=spread_value,
            )
            candles.append(candle)
            bar_open = bar_close

        return candles

    @staticmethod
    def _quantise(value: float, decimals: int) -> Decimal:
        """
        Convert a float price to a :class:`Decimal` quantised to ``decimals`` places.

        Uses string formatting rather than ``Decimal(value)`` so the
        result is exactly the displayed digits, with no float
        artefacts leaking into the contract.
        """
        if value < 0:
            value = 0.0
        formatted = f"{value:.{decimals}f}"
        return Decimal(formatted)


__all__ = ["SyntheticFxMarketDataProvider"]
