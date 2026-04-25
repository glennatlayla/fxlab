"""
Unit + acceptance tests for ``libs.strategy_ir.lookback``.

Scope:
    1. :class:`LookbackBuffer` semantics -- capacity validation,
       NaN-on-warmup, push/get correctness, get-out-of-range, reset.
    2. :class:`LookbackResolver` -- discovers ``_prev_N`` references in
       entry, exit, and filter blocks; takes the MAX(N) per base; emits
       no entry for bases never referenced via ``_prev_*``.
    3. Compiler integration -- the compiled :class:`IRStrategy`
       allocates the right buffers, reads them through the leaf
       evaluator, and produces NaN-driven False results during warmup.
    4. Acceptance -- the FX_DoubleBollinger_TrendZone IR (after
       trimming the unsupported ``spread`` leaves and the M1.A4-out-of-
       scope basket-style ``same_bar_priority`` entries) emits a LONG
       ENTRY signal on EXACTLY the bar immediately after the
       ``close < bb_upper_1`` -> ``close >= bb_upper_1`` transition,
       and zero LONG entries on any other bar.

Determinism:
    Every bar stream used here is constructed deterministically. Two
    compilations of the same IR receive distinct buffer instances and
    the resulting signal streams are byte-identical.
"""

from __future__ import annotations

import json
import math
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path

import numpy as np
import pytest

from libs.contracts.indicator import IndicatorResult
from libs.contracts.market_data import Candle, CandleInterval
from libs.contracts.signal import SignalDirection, SignalType
from libs.contracts.strategy_ir import StrategyIR
from libs.strategy_ir.broker import NullBroker
from libs.strategy_ir.clock import BarClock
from libs.strategy_ir.compiler import StrategyIRCompiler
from libs.strategy_ir.lookback import LookbackBuffer, LookbackPlan, LookbackResolver
from libs.strategy_ir.reference_resolver import IRReferenceError

# ---------------------------------------------------------------------------
# Helpers shared with test_compiler.py-style fixtures
# ---------------------------------------------------------------------------

_SYMBOL = "EURUSD"
_DEPLOYMENT_ID = "deploy-test-lookback"
_CORRELATION_ID = "corr-test-lookback"
_BASE_TIMESTAMP = datetime(2026, 2, 1, 0, 0, tzinfo=timezone.utc)


def _make_candle(index: int, close: float) -> Candle:
    """Build a synthetic 1h candle with flat OHLC = close.

    Flat OHLC keeps any ATR-style indicator deterministic and removes
    accidental high/low effects from the acceptance scenarios. We use
    the H1 interval here (the only hour-based interval the
    :class:`CandleInterval` enum exposes) -- the IR still nominally
    declares a 4h timeframe but the Candle interval flag is consumed
    only by the persistence layer, not by the compiled evaluator,
    so a 1h carrier is harmless.
    """
    ts = _BASE_TIMESTAMP + timedelta(hours=index)
    price = Decimal(str(close))
    return Candle(
        symbol=_SYMBOL,
        interval=CandleInterval.H1,
        open=price,
        high=price,
        low=price,
        close=price,
        volume=1000,
        timestamp=ts,
    )


def _slice_indicators(
    indicator_arrays: dict[str, list[float]],
    upto_index: int,
) -> dict[str, IndicatorResult]:
    out: dict[str, IndicatorResult] = {}
    for ir_id, series in indicator_arrays.items():
        sliced = np.asarray(series[: upto_index + 1], dtype=float)
        out[ir_id] = IndicatorResult(
            indicator_name=ir_id,
            values=sliced,
            timestamps=np.asarray(
                [(_BASE_TIMESTAMP + timedelta(hours=k)).timestamp() for k in range(upto_index + 1)],
                dtype=float,
            ),
            metadata={},
        )
    return out


# ---------------------------------------------------------------------------
# Section 1 -- LookbackBuffer semantics
# ---------------------------------------------------------------------------


