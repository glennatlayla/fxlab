"""
Unit tests for libs.strategy_ir.mocks.mock_market_data_provider.MockMarketDataProvider.

Scope:
    Verify the mock satisfies
    :class:`MarketDataProviderInterface` end-to-end:

        * fetch_bars returns canned data for known keys and an
          empty list for unknown keys (no error).
        * fetch_bars returns a defensive copy so mutating the
          returned list cannot pollute the canned data.
        * get_pip_size returns the correct value for each major
          and a safe default for unknown symbols.
        * supports returns True for canned-data symbols and seeded
          pip-size symbols; False for everything else.
        * Introspection helpers (fetch_calls, clear) work.
        * Construction copies the canned dict so caller mutation
          does not leak into the mock.
"""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

from libs.contracts.market_data import Candle, CandleInterval
from libs.strategy_ir.interfaces.market_data_provider_interface import (
    MarketDataProviderInterface,
)
from libs.strategy_ir.mocks.mock_market_data_provider import MockMarketDataProvider

# ---------------------------------------------------------------------------
# Test data builders
# ---------------------------------------------------------------------------


def _candle(timestamp: datetime, close: str = "1.1000") -> Candle:
    """Build a single Candle for testing."""
    return Candle(
        symbol="EURUSD",
        interval=CandleInterval.H1,
        open=Decimal("1.1000"),
        high=Decimal("1.1010"),
        low=Decimal("1.0995"),
        close=Decimal(close),
        volume=12_345,
        timestamp=timestamp,
    )


