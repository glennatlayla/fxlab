"""
In-memory mock market-data provider for unit tests.

Purpose:
    Satisfy
    :class:`libs.strategy_ir.interfaces.market_data_provider_interface.MarketDataProviderInterface`
    with deterministic, fully implemented behaviour so unit tests for
    every consumer of the Protocol can run with no I/O and no clock
    dependency.

Responsibilities:
    - Hold a pre-canned ``(symbol, timeframe) -> list[Candle]`` map
      passed at construction time.
    - Implement the three Protocol methods deterministically.
    - Track every :meth:`fetch_bars` call so tests can assert on the
      call sequence (introspection helper :meth:`fetch_calls`).
    - Provide :meth:`clear` to reset between test cases when fixtures
      reuse a single instance.

Does NOT:
    - Make any HTTP call.
    - Filter results by ``[start, end]`` -- the canned data IS the
      result for that key. Tests that need range filtering should
      seed the canned data with the exact rows they expect to see.
      (This keeps the mock simple and surprises-free; if a test sees
      a candle outside its window it is the test's fault for seeding
      it, not the mock's fault for failing to filter.)
    - Hold any mutable global state -- every instance is independent.

Dependencies:
    - :mod:`libs.contracts.market_data` for :class:`Candle`.
    - :mod:`libs.strategy_ir.interfaces.market_data_provider_interface`
      for the Protocol the mock satisfies.

Example::

    from datetime import datetime, timezone
    from decimal import Decimal

    from libs.contracts.market_data import Candle, CandleInterval
    from libs.strategy_ir.mocks.mock_market_data_provider import (
        MockMarketDataProvider,
    )

    candles = [
        Candle(
            symbol="EURUSD",
            interval=CandleInterval.H1,
            open=Decimal("1.1000"),
            high=Decimal("1.1010"),
            low=Decimal("1.0995"),
            close=Decimal("1.1005"),
            volume=12_345,
            timestamp=datetime(2026, 4, 25, 12, 0, tzinfo=timezone.utc),
        ),
    ]
    provider = MockMarketDataProvider(canned={("EURUSD", "H1"): candles})
    bars = provider.fetch_bars(
        symbol="EURUSD",
        timeframe="H1",
        start=datetime(2026, 4, 25, tzinfo=timezone.utc),
        end=datetime(2026, 4, 26, tzinfo=timezone.utc),
    )
    assert bars == candles
"""

from __future__ import annotations

import threading
from datetime import datetime
from decimal import Decimal

from libs.contracts.market_data import Candle
from libs.strategy_ir.interfaces.market_data_provider_interface import (
    MarketDataProviderInterface,
)

# ---------------------------------------------------------------------------
# Pip-size table for the seven majors (deterministic, identical across runs)
# ---------------------------------------------------------------------------

#: Default pip sizes for the seven major FX pairs. JPY pairs use
#: ``0.01``; everything else uses ``0.0001``. Tests that need a
#: different value can override via :meth:`MockMarketDataProvider.set_pip_size`.
_DEFAULT_PIP_SIZES: dict[str, Decimal] = {
    "EURUSD": Decimal("0.0001"),
    "GBPUSD": Decimal("0.0001"),
    "USDJPY": Decimal("0.01"),
    "USDCHF": Decimal("0.0001"),
    "AUDUSD": Decimal("0.0001"),
    "USDCAD": Decimal("0.0001"),
    "NZDUSD": Decimal("0.0001"),
}