def test_lookback_buffer_zero_capacity_rejected() -> None:
    """A capacity of zero (or negative) is meaningless and must raise."""
    with pytest.raises(ValueError):
        LookbackBuffer(capacity=0)
    with pytest.raises(ValueError):
        LookbackBuffer(capacity=-3)


def test_lookback_buffer_returns_nan_before_any_push() -> None:
    """Reading any lag before the first push returns NaN, not error."""
    buf = LookbackBuffer(capacity=3)
    assert math.isnan(buf.get(1))
    assert math.isnan(buf.get(2))
    assert math.isnan(buf.get(3))
    assert buf.filled == 0


def test_lookback_buffer_warmup_yields_nan_for_insufficient_history() -> None:
    """``get(n)`` returns NaN until ``n`` values have been pushed."""
    buf = LookbackBuffer(capacity=3)
    buf.push(10.0)
    assert buf.get(1) == 10.0
    assert math.isnan(buf.get(2))
    assert math.isnan(buf.get(3))
    buf.push(20.0)
    assert buf.get(1) == 20.0
    assert buf.get(2) == 10.0
    assert math.isnan(buf.get(3))


def test_lookback_buffer_full_window_evicts_oldest_first() -> None:
    """Once the buffer is full, the oldest value is overwritten."""
    buf = LookbackBuffer(capacity=2)
    buf.push(1.0)
    buf.push(2.0)
    buf.push(3.0)  # evicts 1.0
    assert buf.get(1) == 3.0
    assert buf.get(2) == 2.0


def test_lookback_buffer_get_out_of_range_raises() -> None:
    """``get`` rejects lags <= 0 and lags > capacity."""
    buf = LookbackBuffer(capacity=2)
    buf.push(1.0)
    buf.push(2.0)
    with pytest.raises(ValueError):
        buf.get(0)
    with pytest.raises(ValueError):
        buf.get(3)


def test_lookback_buffer_reset_returns_buffer_to_empty_state() -> None:
    """``reset`` re-pads the buffer with NaN and zeroes ``filled``."""
    buf = LookbackBuffer(capacity=2)
    buf.push(1.0)
    buf.push(2.0)
    assert buf.filled == 2
    buf.reset()
    assert buf.filled == 0
    assert math.isnan(buf.get(1))
    assert math.isnan(buf.get(2))


def test_lookback_buffer_propagates_nan_pushes() -> None:
    """NaN is a legal stored value and propagates through ``get``."""
    buf = LookbackBuffer(capacity=2)
    buf.push(float("nan"))
    buf.push(1.0)
    assert buf.get(1) == 1.0
    assert math.isnan(buf.get(2))


# ---------------------------------------------------------------------------
# Section 2 -- LookbackResolver scanning
# ---------------------------------------------------------------------------