_T0 = datetime(2026, 4, 25, 12, 0, tzinfo=timezone.utc)
_T1 = datetime(2026, 4, 25, 13, 0, tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# Interface conformance
# ---------------------------------------------------------------------------


def test_mock_satisfies_market_data_provider_protocol() -> None:
    """The mock must satisfy MarketDataProviderInterface structurally."""
    provider = MockMarketDataProvider()
    assert isinstance(provider, MarketDataProviderInterface)


# ---------------------------------------------------------------------------
# fetch_bars
# ---------------------------------------------------------------------------


def test_fetch_bars_returns_canned_data_for_known_key() -> None:
    """A seeded (symbol, timeframe) returns the exact canned list."""
    candles = [_candle(_T0), _candle(_T1, close="1.1020")]
    provider = MockMarketDataProvider(canned={("EURUSD", "H1"): candles})

    result = provider.fetch_bars(
        symbol="EURUSD",
        timeframe="H1",
        start=_T0,
        end=_T1,
    )

    assert result == candles


def test_fetch_bars_returns_empty_list_for_unknown_key() -> None:
    """Unknown (symbol, timeframe) returns [] (NOT an error)."""
    provider = MockMarketDataProvider()
    result = provider.fetch_bars(
        symbol="EURUSD",
        timeframe="H1",
        start=_T0,
        end=_T1,
    )
    assert result == []


def test_fetch_bars_returns_defensive_copy() -> None:
    """Mutating the returned list must not affect the canned data."""
    candles = [_candle(_T0)]
    provider = MockMarketDataProvider(canned={("EURUSD", "H1"): candles})

    first = provider.fetch_bars(symbol="EURUSD", timeframe="H1", start=_T0, end=_T1)
    first.append(_candle(_T1))

    second = provider.fetch_bars(symbol="EURUSD", timeframe="H1", start=_T0, end=_T1)
    assert len(second) == 1


def test_constructor_copies_canned_dict() -> None:
    """Mutating the dict passed to __init__ must not affect the mock."""
    canned: dict[tuple[str, str], list[Candle]] = {("EURUSD", "H1"): [_candle(_T0)]}
    provider = MockMarketDataProvider(canned=canned)

    # Mutate caller's dict after construction; mock should be unaffected.
    canned[("EURUSD", "H1")].append(_candle(_T1))
    canned[("GBPUSD", "H1")] = [_candle(_T0)]

    eur_bars = provider.fetch_bars(symbol="EURUSD", timeframe="H1", start=_T0, end=_T1)
    gbp_bars = provider.fetch_bars(symbol="GBPUSD", timeframe="H1", start=_T0, end=_T1)
    assert len(eur_bars) == 1
    assert gbp_bars == []


def test_set_canned_overwrites_prior_value() -> None:
    """set_canned must overwrite an existing canned entry."""
    provider = MockMarketDataProvider(canned={("EURUSD", "H1"): [_candle(_T0)]})
    provider.set_canned("EURUSD", "H1", [_candle(_T1, close="1.1050")])

    result = provider.fetch_bars(symbol="EURUSD", timeframe="H1", start=_T0, end=_T1)
    assert len(result) == 1
    assert result[0].close == Decimal("1.1050")


# ---------------------------------------------------------------------------
# get_pip_size
# ---------------------------------------------------------------------------


def test_get_pip_size_returns_correct_value_for_each_major() -> None:
    """The seven majors must have the correct pip size out of the box."""
    provider = MockMarketDataProvider()
    assert provider.get_pip_size("EURUSD") == Decimal("0.0001")
    assert provider.get_pip_size("GBPUSD") == Decimal("0.0001")
    assert provider.get_pip_size("USDJPY") == Decimal("0.01")
    assert provider.get_pip_size("USDCHF") == Decimal("0.0001")
    assert provider.get_pip_size("AUDUSD") == Decimal("0.0001")
    assert provider.get_pip_size("USDCAD") == Decimal("0.0001")
    assert provider.get_pip_size("NZDUSD") == Decimal("0.0001")


def test_get_pip_size_defaults_to_one_pip_for_unknown_symbol() -> None:
    """Unknown symbols get the safe Decimal('0.0001') default."""
    provider = MockMarketDataProvider()
    assert provider.get_pip_size("XAUUSD") == Decimal("0.0001")


def test_set_pip_size_overrides_default() -> None:
    """set_pip_size must override the table value for one symbol."""
    provider = MockMarketDataProvider()
    provider.set_pip_size("USDJPY", Decimal("0.001"))
    assert provider.get_pip_size("USDJPY") == Decimal("0.001")
    # Other symbols are unaffected.
    assert provider.get_pip_size("EURUSD") == Decimal("0.0001")


# ---------------------------------------------------------------------------
# supports
# ---------------------------------------------------------------------------


def test_supports_returns_true_for_pip_size_table_symbols() -> None:
    """Every major in the pip-size table is supported by default."""
    provider = MockMarketDataProvider()
    for symbol in ("EURUSD", "USDJPY", "NZDUSD"):
        assert provider.supports(symbol) is True


def test_supports_returns_true_for_canned_data_symbol() -> None:
    """A symbol with canned data is supported even if not in pip-size table."""
    provider = MockMarketDataProvider(canned={("XAUUSD", "H1"): [_candle(_T0)]})
    assert provider.supports("XAUUSD") is True


def test_supports_returns_false_for_unknown_symbol() -> None:
    """An unknown symbol with no seeded data is NOT supported."""
    provider = MockMarketDataProvider()
    assert provider.supports("BTCUSD") is False


# ---------------------------------------------------------------------------
# Introspection
# ---------------------------------------------------------------------------


def test_fetch_calls_returns_chronological_log() -> None:
    """fetch_calls must return every fetch in the order it was made."""
    provider = MockMarketDataProvider()
    provider.fetch_bars(symbol="EURUSD", timeframe="H1", start=_T0, end=_T1)
    provider.fetch_bars(symbol="GBPUSD", timeframe="M5", start=_T1, end=_T1)

    log = provider.fetch_calls()
    assert log == [
        ("EURUSD", "H1", _T0, _T1),
        ("GBPUSD", "M5", _T1, _T1),
    ]


def test_fetch_calls_returns_defensive_copy() -> None:
    """Mutating the returned log must not affect the internal state."""
    provider = MockMarketDataProvider()
    provider.fetch_bars(symbol="EURUSD", timeframe="H1", start=_T0, end=_T1)

    log = provider.fetch_calls()
    log.append(("MUTATED", "X", _T0, _T1))

    assert provider.fetch_calls() == [("EURUSD", "H1", _T0, _T1)]


def test_clear_resets_canned_pip_sizes_and_log() -> None:
    """clear() must wipe canned data, pip-size overrides, and the log."""
    provider = MockMarketDataProvider(canned={("EURUSD", "H1"): [_candle(_T0)]})
    provider.set_pip_size("USDJPY", Decimal("0.001"))
    provider.fetch_bars(symbol="EURUSD", timeframe="H1", start=_T0, end=_T1)

    provider.clear()

    # Log is empty immediately after clear (assert this BEFORE issuing
    # any further fetch calls, which would re-populate the log).
    assert provider.fetch_calls() == []
    assert provider.get_pip_size("USDJPY") == Decimal("0.01")  # back to default
    # Canned data is gone too.
    assert provider.fetch_bars(symbol="EURUSD", timeframe="H1", start=_T0, end=_T1) == []
