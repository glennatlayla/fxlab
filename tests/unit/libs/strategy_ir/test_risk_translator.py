"""
Unit tests for ``libs.strategy_ir.risk_translator``.

Coverage:
    1. ``RiskModelTranslator.translate()`` returns a CompiledRiskModel
       whose position sizer satisfies the M1.A5 acceptance constraint
       at every entry bar in a synthetic 50-bar trade blotter
       (``stop_distance * size <= risk_pct_of_equity% * equity`` with
       a small float tolerance for atr-based stop rounding).
    2. ``daily_loss_limit_pct`` blocking: simulate a sequence of
       losing trades that cumulatively breach the limit; assert the
       PreTradeGate blocks the next trade.
    3. ``max_drawdown_halt_pct`` blocking: simulate a drawdown that
       crosses the threshold; assert the PreTradeGate blocks at the
       threshold via the post-trade gate's halt latch.
    4. Sizing-method gating: deferred basket methods raise
       :class:`UnsupportedRiskMethodError` (M3.X2.5 deferral).
    5. Sizing input validation: zero stop distance, non-positive
       equity, non-positive entry price all raise
       :class:`InvalidRiskInputError`.

The tests build a programmatic StrategyIR rather than loading any
on-disk artifact so the assertions stay independent of repo-wide IR
content.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

import pytest

from libs.contracts.strategy_ir import StrategyIR
from libs.strategy_ir.risk_translator import (
    DEFERRED_SIZING_METHODS,
    SUPPORTED_SIZING_METHOD,
    ClosedTrade,
    CompiledRiskModel,
    EquityState,
    GateDecision,
    InvalidRiskInputError,
    ProposedTrade,
    RiskModelTranslator,
    UnsupportedRiskMethodError,
    assert_supported_sizing_method,
)

# ---------------------------------------------------------------------------
# Constants and helpers
# ---------------------------------------------------------------------------

_SYMBOL = "EURUSD"
_BASE_TIMESTAMP = datetime(2026, 1, 5, 0, 0, tzinfo=timezone.utc)
_STARTING_EQUITY = 100_000.0


def _ir_body(
    *,
    method: str = SUPPORTED_SIZING_METHOD,
    risk_pct: float = 0.5,
    daily_loss_pct: float = 2.0,
    max_dd_pct: float = 10.0,
) -> dict[str, Any]:
    """Build a minimal IR body customised for risk-translator tests.

    The IR carries one ATR indicator + a tiny long-side entry plus an
    atr_multiple initial stop so the entry path can be exercised by a
    downstream backtest engine if needed; for the risk-translator tests
    we only consume the ``risk_model`` block.
    """
    return {
        "schema_version": "0.1-inferred",
        "artifact_type": "strategy_ir",
        "metadata": {
            "strategy_name": "RiskTranslator_TestFixture",
            "strategy_version": "0.0.1-test",
            "author": "M1.A5 acceptance test",
            "created_utc": "2026-04-25T00:00:00Z",
            "objective": "Risk-translator harness IR.",
            "status": "test_fixture",
            "notes": "Atr-multiple stop + fixed_fractional_risk sizing.",
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
            "warmup_bars": 14,
            "missing_bar_policy": "reject_run",
        },
        "indicators": [
            {
                "id": "atr_14",
                "type": "atr",
                "length": 14,
                "timeframe": "1h",
            },
        ],
        "entry_logic": {
            "evaluation_timing": "on_bar_close",
            "execution_timing": "next_bar_open",
            "long": {
                "logic": {
                    "op": "and",
                    "conditions": [
                        {"lhs": "close", "operator": ">", "rhs": 0},
                    ],
                },
                "order_type": "market",
            },
        },
        "exit_logic": {
            "initial_stop": {
                "type": "atr_multiple",
                "indicator": "atr_14",
                "multiple": 2.0,
            },
            "same_bar_priority": ["initial_stop"],
        },
        "risk_model": {
            "position_sizing": {
                "method": method,
                "risk_pct_of_equity": risk_pct,
            },
            "max_open_positions": 1,
            "daily_loss_limit_pct": daily_loss_pct,
            "max_drawdown_halt_pct": max_dd_pct,
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


def _build_ir(**kwargs: Any) -> StrategyIR:
    """Construct a StrategyIR from :func:`_ir_body` keyword overrides."""
    return StrategyIR.model_validate(_ir_body(**kwargs))


def _make_proposed(
    *, entry_price: float = 1.10, stop_price: float = 1.0945, day_offset: int = 0
) -> ProposedTrade:
    """Helper for building a deterministic :class:`ProposedTrade`."""
    return ProposedTrade(
        symbol=_SYMBOL,
        direction="long",
        entry_price=entry_price,
        stop_price=stop_price,
        bar_timestamp=_BASE_TIMESTAMP + timedelta(days=day_offset),
    )


def _make_closed(*, pnl: float, day_offset: int = 0) -> ClosedTrade:
    """Helper for building a deterministic :class:`ClosedTrade`."""
    return ClosedTrade(
        symbol=_SYMBOL,
        realized_pnl=pnl,
        closed_at=_BASE_TIMESTAMP + timedelta(days=day_offset),
    )


# ---------------------------------------------------------------------------
# Acceptance test: 50-bar trade blotter, every entry obeys the budget
# ---------------------------------------------------------------------------


def test_acceptance_every_entry_respects_risk_pct_of_equity() -> None:
    """
    Build a StrategyIR with ``risk_pct_of_equity = 0.5`` and a synthetic
    50-bar bar stream that produces ~5 entry bars (we synthesise the
    entry events directly from a deterministic price + ATR series so the
    test does not depend on the entry-evaluator pipeline). For every
    entry bar compute ``stop_distance * size`` from the sizer output and
    assert it is ``<= 0.5%`` of the equity at entry, with a 1e-6 float
    tolerance for atr-based stop rounding.
    """
    ir = _build_ir(risk_pct=0.5)
    bundle = RiskModelTranslator(ir).translate()
    risk_fraction = 0.5 / 100.0  # 0.5%

    # Synthesise a 50-bar deterministic price + ATR series.
    bars = []
    for i in range(50):
        price = 1.10 + 0.001 * (i % 7) - 0.0005 * (i % 5)
        atr_value = 0.0010 + 0.00005 * (i % 11)  # ~10..15 pips
        bars.append((price, atr_value))

    # Pick 5 specific entry bars (workplan asks "~5 entries"). The
    # acceptance check is per-entry, so the choice of indices is
    # immaterial as long as the test exercises a non-trivial subset.
    entry_indices = [3, 11, 19, 27, 41]
    equity_at_entry = _STARTING_EQUITY  # equity does not change in this test

    for idx in entry_indices:
        entry_price, atr_value = bars[idx]
        stop_distance = 2.0 * atr_value  # the IR's atr_multiple = 2.0
        stop_price = entry_price - stop_distance
        size = bundle.position_sizer(entry_price, stop_price, equity_at_entry)
        used_risk = stop_distance * size
        budget = risk_fraction * equity_at_entry
        # The sizer's algorithm guarantees used_risk == budget exactly,
        # so a 1e-6 absolute tolerance is generous.
        assert used_risk <= budget + 1e-6, (
            f"bar {idx}: stop_distance({stop_distance})*size({size})={used_risk} "
            f"exceeds budget({budget})"
        )
        # And the sizer should also never UNDER-size when the budget
        # is positive (sanity check that the formula is doing real work).
        assert size > 0


# ---------------------------------------------------------------------------
# Determinism: two translations of the same IR produce identical
# decisions for the same equity-state event sequence.
# ---------------------------------------------------------------------------


def test_translate_is_deterministic_across_two_invocations() -> None:
    """Two translator runs over the same IR produce identical sizing
    decisions and identical gate verdicts for the same input sequences."""
    ir = _build_ir(risk_pct=0.75, daily_loss_pct=1.5, max_dd_pct=8.0)
    bundle_a = RiskModelTranslator(ir).translate()
    bundle_b = RiskModelTranslator(ir).translate()

    state_a = bundle_a.make_initial_equity_state(_STARTING_EQUITY)
    state_b = bundle_b.make_initial_equity_state(_STARTING_EQUITY)

    proposals = [
        _make_proposed(entry_price=1.10 + 0.001 * i, stop_price=1.10 + 0.001 * i - 0.005)
        for i in range(8)
    ]
    closes = [_make_closed(pnl=-50.0 - 5.0 * i, day_offset=0) for i in range(8)]

    for proposed, closed in zip(proposals, closes, strict=True):
        size_a = bundle_a.position_sizer(
            proposed.entry_price, proposed.stop_price, state_a.current_equity
        )
        size_b = bundle_b.position_sizer(
            proposed.entry_price, proposed.stop_price, state_b.current_equity
        )
        assert size_a == size_b

        decision_a = bundle_a.pre_trade_gate(proposed, state_a)
        decision_b = bundle_b.pre_trade_gate(proposed, state_b)
        assert decision_a == decision_b

        bundle_a.post_trade_gate(closed, state_a)
        bundle_b.post_trade_gate(closed, state_b)
        assert state_a == state_b


# ---------------------------------------------------------------------------
# Daily loss limit gate
# ---------------------------------------------------------------------------


def test_daily_loss_limit_blocks_next_trade_after_threshold_crossed() -> None:
    """A sequence of losing trades that cumulatively exceeds the
    ``daily_loss_limit_pct`` budget must cause the next pre-trade
    gate call to return Block."""
    # 2% of $100k = $2,000 daily loss limit.
    ir = _build_ir(daily_loss_pct=2.0, max_dd_pct=50.0)
    bundle = RiskModelTranslator(ir).translate()
    state = bundle.make_initial_equity_state(_STARTING_EQUITY)

    # Pre-trade should allow at the start.
    initial = bundle.pre_trade_gate(_make_proposed(), state)
    assert initial.allowed is True

    # Three $700 losing trades on the same day -> $2,100 total -> over $2k.
    for _ in range(3):
        bundle.post_trade_gate(_make_closed(pnl=-700.0, day_offset=0), state)
        # gate evaluation does NOT mutate; daily_realized_pnl reflects each close.
        _ = bundle.pre_trade_gate(_make_proposed(), state)

    assert state.daily_realized_pnl == pytest.approx(-2100.0)

    # The NEXT pre-trade gate call must block with the daily limit reason.
    blocked = bundle.pre_trade_gate(_make_proposed(), state)
    assert blocked.allowed is False
    assert blocked.reason == "daily_loss_limit_breached"
    assert "daily realized" in blocked.detail


def test_daily_loss_resets_on_new_trading_day() -> None:
    """Crossing the limit on one day should not block trading the next
    day -- the post-trade gate rolls the daily accumulator over."""
    ir = _build_ir(daily_loss_pct=2.0, max_dd_pct=50.0)
    bundle = RiskModelTranslator(ir).translate()
    state = bundle.make_initial_equity_state(_STARTING_EQUITY)

    # Day 0: lose $2,500 (over the limit).
    bundle.post_trade_gate(_make_closed(pnl=-2500.0, day_offset=0), state)
    blocked_day0 = bundle.pre_trade_gate(_make_proposed(day_offset=0), state)
    assert blocked_day0.allowed is False
    assert blocked_day0.reason == "daily_loss_limit_breached"

    # Day 1: a winning trade should reset the daily accumulator. The
    # post-trade gate handles rollover. After that the next pre-trade
    # gate call should allow.
    bundle.post_trade_gate(_make_closed(pnl=200.0, day_offset=1), state)
    assert state.daily_realized_pnl == pytest.approx(200.0)

    allowed_day1 = bundle.pre_trade_gate(_make_proposed(day_offset=1), state)
    assert allowed_day1.allowed is True


# ---------------------------------------------------------------------------
# Max drawdown halt gate
# ---------------------------------------------------------------------------


def test_max_drawdown_halt_blocks_trades_when_threshold_crossed() -> None:
    """A drawdown that crosses ``max_drawdown_halt_pct`` of peak
    equity must flip the EquityState into ``halted`` and the very next
    pre-trade gate call must Block with the drawdown reason."""
    # 10% drawdown halt off peak. Set daily limit very high so it does
    # not trip first.
    ir = _build_ir(daily_loss_pct=99.0, max_dd_pct=10.0)
    bundle = RiskModelTranslator(ir).translate()
    state = bundle.make_initial_equity_state(_STARTING_EQUITY)

    # Run up to a new peak first (so the drawdown anchor is unambiguous).
    bundle.post_trade_gate(_make_closed(pnl=10_000.0, day_offset=0), state)
    assert state.peak_equity == pytest.approx(110_000.0)

    # Initial gate call: still allowed.
    assert bundle.pre_trade_gate(_make_proposed(day_offset=1), state).allowed is True

    # Now bleed down by ~12% off peak in two losing trades. Peak is
    # 110k; 10% drawdown floor is 99k. Losing 12k drops us to 98k --
    # below the floor.
    bundle.post_trade_gate(_make_closed(pnl=-6_000.0, day_offset=1), state)
    assert state.halted is False  # still above floor (104k > 99k)
    bundle.post_trade_gate(_make_closed(pnl=-6_000.0, day_offset=1), state)

    # Crossed the floor; halt latch should be flipped.
    assert state.halted is True
    assert state.halt_reason == "max_drawdown_halt_breached"

    blocked = bundle.pre_trade_gate(_make_proposed(day_offset=1), state)
    assert blocked.allowed is False
    assert blocked.reason == "max_drawdown_halt_breached"
    assert "max-drawdown floor" in blocked.detail or "halted" in blocked.detail


def test_drawdown_does_not_halt_when_well_above_floor() -> None:
    """A small drawdown that stays above the floor must not halt."""
    ir = _build_ir(daily_loss_pct=99.0, max_dd_pct=20.0)
    bundle = RiskModelTranslator(ir).translate()
    state = bundle.make_initial_equity_state(_STARTING_EQUITY)
    bundle.post_trade_gate(_make_closed(pnl=-500.0, day_offset=0), state)
    assert state.halted is False
    decision = bundle.pre_trade_gate(_make_proposed(day_offset=0), state)
    assert decision.allowed is True


# ---------------------------------------------------------------------------
# Method gating: deferred + unsupported methods
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("method", sorted(DEFERRED_SIZING_METHODS))
def test_deferred_sizing_methods_raise(method: str) -> None:
    """Sizing methods still flagged as deferred must raise
    UnsupportedRiskMethodError with an explicit deferral message.

    NB: ``fixed_basket_risk`` shipped with M3.X2.5 (basket execution)
    so it is no longer in :data:`DEFERRED_SIZING_METHODS`; only the
    remaining variants (e.g. ``inverse_volatility_by_leg``) appear in
    this parametrise.
    """
    ir = _build_ir(method=method)
    with pytest.raises(UnsupportedRiskMethodError) as excinfo:
        RiskModelTranslator(ir).translate()
    msg = str(excinfo.value)
    assert method in msg
    assert "deferred" in msg


def test_fixed_basket_risk_method_now_supported() -> None:
    """``fixed_basket_risk`` shipped with M3.X2.5 and uses the same
    fixed-fractional-risk closure as ``fixed_fractional_risk``. The
    translator must produce a CompiledRiskModel without raising."""
    ir = _build_ir(method="fixed_basket_risk")
    bundle = RiskModelTranslator(ir).translate()
    assert bundle.method == "fixed_basket_risk"
    # The sizer follows the same fixed-fractional formula -- a 0.5%
    # risk budget on 100k equity with a 0.005 stop distance produces
    # 100,000 units (mirrors test_compiled_risk_model_position_sizer
    # for ``fixed_fractional_risk``).
    size = bundle.position_sizer(1.10, 1.095, 100_000.0)
    assert abs(size - 100_000.0) < 1e-6


def test_unknown_sizing_method_raises() -> None:
    """An entirely unknown sizing method must also raise."""
    ir = _build_ir(method="totally_made_up_method")
    with pytest.raises(UnsupportedRiskMethodError):
        RiskModelTranslator(ir).translate()


def test_assert_supported_sizing_method_helper() -> None:
    """The convenience helper short-circuits without building the bundle."""
    ir = _build_ir()
    # Allowed: fixed_fractional_risk (default).
    assert_supported_sizing_method(ir.risk_model)
    # Allowed: fixed_basket_risk (M3.X2.5).
    basket_ir = _build_ir(method="fixed_basket_risk")
    assert_supported_sizing_method(basket_ir.risk_model)
    # Disallowed: still-deferred methods raise.
    bad_ir = _build_ir(method="inverse_volatility_by_leg")
    with pytest.raises(UnsupportedRiskMethodError):
        assert_supported_sizing_method(bad_ir.risk_model)


# ---------------------------------------------------------------------------
# Sizing input validation
# ---------------------------------------------------------------------------


def test_sizer_rejects_zero_stop_distance() -> None:
    """A zero stop distance is undefined risk -- raise loudly."""
    ir = _build_ir()
    bundle = RiskModelTranslator(ir).translate()
    with pytest.raises(InvalidRiskInputError):
        bundle.position_sizer(1.10, 1.10, _STARTING_EQUITY)


def test_sizer_rejects_non_positive_equity() -> None:
    """Sizing against zero/negative equity is meaningless -- raise."""
    ir = _build_ir()
    bundle = RiskModelTranslator(ir).translate()
    with pytest.raises(InvalidRiskInputError):
        bundle.position_sizer(1.10, 1.0945, 0.0)
    with pytest.raises(InvalidRiskInputError):
        bundle.position_sizer(1.10, 1.0945, -1.0)


def test_sizer_rejects_non_positive_entry_price() -> None:
    """Negative or zero entry price is invalid market data -- raise."""
    ir = _build_ir()
    bundle = RiskModelTranslator(ir).translate()
    with pytest.raises(InvalidRiskInputError):
        bundle.position_sizer(0.0, -0.001, _STARTING_EQUITY)


def test_make_initial_equity_state_rejects_non_positive_starting_equity() -> None:
    """Starting equity must be positive."""
    ir = _build_ir()
    bundle = RiskModelTranslator(ir).translate()
    with pytest.raises(InvalidRiskInputError):
        bundle.make_initial_equity_state(0.0)


# ---------------------------------------------------------------------------
# CompiledRiskModel surface
# ---------------------------------------------------------------------------


def test_compiled_risk_model_carries_resolved_constants() -> None:
    """The bundle exposes the resolved float constants for debug tooling."""
    ir = _build_ir(risk_pct=0.4, daily_loss_pct=2.5, max_dd_pct=12.0)
    bundle = RiskModelTranslator(ir).translate()
    assert isinstance(bundle, CompiledRiskModel)
    assert bundle.risk_pct_of_equity == pytest.approx(0.4)
    assert bundle.daily_loss_limit_pct == pytest.approx(2.5)
    assert bundle.max_drawdown_halt_pct == pytest.approx(12.0)
    assert bundle.method == SUPPORTED_SIZING_METHOD


def test_gate_decision_factory_methods() -> None:
    """:meth:`GateDecision.allow` and ``.block`` round-trip cleanly."""
    a = GateDecision.allow()
    assert a.allowed is True
    assert a.reason == ""
    b = GateDecision.block(reason="x", detail="y")
    assert b.allowed is False
    assert b.reason == "x"
    assert b.detail == "y"


def test_equity_state_apply_close_rolls_over_day() -> None:
    """:meth:`EquityState.apply_close` resets daily P&L on a new date."""
    state = EquityState(
        starting_equity=100_000.0,
        current_equity=100_000.0,
        peak_equity=100_000.0,
    )
    state.apply_close(_make_closed(pnl=-300.0, day_offset=0))
    assert state.daily_realized_pnl == pytest.approx(-300.0)
    state.apply_close(_make_closed(pnl=-100.0, day_offset=1))
    # Day rolled over -> daily accumulator restarted.
    assert state.daily_realized_pnl == pytest.approx(-100.0)
    # current_equity is the running total, not per-day.
    assert state.current_equity == pytest.approx(99_600.0)