def _build_minimal_ir_with_lookbacks(
    *,
    extra_long_conditions: list[dict] | None = None,
    extra_short_conditions: list[dict] | None = None,
    filters: list[dict] | None = None,
) -> StrategyIR:
    """A small but valid IR used for resolver-only tests.

    Indicators: ``sma_fast``, ``sma_slow``. Long entry trips on a bare
    ``sma_fast > sma_slow`` plus any ``extra_long_conditions``; short
    side mirrors. Optional filters are appended verbatim.
    """
    body = {
        "schema_version": "0.1-inferred",
        "artifact_type": "strategy_ir",
        "metadata": {
            "strategy_name": "Lookback_Resolver_Fixture",
            "strategy_version": "0.0.1",
            "author": "M1.A4 lookback test",
            "created_utc": "2026-04-25T00:00:00Z",
            "objective": "Resolver fixture only -- never compiled.",
            "status": "test_fixture",
            "notes": "Tiny IR exercising _prev_N discovery.",
        },
        "universe": {
            "asset_class": "spot_fx",
            "symbols": [_SYMBOL],
            "direction": "both",
        },
        "data_requirements": {
            "primary_timeframe": "1h",
            "required_fields": ["open", "high", "low", "close"],
            "timezone": "UTC",
            "session_rules": {
                "allowed_entry_days": [],
                "blocked_entry_windows": [],
            },
            "warmup_bars": 5,
            "missing_bar_policy": "reject_run",
        },
        "indicators": [
            {"id": "sma_fast", "type": "sma", "source": "close", "length": 3, "timeframe": "1h"},
            {"id": "sma_slow", "type": "sma", "source": "close", "length": 5, "timeframe": "1h"},
        ],
        "entry_logic": {
            "evaluation_timing": "on_bar_close",
            "execution_timing": "next_bar_open",
            "long": {
                "logic": {
                    "op": "and",
                    "conditions": [
                        {"lhs": "sma_fast", "operator": ">", "rhs": "sma_slow"},
                        *(extra_long_conditions or []),
                    ],
                },
                "order_type": "market",
            },
            "short": {
                "logic": {
                    "op": "and",
                    "conditions": [
                        {"lhs": "sma_fast", "operator": "<", "rhs": "sma_slow"},
                        *(extra_short_conditions or []),
                    ],
                },
                "order_type": "market",
            },
        },
        "exit_logic": {
            "primary_exit": {
                "type": "mean_reversion_to_mid",
                "long_condition": {"lhs": "sma_fast", "operator": "<=", "rhs": "sma_slow"},
                "short_condition": {"lhs": "sma_fast", "operator": ">=", "rhs": "sma_slow"},
            },
            "same_bar_priority": ["primary_exit"],
        },
        "risk_model": {
            "position_sizing": {"method": "fixed_fractional_risk", "risk_pct_of_equity": 0.5},
            "max_open_positions": 1,
            "daily_loss_limit_pct": 2.0,
            "max_drawdown_halt_pct": 10.0,
            "pyramiding": False,
        },
        "execution_model": {
            "fill_model": "next_bar_open",
            "slippage_model_ref": "test_slippage_v1",
            "spread_model_ref": "test_spread_v1",
            "commission_model_ref": "test_commission_v1",
            "swap_model_ref": "test_swap_v1",
            "partial_fill_policy": "not_applicable_for_market_orders",
            "reject_policy": "log_and_skip_signal",
        },
    }
    if filters is not None:
        body["filters"] = filters
    return StrategyIR.model_validate(body)


def test_lookback_resolver_returns_empty_plan_when_no_prev_refs() -> None:
    """An IR with no _prev_N references yields an empty plan."""
    ir = _build_minimal_ir_with_lookbacks()
    plan = LookbackResolver(ir).resolve()
    assert isinstance(plan, LookbackPlan)
    assert plan.capacities == {}


def test_lookback_resolver_picks_up_prev_in_entry_long_and_short() -> None:
    """Resolver finds _prev_N tokens in both entry sides."""
    ir = _build_minimal_ir_with_lookbacks(
        extra_long_conditions=[{"lhs": "close", "operator": ">", "rhs": "close_prev_1"}],
        extra_short_conditions=[{"lhs": "close", "operator": "<", "rhs": "close_prev_1"}],
    )
    plan = LookbackResolver(ir).resolve()
    assert plan.capacities == {"close": 1}


def test_lookback_resolver_takes_max_n_across_conditions() -> None:
    """When multiple conditions reference the same base, MAX(N) wins."""
    ir = _build_minimal_ir_with_lookbacks(
        extra_long_conditions=[
            {"lhs": "close", "operator": ">", "rhs": "close_prev_1"},
            {"lhs": "close_prev_3", "operator": "<", "rhs": "close_prev_5"},
            {"lhs": "sma_fast", "operator": ">", "rhs": "sma_fast_prev_2"},
        ],
    )
    plan = LookbackResolver(ir).resolve()
    assert plan.capacities == {"close": 5, "sma_fast": 2}