class MockMarketDataProvider(MarketDataProviderInterface):
    """
    Deterministic in-memory MarketDataProviderInterface implementation.

    Responsibilities:
        - Return canned candle lists for known ``(symbol, timeframe)``
          keys.
        - Return an empty list for keys that were not seeded (NOT an
          error -- vendors return empty windows when they have no
          data and the Protocol mirrors that).
        - Report support for any symbol that appears in the canned
          map OR in the pip-size table.
        - Track every ``fetch_bars`` call for test introspection.

    Does NOT:
        - Filter by ``[start, end]`` -- see module docstring.
        - Mutate the canned data after construction; the dict is
          deep-copied at construction time so tests cannot accidentally
          share state through the input dict.

    Thread safety:
        Reads and writes to the call-log are guarded by a lock so
        tests that exercise concurrent code paths see a consistent
        log.
    """

    def __init__(
        self,
        *,
        canned: dict[tuple[str, str], list[Candle]] | None = None,
    ) -> None:
        """
        Construct a mock with an optional pre-canned dataset.

        Args:
            canned: Mapping from ``(symbol, timeframe)`` to the list
                of :class:`Candle` to return. Defaults to an empty
                map when omitted (every fetch returns ``[]`` until
                seeded via :meth:`set_canned`).
        """
        # Defensive copy so the caller can mutate their original dict
        # without corrupting the mock's view.
        self._canned: dict[tuple[str, str], list[Candle]] = {
            key: list(value) for key, value in (canned or {}).items()
        }
        self._pip_sizes: dict[str, Decimal] = dict(_DEFAULT_PIP_SIZES)
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
        Return the canned candle list for ``(symbol, timeframe)``.

        Args:
            symbol: Tradable instrument key.
            timeframe: Bar-resolution string used to construct the
                key. Must match the key used when seeding.
            start: Recorded for introspection but NOT used for
                filtering -- see module docstring.
            end: Same as ``start``.

        Returns:
            A NEW list (defensive copy) of canned candles, or an
            empty list when the key was not seeded.
        """
        with self._lock:
            self._fetch_log.append((symbol, timeframe, start, end))
            return list(self._canned.get((symbol, timeframe), []))

    def get_pip_size(self, symbol: str) -> Decimal:
        """
        Return the pip size for ``symbol``.

        Args:
            symbol: Tradable instrument.

        Returns:
            The pip size from the table. Defaults to
            ``Decimal("0.0001")`` for any symbol not explicitly
            seeded -- mirrors the safe-default behaviour real
            adapters use for unknown majors.
        """
        return self._pip_sizes.get(symbol, Decimal("0.0001"))

    def supports(self, symbol: str) -> bool:
        """
        Report whether the mock can serve ``symbol``.

        A symbol is considered supported when it appears in the
        canned-data map OR in the pip-size table. This matches what
        a real adapter would report (it serves anything in its
        instruments catalog, regardless of whether the test happens
        to have seeded data for it yet).

        Args:
            symbol: Tradable instrument.

        Returns:
            ``True`` if the symbol is in either internal map.
        """
        if symbol in self._pip_sizes:
            return True
        return any(canned_symbol == symbol for canned_symbol, _ in self._canned)

    # ------------------------------------------------------------------
    # Seeding helpers (tests use these between assertions)
    # ------------------------------------------------------------------

    def set_canned(
        self,
        symbol: str,
        timeframe: str,
        candles: list[Candle],
    ) -> None:
        """
        Seed (or overwrite) the canned candle list for one key.

        Args:
            symbol: Tradable instrument.
            timeframe: Bar resolution.
            candles: New canned list. A defensive copy is stored so
                later mutation of the caller's list does not affect
                future fetches.
        """
        with self._lock:
            self._canned[(symbol, timeframe)] = list(candles)

    def set_pip_size(self, symbol: str, pip_size: Decimal) -> None:
        """
        Override the pip size for ``symbol``.

        Args:
            symbol: Tradable instrument.
            pip_size: New pip size. Stored as-is; callers should pass
                a :class:`Decimal` to preserve precision.
        """
        with self._lock:
            self._pip_sizes[symbol] = pip_size

    # ------------------------------------------------------------------
    # Introspection helpers (test assertions use these)
    # ------------------------------------------------------------------

    def fetch_calls(self) -> list[tuple[str, str, datetime, datetime]]:
        """
        Return a copy of the call log in chronological order.

        Each entry is ``(symbol, timeframe, start, end)``.
        """
        with self._lock:
            return list(self._fetch_log)

    def clear(self) -> None:
        """Wipe the canned data, pip-size overrides, and the call log."""
        with self._lock:
            self._canned.clear()
            self._pip_sizes = dict(_DEFAULT_PIP_SIZES)
            self._fetch_log.clear()


__all__ = ["MockMarketDataProvider"]
