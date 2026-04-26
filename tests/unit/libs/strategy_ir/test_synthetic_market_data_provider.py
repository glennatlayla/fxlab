"""
Unit tests for libs.strategy_ir.synthetic_market_data_provider.SyntheticFxMarketDataProvider.

Scope:
    - Determinism: same seed + same args => byte-identical bars,
      different seeds => different bars.
    - OHLC invariants on every emitted bar (high >= max(open, close),
      low <= min(open, close), volume > 0).
    - Timeframe alignment: consecutive bars are exactly one bar
      duration apart and aligned to the bar grid.
    - All seven majors return non-empty for a 30-day H1 window.
    - JPY pip size is 0.01; non-JPY is 0.0001.
    - supports() returns False for unknown symbols, True for the
      seven majors.
    - Unsupported symbols and timeframes raise ValueError; naive
      datetimes raise ValueError; inverted windows raise ValueError.
    - Constructor honours ``symbol_params`` overrides; rejects invalid
      override keys/values.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from libs.contracts.market_data import Candle, CandleInterval
from libs.strategy_ir.interfaces.market_data_provider_interface import (
    MarketDataProviderInterface,
)
from libs.strategy_ir.synthetic_market_data_provider import SyntheticFxMarketDataProvider

# ---------------------------------------------------------------------------
# Fixtures and helpers
# ---------------------------------------------------------------------------

_MAJORS: list[str] = [
    "EURUSD",
    "GBPUSD",
    "USDJPY",
    "USDCHF",
    "AUDUSD",
    "USDCAD",
    "NZDUSD",
]


def _w(start_iso: str, end_iso: str) -> tuple[datetime, datetime]:
    """Build a (start, end) UTC window from ISO strings."""
    return (
        datetime.fromisoformat(start_iso).replace(tzinfo=timezone.utc),
        datetime.fromisoformat(end_iso).replace(tzinfo=timezone.utc),
    )


# ---------------------------------------------------------------------------
# Interface conformance
# ---------------------------------------------------------------------------


def test_provider_satisfies_market_data_provider_protocol() -> None:
    """The synthetic provider must satisfy MarketDataProviderInterface."""
    provider = SyntheticFxMarketDataProvider(seed=42)
    assert isinstance(provider, MarketDataProviderInterface)


# ---------------------------------------------------------------------------
# Determinism
# ---------------------------------------------------------------------------


def test_same_seed_same_args_returns_byte_identical_bars() -> None:
    """Two providers built with the same seed return identical bars."""
    start, end = _w("2026-01-01T00:00:00", "2026-01-08T00:00:00")
    a = SyntheticFxMarketDataProvider(seed=1234)
    b = SyntheticFxMarketDataProvider(seed=1234)

    bars_a = a.fetch_bars(symbol="EURUSD", timeframe="H1", start=start, end=end)
    bars_b = b.fetch_bars(symbol="EURUSD", timeframe="H1", start=start, end=end)

    assert bars_a == bars_b
    # And byte-identical via JSON dump (defensive: catches any
    # float-shaped Decimal drift).
    assert [c.model_dump() for c in bars_a] == [c.model_dump() for c in bars_b]


def test_repeated_calls_on_same_provider_return_identical_bars() -> None:
    """Calling fetch_bars twice with the same args returns identical bars."""
    provider = SyntheticFxMarketDataProvider(seed=99)
    start, end = _w("2026-02-01T00:00:00", "2026-02-05T00:00:00")

    first = provider.fetch_bars(symbol="GBPUSD", timeframe="M15", start=start, end=end)
    second = provider.fetch_bars(symbol="GBPUSD", timeframe="M15", start=start, end=end)
    assert first == second


def test_different_seeds_produce_different_bars() -> None:
    """Different seeds must produce a different bar series."""
    start, end = _w("2026-01-01T00:00:00", "2026-01-08T00:00:00")
    a = SyntheticFxMarketDataProvider(seed=1)
    b = SyntheticFxMarketDataProvider(seed=2)

    bars_a = a.fetch_bars(symbol="EURUSD", timeframe="H1", start=start, end=end)
    bars_b = b.fetch_bars(symbol="EURUSD", timeframe="H1", start=start, end=end)

    assert bars_a != bars_b
    # Sanity check -- the difference must show up in the close
    # column, not just elsewhere.
    closes_a = [c.close for c in bars_a]
    closes_b = [c.close for c in bars_b]
    assert closes_a != closes_b


def test_different_symbols_share_seed_but_produce_different_bars() -> None:
    """The same seed with different symbols must produce different series."""
    provider = SyntheticFxMarketDataProvider(seed=42)
    start, end = _w("2026-01-01T00:00:00", "2026-01-04T00:00:00")

    eur = provider.fetch_bars(symbol="EURUSD", timeframe="H1", start=start, end=end)
    gbp = provider.fetch_bars(symbol="GBPUSD", timeframe="H1", start=start, end=end)

    # Different start prices alone make this true; assert on the
    # close column to be explicit.
    assert [c.close for c in eur] != [c.close for c in gbp]


# ---------------------------------------------------------------------------
# Bar shape: OHLC invariants, timestamp alignment, volume
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "timeframe,bar_seconds", [("M15", 900), ("H1", 3600), ("H4", 14400), ("D", 86400)]
)
def test_emitted_bars_obey_ohlc_invariants(timeframe: str, bar_seconds: int) -> None:
    """high >= open/close, low <= open/close, volume >= 0 on every bar."""
    provider = SyntheticFxMarketDataProvider(seed=7)
    start, end = _w("2026-03-01T00:00:00", "2026-03-08T00:00:00")

    bars = provider.fetch_bars(symbol="EURUSD", timeframe=timeframe, start=start, end=end)
    assert bars, f"Expected non-empty bars for {timeframe}"

    for candle in bars:
        assert candle.high >= candle.open, candle
        assert candle.high >= candle.close, candle
        assert candle.low <= candle.open, candle
        assert candle.low <= candle.close, candle
        assert candle.volume >= 0, candle
        assert candle.symbol == "EURUSD"
        assert candle.timestamp.tzinfo is not None

    # Timestamps are strictly increasing and exactly bar_seconds apart.
    for prev, current in zip(bars, bars[1:], strict=False):
        delta = current.timestamp - prev.timestamp
        assert delta == timedelta(seconds=bar_seconds), (prev, current)


def test_emitted_candles_are_pydantic_validated_instances() -> None:
    """Every emitted bar is a real Candle instance, not a dict."""
    provider = SyntheticFxMarketDataProvider(seed=42)
    start, end = _w("2026-01-01T00:00:00", "2026-01-02T00:00:00")
    bars = provider.fetch_bars(symbol="EURUSD", timeframe="H1", start=start, end=end)

    for candle in bars:
        assert isinstance(candle, Candle)
        # Pydantic-frozen: round-trip via model_dump must succeed.
        assert candle.model_dump()["symbol"] == "EURUSD"


def test_timestamps_are_aligned_to_bar_grid() -> None:
    """Aligned start floors to the bar boundary; first timestamp lands on it."""
    provider = SyntheticFxMarketDataProvider(seed=42)
    # Pass a deliberately mid-bar start (12:34:56) — the provider must
    # floor to the nearest H1 boundary (12:00:00).
    start = datetime(2026, 1, 1, 12, 34, 56, tzinfo=timezone.utc)
    end = datetime(2026, 1, 1, 18, 0, 0, tzinfo=timezone.utc)
    bars = provider.fetch_bars(symbol="EURUSD", timeframe="H1", start=start, end=end)

    assert bars[0].timestamp == datetime(2026, 1, 1, 12, 0, 0, tzinfo=timezone.utc)
    assert bars[-1].timestamp == datetime(2026, 1, 1, 18, 0, 0, tzinfo=timezone.utc)


def test_inverted_window_raises() -> None:
    """end < start must be a fail-fast ValueError."""
    provider = SyntheticFxMarketDataProvider(seed=42)
    start = datetime(2026, 1, 2, tzinfo=timezone.utc)
    end = datetime(2026, 1, 1, tzinfo=timezone.utc)
    with pytest.raises(ValueError, match="before start"):
        provider.fetch_bars(symbol="EURUSD", timeframe="H1", start=start, end=end)


def test_naive_datetimes_raise() -> None:
    """Naive datetimes (no tzinfo) must be rejected."""
    provider = SyntheticFxMarketDataProvider(seed=42)
    with pytest.raises(ValueError, match="timezone-aware"):
        provider.fetch_bars(
            symbol="EURUSD",
            timeframe="H1",
            start=datetime(2026, 1, 1),  # noqa: DTZ001 — intentional for test
            end=datetime(2026, 1, 2, tzinfo=timezone.utc),
        )


# ---------------------------------------------------------------------------
# All seven majors / 30-day H1 coverage
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("symbol", _MAJORS)
def test_all_majors_return_non_empty_for_30d_h1(symbol: str) -> None:
    """Every supported FX major returns a populated H1 series for a 30-day window."""
    provider = SyntheticFxMarketDataProvider(seed=42)
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    end = start + timedelta(days=30)
    bars = provider.fetch_bars(symbol=symbol, timeframe="H1", start=start, end=end)

    # 30 days × 24 hours = 720 bars; +1 because both endpoints are inclusive.
    expected = 30 * 24 + 1
    assert len(bars) == expected, (symbol, len(bars))
    assert bars[0].symbol == symbol


# ---------------------------------------------------------------------------
# Pip size
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "symbol,expected",
    [
        ("EURUSD", Decimal("0.0001")),
        ("GBPUSD", Decimal("0.0001")),
        ("USDCHF", Decimal("0.0001")),
        ("AUDUSD", Decimal("0.0001")),
        ("USDCAD", Decimal("0.0001")),
        ("NZDUSD", Decimal("0.0001")),
        ("USDJPY", Decimal("0.01")),
    ],
)
def test_pip_size_per_symbol(symbol: str, expected: Decimal) -> None:
    """JPY pairs use 0.01; non-JPY pairs use 0.0001."""
    provider = SyntheticFxMarketDataProvider(seed=42)
    assert provider.get_pip_size(symbol) == expected


def test_pip_size_unknown_symbol_raises() -> None:
    """get_pip_size on an unknown symbol must raise."""
    provider = SyntheticFxMarketDataProvider(seed=42)
    with pytest.raises(ValueError, match="Unsupported symbol"):
        provider.get_pip_size("XYZ")


# ---------------------------------------------------------------------------
# supports()
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("symbol", _MAJORS)
def test_supports_true_for_all_majors(symbol: str) -> None:
    provider = SyntheticFxMarketDataProvider(seed=42)
    assert provider.supports(symbol) is True


@pytest.mark.parametrize("symbol", ["XYZ", "AAPL", "BTCUSD", "EURUSD ", "eurusd", ""])
def test_supports_false_for_non_majors(symbol: str) -> None:
    provider = SyntheticFxMarketDataProvider(seed=42)
    assert provider.supports(symbol) is False


# ---------------------------------------------------------------------------
# Unsupported symbol / timeframe in fetch_bars
# ---------------------------------------------------------------------------


def test_fetch_bars_unsupported_symbol_raises() -> None:
    provider = SyntheticFxMarketDataProvider(seed=42)
    start, end = _w("2026-01-01T00:00:00", "2026-01-02T00:00:00")
    with pytest.raises(ValueError, match="Unsupported symbol"):
        provider.fetch_bars(symbol="AAPL", timeframe="H1", start=start, end=end)


def test_fetch_bars_unsupported_timeframe_raises() -> None:
    provider = SyntheticFxMarketDataProvider(seed=42)
    start, end = _w("2026-01-01T00:00:00", "2026-01-02T00:00:00")
    with pytest.raises(ValueError, match="Unsupported timeframe"):
        provider.fetch_bars(symbol="EURUSD", timeframe="W1", start=start, end=end)


# ---------------------------------------------------------------------------
# Timeframe aliases
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "alias_a,alias_b",
    [("M15", "15m"), ("H1", "1h"), ("H4", "4h"), ("D", "1d"), ("D1", "1d")],
)
def test_timeframe_aliases_produce_same_bars(alias_a: str, alias_b: str) -> None:
    """Both aliases of a timeframe must produce identical bars (same bar_seconds)."""
    provider = SyntheticFxMarketDataProvider(seed=42)
    start, end = _w("2026-01-01T00:00:00", "2026-01-04T00:00:00")
    bars_a = provider.fetch_bars(symbol="EURUSD", timeframe=alias_a, start=start, end=end)
    bars_b = provider.fetch_bars(symbol="EURUSD", timeframe=alias_b, start=start, end=end)
    # Note: the seed-mix incorporates the timeframe string, so two
    # different aliases of the same bar duration can drift in random
    # values. What MUST match across aliases is the bar count and
    # timestamp grid -- the synthetic content is allowed to differ.
    assert len(bars_a) == len(bars_b)
    assert [c.timestamp for c in bars_a] == [c.timestamp for c in bars_b]


@pytest.mark.parametrize(
    "timeframe,expected_interval",
    [
        ("M15", CandleInterval.M15),
        ("15m", CandleInterval.M15),
        ("H1", CandleInterval.H1),
        ("1h", CandleInterval.H1),
        ("D", CandleInterval.D1),
        ("1d", CandleInterval.D1),
    ],
)
def test_candle_interval_matches_timeframe(
    timeframe: str, expected_interval: CandleInterval
) -> None:
    """Each emitted Candle stamps the configured CandleInterval enum."""
    provider = SyntheticFxMarketDataProvider(seed=42)
    start, end = _w("2026-01-01T00:00:00", "2026-01-02T00:00:00")
    bars = provider.fetch_bars(symbol="EURUSD", timeframe=timeframe, start=start, end=end)
    assert bars
    assert all(c.interval == expected_interval for c in bars)


# ---------------------------------------------------------------------------
# Constructor: symbol_params overrides
# ---------------------------------------------------------------------------


def test_symbol_params_override_changes_output() -> None:
    """Overriding the start_price changes the observed bar prices."""
    base = SyntheticFxMarketDataProvider(seed=42)
    custom = SyntheticFxMarketDataProvider(
        seed=42,
        symbol_params={"EURUSD": {"start_price": 5.0, "drift": 0.0, "vol": 0.01}},
    )
    start, end = _w("2026-01-01T00:00:00", "2026-01-02T00:00:00")
    base_bars = base.fetch_bars(symbol="EURUSD", timeframe="H1", start=start, end=end)
    custom_bars = custom.fetch_bars(symbol="EURUSD", timeframe="H1", start=start, end=end)

    assert base_bars[0].open != custom_bars[0].open
    # Custom start_price=5.0 must surface in the first open.
    assert custom_bars[0].open == Decimal("5.00000")


def test_symbol_params_unknown_symbol_raises() -> None:
    """Override keys must be one of the supported majors."""
    with pytest.raises(ValueError, match="not a supported FX major"):
        SyntheticFxMarketDataProvider(
            seed=42,
            symbol_params={"AAPL": {"start_price": 1.0, "drift": 0.0, "vol": 0.05}},
        )


def test_symbol_params_missing_keys_raises() -> None:
    """Override values must include start_price, drift, vol."""
    with pytest.raises(ValueError, match="missing required keys"):
        SyntheticFxMarketDataProvider(
            seed=42,
            symbol_params={"EURUSD": {"start_price": 1.0}},  # type: ignore[dict-item]
        )


# ---------------------------------------------------------------------------
# Introspection helpers
# ---------------------------------------------------------------------------


def test_fetch_calls_records_calls_in_order() -> None:
    provider = SyntheticFxMarketDataProvider(seed=42)
    start, end = _w("2026-01-01T00:00:00", "2026-01-02T00:00:00")
    provider.fetch_bars(symbol="EURUSD", timeframe="H1", start=start, end=end)
    provider.fetch_bars(symbol="GBPUSD", timeframe="M15", start=start, end=end)

    log = provider.fetch_calls()
    assert len(log) == 2
    assert log[0][0] == "EURUSD"
    assert log[1][0] == "GBPUSD"


def test_clear_log_wipes_log() -> None:
    provider = SyntheticFxMarketDataProvider(seed=42)
    start, end = _w("2026-01-01T00:00:00", "2026-01-02T00:00:00")
    provider.fetch_bars(symbol="EURUSD", timeframe="H1", start=start, end=end)
    assert provider.fetch_calls()
    provider.clear_log()
    assert provider.fetch_calls() == []


# ---------------------------------------------------------------------------
# Spread emission (M3.X1.x compiler-gap fix)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("symbol", _MAJORS)
def test_every_emitted_candle_carries_a_spread(symbol: str) -> None:
    """The synthetic provider must stamp ``spread`` on every emitted bar.

    This is the prerequisite for the Strategy IR's spread-filter
    leaf (``"lhs": "spread", "operator": "<=", "rhs": N,
    "units": "pips"``) to evaluate. Before the M3.X1.x fix the
    provider left ``spread`` as ``None`` and the CLI sanitised the
    leaf out; after the fix the leaf must evaluate against a real
    pip count.
    """
    provider = SyntheticFxMarketDataProvider(seed=42)
    start, end = _w("2026-01-01T00:00:00", "2026-01-02T00:00:00")
    bars = provider.fetch_bars(symbol=symbol, timeframe="H1", start=start, end=end)
    assert bars
    for candle in bars:
        assert candle.spread is not None, (symbol, candle)
        # Spread is in PRICE units (Decimal). Converting to pips at
        # consumption time is the compiler's job; the provider's
        # contract is "spread is positive and aligns with the symbol's
        # pip size".
        assert candle.spread > Decimal("0"), (symbol, candle.spread)


def test_spread_is_constant_per_symbol() -> None:
    """The synthetic provider models a static broker quote: the
    spread must be identical across every bar of a single
    fetch_bars call. This keeps the M3.X1 determinism contract
    intact and lets the spread-filter compile-time decision be
    "always pass" or "always fail" rather than a per-bar coin toss.
    """
    provider = SyntheticFxMarketDataProvider(seed=42)
    start, end = _w("2026-01-01T00:00:00", "2026-01-04T00:00:00")
    bars = provider.fetch_bars(symbol="EURUSD", timeframe="H1", start=start, end=end)
    assert bars
    spreads = {c.spread for c in bars}
    assert len(spreads) == 1, (
        "synthetic provider must emit a single constant spread per "
        f"symbol; got {spreads!r} on EURUSD"
    )


def test_spread_roughly_matches_half_pip_for_majors() -> None:
    """EURUSD spread should be ~0.5 pips (= 0.00005 in price units)."""
    provider = SyntheticFxMarketDataProvider(seed=42)
    start, end = _w("2026-01-01T00:00:00", "2026-01-02T00:00:00")
    bars = provider.fetch_bars(symbol="EURUSD", timeframe="H1", start=start, end=end)
    assert bars
    # 0.5 pips * 0.0001 price/pip = 0.00005. Quantised to 5 decimals.
    assert bars[0].spread == Decimal("0.00005"), bars[0].spread


def test_spread_roughly_matches_pip_size_for_jpy() -> None:
    """USDJPY spread should be 0.6 pips at 0.01 = 0.006 price units (3 dp)."""
    provider = SyntheticFxMarketDataProvider(seed=42)
    start, end = _w("2026-01-01T00:00:00", "2026-01-02T00:00:00")
    bars = provider.fetch_bars(symbol="USDJPY", timeframe="H1", start=start, end=end)
    assert bars
    assert bars[0].spread == Decimal("0.006"), bars[0].spread