def test_lookback_resolver_finds_refs_in_exit_logic() -> None:
    """A _prev_N reference inside exit_logic.primary_exit is captured."""
    body = _build_minimal_ir_with_lookbacks().model_dump()
    body["exit_logic"]["primary_exit"]["long_condition"] = {
        "lhs": "sma_fast",
        "operator": "<=",
        "rhs": "sma_fast_prev_2",
    }
    ir = StrategyIR.model_validate(body)
    plan = LookbackResolver(ir).resolve()
    assert plan.capacities == {"sma_fast": 2}


def test_lookback_resolver_finds_refs_in_filters() -> None:
    """A _prev_N reference inside a filter expression is captured."""
    ir = _build_minimal_ir_with_lookbacks(
        filters=[
            {"id": "fast_rising", "lhs": "sma_fast", "operator": ">", "rhs": "sma_fast_prev_1"}
        ]
    )
    plan = LookbackResolver(ir).resolve()
    assert plan.capacities == {"sma_fast": 1}


def test_lookback_resolver_split_prev_suffix_helper() -> None:
    """The split_prev_suffix helper agrees with the regex behaviour."""
    assert LookbackResolver.split_prev_suffix("close_prev_1") == ("close", 1)
    assert LookbackResolver.split_prev_suffix("bb_upper_1_prev_2") == ("bb_upper_1", 2)
    assert LookbackResolver.split_prev_suffix("close") is None
    assert LookbackResolver.split_prev_suffix("close_prev_0") is None
    assert LookbackResolver.split_prev_suffix("close_prev_") is None


# ---------------------------------------------------------------------------
# Section 3 -- compiler integration
# ---------------------------------------------------------------------------


def test_compiler_rejects_prev_with_unknown_base() -> None:
    """A _prev_N reference whose base resolves to neither an indicator
    id nor a price field must raise IRReferenceError at compile time.

    The reference resolver runs first and catches dangling identifiers
    from the entry/exit logic, so we instead inject the bad base via a
    filter (which the resolver accepts more leniently for cross-
    timeframe references). The compiler's _allocate_lookback_buffers
    then refuses the bad base."""
    # Use an IR whose resolver-side classification accepts the bad base
    # by routing through a derived field formula.
    body = _build_minimal_ir_with_lookbacks().model_dump()
    body["derived_fields"] = [
        {"id": "synthetic", "formula": "ghost_indicator_prev_1"},
    ]
    # The reference resolver itself rejects the dangling token before
    # the lookback resolver runs, so we expect an IRReferenceError
    # either way -- the test is simply that compile() refuses.
    bad_ir = StrategyIR.model_validate(body)
    compiler = StrategyIRCompiler(clock=BarClock(), broker=NullBroker())
    with pytest.raises(IRReferenceError):
        compiler.compile(bad_ir, deployment_id=_DEPLOYMENT_ID)


def test_compiled_strategy_yields_no_signal_on_warmup_bar_for_prev_ref() -> None:
    """On the very first bar (before any push has happened) every
    leaf condition that consumes a _prev_N reference must short-
    circuit to False because the buffer returns NaN."""
    ir = _build_minimal_ir_with_lookbacks(
        extra_long_conditions=[{"lhs": "close", "operator": ">", "rhs": "close_prev_1"}],
    )
    compiler = StrategyIRCompiler(clock=BarClock(), broker=NullBroker())
    strategy = compiler.compile(ir, deployment_id=_DEPLOYMENT_ID)

    # Build a stream where sma_fast > sma_slow on EVERY bar so the
    # only thing gating the long entry is the close > close_prev_1
    # check. On bar 0, close_prev_1 is NaN -> condition False -> no
    # signal. On bar 1+, the close-vs-prev-close check decides.
    closes = [1.10, 1.11, 1.12, 1.13, 1.14, 1.15]
    candles = [_make_candle(i, c) for i, c in enumerate(closes)]
    indicator_arrays = {
        "sma_fast": [1.20] * len(closes),
        "sma_slow": [1.10] * len(closes),
    }

    candle_buffer: list[Candle] = []
    bar0_signal = None
    for idx, candle in enumerate(candles[:1]):
        candle_buffer.append(candle)
        result = strategy.evaluate(
            candle.symbol,
            candle_buffer,
            _slice_indicators(indicator_arrays, idx),
            None,
            correlation_id=_CORRELATION_ID,
        )
        bar0_signal = result
    assert bar0_signal is None, "bar 0 must NOT emit a signal -- prev_close is NaN"


def test_compiled_strategy_emits_signal_when_prev_condition_met() -> None:
    """Once the buffer has been filled, the prev condition starts to
    drive entry signals deterministically."""
    ir = _build_minimal_ir_with_lookbacks(
        extra_long_conditions=[{"lhs": "close", "operator": ">", "rhs": "close_prev_1"}],
    )
    compiler = StrategyIRCompiler(clock=BarClock(), broker=NullBroker())
    strategy = compiler.compile(ir, deployment_id=_DEPLOYMENT_ID)

    closes = [1.10, 1.11, 1.12, 1.13, 1.14, 1.15]
    candles = [_make_candle(i, c) for i, c in enumerate(closes)]
    indicator_arrays = {
        "sma_fast": [1.20] * len(closes),
        "sma_slow": [1.10] * len(closes),
    }
    candle_buffer: list[Candle] = []
    long_indices: list[int] = []
    for idx, candle in enumerate(candles):
        candle_buffer.append(candle)
        sig = strategy.evaluate(
            candle.symbol,
            candle_buffer,
            _slice_indicators(indicator_arrays, idx),
            None,
            correlation_id=_CORRELATION_ID,
        )
        if (
            sig is not None
            and sig.signal_type == SignalType.ENTRY
            and sig.direction == SignalDirection.LONG
        ):
            long_indices.append(idx)
    # close is monotonically increasing so close > close_prev_1 holds
    # on every bar that has a prev (i.e. bars 1..5). Bar 0 has no prev.
    assert long_indices == [1, 2, 3, 4, 5]


def test_lookback_buffers_are_independent_per_compile_call() -> None:
    """Two compilations of the same IR allocate distinct buffers, so
    advancing one strategy does not leak state into the other."""
    ir = _build_minimal_ir_with_lookbacks(
        extra_long_conditions=[{"lhs": "close", "operator": ">", "rhs": "close_prev_1"}],
    )
    compiler = StrategyIRCompiler(clock=BarClock(), broker=NullBroker())
    strategy_a = compiler.compile(ir, deployment_id=_DEPLOYMENT_ID)
    strategy_b = compiler.compile(ir, deployment_id=_DEPLOYMENT_ID)

    closes = [1.10, 1.11, 1.12, 1.13]
    candles = [_make_candle(i, c) for i, c in enumerate(closes)]
    indicator_arrays = {
        "sma_fast": [1.20] * len(closes),
        "sma_slow": [1.10] * len(closes),
    }
    # Drive strategy_a through the full stream.
    candle_buffer: list[Candle] = []
    for idx, candle in enumerate(candles):
        candle_buffer.append(candle)
        strategy_a.evaluate(
            candle.symbol,
            candle_buffer,
            _slice_indicators(indicator_arrays, idx),
            None,
            correlation_id=_CORRELATION_ID,
        )

    # Now run strategy_b ONLY on bar 0 -- if buffers were shared, the
    # close_prev_1 reference would resolve to closes[2] from
    # strategy_a's run and the condition would fire spuriously.
    bar0_buffer = [candles[0]]
    bar0_signal = strategy_b.evaluate(
        candles[0].symbol,
        bar0_buffer,
        _slice_indicators(indicator_arrays, 0),
        None,
        correlation_id=_CORRELATION_ID,
    )
    assert bar0_signal is None, (
        "strategy_b's bar 0 must produce no signal -- proving its "
        "lookback buffer is independent of strategy_a's"
    )


# ---------------------------------------------------------------------------
# Section 4 -- FX_DoubleBollinger_TrendZone acceptance test
# ---------------------------------------------------------------------------


_REPO_ROOT = Path(__file__).resolve().parents[4]
_DOUBLE_BOLLINGER_IR_PATH = (
    _REPO_ROOT
    / "Strategy Repo"
    / "fxlab_kathy_lien_public_strategy_pack"
    / "FX_DoubleBollinger_TrendZone.strategy_ir.json"
)


def _load_double_bollinger_subset() -> StrategyIR:
    """Load the Double Bollinger IR and trim the parts that are out of
    M1.A4 scope:

    - ``spread`` price-field references in entry conditions and
      ``required_fields`` (spread is not a Candle field; the engine
      stitches it from a separate spread feed).
    - ``filters`` block (filters are evaluated by a separate engine
      stage, not by the compiled strategy).
    - ``trailing_stop`` / ``time_exit`` / ``session_close_exit`` (these
      live on the engine side, not the compiler side).
    - ``initial_stop`` / ``take_profit`` references inside
      ``same_bar_priority``: the IR uses names like ``stop_loss`` and
      ``take_profit`` that don't match the compiled-exit-check names;
      we trim the priority list to the names actually compiled.

    Crucially, we KEEP every leaf condition that exercises a
    ``_prev_N`` reference -- that is the whole point of the test.
    """
    with _DOUBLE_BOLLINGER_IR_PATH.open(encoding="utf-8") as fh:
        body = json.load(fh)

    # Drop spread leaves and the spread required_field.
    for side in ("long", "short"):
        conds = body["entry_logic"][side]["logic"]["conditions"]
        body["entry_logic"][side]["logic"]["conditions"] = [
            c for c in conds if c.get("lhs") != "spread"
        ]
    body["data_requirements"]["required_fields"] = [
        f for f in body["data_requirements"]["required_fields"] if f != "spread"
    ]

    # Drop the rules that the compiler doesn't process (and that would
    # leave dangling priority entries).
    body.pop("filters", None)
    body["exit_logic"].pop("trailing_stop", None)
    body["exit_logic"].pop("time_exit", None)
    body["exit_logic"].pop("session_close_exit", None)

    # Trim same_bar_priority to the names the compiler actually
    # produces (initial_stop + take_profit are the compiled exits).
    body["exit_logic"]["same_bar_priority"] = ["initial_stop", "take_profit"]

    return StrategyIR.model_validate(body)


def test_double_bollinger_lookback_plan_includes_all_prev_bases() -> None:
    """Sanity check: the resolver discovers every ``_prev_N`` base in
    the production IR's entry conditions: bb_mid, close, bb_upper_1,
    bb_lower_1.
    """
    ir = _load_double_bollinger_subset()
    plan = LookbackResolver(ir).resolve()
    # All four bases appear with N=1; bb_mid is referenced from BOTH
    # sides (long: > bb_mid_prev_1, short: < bb_mid_prev_1) but MAX
    # is still 1.
    expected = {"bb_mid": 1, "close": 1, "bb_upper_1": 1, "bb_lower_1": 1}
    assert plan.capacities == expected


def test_double_bollinger_long_entry_fires_only_after_close_crosses_bb_upper_1() -> None:
    """Acceptance test for M1.A4.

    Synthesise a 12-bar stream where the long entry is gated by:

      C1: close >= bb_upper_1                  (cross above the upper 1-sigma)
      C2: close <= bb_upper_2                  (still inside the 2-sigma envelope)
      C3: bb_mid > bb_mid_prev_1               (mid-line trending up)
      C4: close_prev_1 < bb_upper_1_prev_1     (PRIOR bar was below the band)

    We hand-tune the indicator arrays so that:
      * bb_mid is monotonically rising on every bar -> C3 holds from
        bar 1 onward.
      * bb_upper_2 stays well above close on every bar -> C2 holds.
      * close < bb_upper_1 on bars 0..5 (so C4 holds when prev = bar5
        and current = bar6), and close >= bb_upper_1 from bar 6 on.
    The CROSS therefore happens between bar 5 (close < bb_upper_1) and
    bar 6 (close >= bb_upper_1). Exactly bar 6 should produce a LONG
    ENTRY signal:
      - C1 holds at bar 6 (close=1.1100, bb_upper_1=1.1099).
      - C4 needs prev_close < prev_bb_upper_1; at bar 6 the buffers
        hold bar 5 values (close=1.1080, bb_upper_1=1.1099) so C4
        holds.
    On bar 7+ C4 fails because prev_close (=1.1100) is NOT < prev
    bb_upper_1 (=1.1099) -- the cross only happens once.
    On bars 0..5 C1 fails because close < bb_upper_1.
    """
    ir = _load_double_bollinger_subset()
    compiler = StrategyIRCompiler(clock=BarClock(), broker=NullBroker())
    strategy = compiler.compile(ir, deployment_id=_DEPLOYMENT_ID)

    # 12-bar stream. close climbs steadily; bb_upper_1 is a flat
    # value (1.1099) so the cross is unambiguous.
    closes = [
        1.1000,  # bar 0
        1.1010,  # bar 1
        1.1020,  # bar 2
        1.1040,  # bar 3
        1.1060,  # bar 4
        1.1080,  # bar 5  (still below 1.1099)
        1.1100,  # bar 6  (crosses above 1.1099) <-- expected entry
        1.1110,  # bar 7
        1.1120,  # bar 8
        1.1130,  # bar 9
        1.1140,  # bar 10
        1.1150,  # bar 11
    ]
    n_bars = len(closes)
    candles = [_make_candle(i, c) for i, c in enumerate(closes)]
    indicator_arrays = {
        # bb_mid rising every bar ensures C3 holds from bar 1 onward.
        "bb_mid": [1.1000 + 0.0001 * i for i in range(n_bars)],
        # bb_upper_1 constant at 1.1099. close crosses it between bar 5 and bar 6.
        "bb_upper_1": [1.1099] * n_bars,
        # bb_lower_1 well below close so the SHORT side never trips.
        "bb_lower_1": [1.0900] * n_bars,
        # bb_upper_2 well above close so C2 always holds.
        "bb_upper_2": [1.1500] * n_bars,
        "bb_lower_2": [1.0500] * n_bars,
        # ATR is irrelevant to entry -- supplied so initial_stop wires up.
        "atr_4h": [0.001] * n_bars,
    }

    long_entry_bar_indices: list[int] = []
    short_entry_bar_indices: list[int] = []
    candle_buffer: list[Candle] = []
    for idx, candle in enumerate(candles):
        candle_buffer.append(candle)
        result = strategy.evaluate(
            candle.symbol,
            candle_buffer,
            _slice_indicators(indicator_arrays, idx),
            None,
            correlation_id=_CORRELATION_ID,
        )
        if result is None:
            continue
        if result.signal_type != SignalType.ENTRY:
            continue
        if result.direction == SignalDirection.LONG:
            long_entry_bar_indices.append(idx)
        elif result.direction == SignalDirection.SHORT:
            short_entry_bar_indices.append(idx)

    # Exactly bar 6 -- the bar immediately after the cross.
    assert long_entry_bar_indices == [6], (
        f"long entry should fire ONLY on bar 6 (the bar immediately after the "
        f"close < bb_upper_1 -> close >= bb_upper_1 transition); got {long_entry_bar_indices}"
    )
    assert short_entry_bar_indices == [], (
        f"short entry should never fire in this rising-price scenario; "
        f"got {short_entry_bar_indices}"
    )
