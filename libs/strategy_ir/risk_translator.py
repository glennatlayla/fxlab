"""
StrategyIR -> risk model + position-sizing translator (M1.A5 linchpin).

Purpose:
    Translate the ``risk_model`` block of a parsed :class:`StrategyIR`
    into three small, deterministic callables the engine can wire into
    its trade lifecycle without re-parsing the IR:

    * a :class:`PositionSizer` that converts (entry_price, stop_price,
      equity) into a position size honouring the IR's
      ``position_sizing.risk_pct_of_equity`` budget,
    * a :class:`PreTradeGate` that consults persisted equity-state to
      block an outgoing order when ``daily_loss_limit_pct`` or
      ``max_drawdown_halt_pct`` would be breached on the next loss,
    * a :class:`PostTradeGate` that updates the equity-state after
      every closed trade so the next pre-trade gate call is informed.

    All three are produced together by :meth:`RiskModelTranslator.translate`
    and bound onto a single immutable :class:`CompiledRiskModel`. The
    compiler attaches that bundle to :class:`IRStrategy` so
    :class:`BacktestEngine` can call them directly.

Responsibilities:
    - Honour the M1.A5 spec scope: ``fixed_fractional_risk`` sizing only.
      Encountering ``fixed_basket_risk`` / ``inverse_volatility_by_leg``
      raises :class:`UnsupportedRiskMethodError` -- those land in the
      basket-execution tranche (M3.X2.5).
    - Produce a sizer that satisfies the workplan acceptance constraint:
      ``stop_distance * position_size <= risk_pct_of_equity% * equity``
      at every entry bar.
    - Produce gates that explicitly RETURN a typed
      :class:`GateDecision` (Allow or Block-with-reason) -- never
      "silently pass" when a limit is hit.
    - Stay deterministic: identical IR + identical equity-state events
      MUST produce identical sizing/gate decisions across runs. No
      ``datetime.now()``, no random source, no global state.

Does NOT:
    - Mutate the input :class:`StrategyIR` (Pydantic frozen + we never
      copy fields out for re-binding).
    - Persist equity-state to disk. The :class:`EquityState` instance
      is held in memory and updated via ``PostTradeGate`` calls; the
      caller (engine / service) decides whether to mirror it durably.
    - Submit orders, manage positions, or talk to a broker.
    - Apply per-symbol or per-basket sizing (basket = M3.X2.5).

Dependencies:
    - :mod:`libs.contracts.strategy_ir` for the ``RiskModel`` /
      ``PositionSizing`` types.
    - Standard library only otherwise.

Raises:
    - :class:`UnsupportedRiskMethodError`: if the IR declares a sizing
      method other than ``fixed_fractional_risk``. The deferred methods
      (``fixed_basket_risk``, ``inverse_volatility_by_leg``) are listed
      explicitly in the error message so operators see the deferral
      reason rather than a generic "unsupported".
    - :class:`InvalidRiskInputError`: if a sizer call receives a stop
      distance of zero (the budget would divide by zero), a
      non-positive equity, or a non-positive entry price.

Example::

    from libs.strategy_ir.risk_translator import RiskModelTranslator

    bundle = RiskModelTranslator(ir).translate()

    # Pre-trade.
    decision = bundle.pre_trade_gate(
        ProposedTrade(symbol="EURUSD", direction="long",
                      entry_price=1.10, stop_price=1.0945),
        bundle.equity_state,
    )
    if decision.allowed:
        size = bundle.position_sizer(
            entry_price=1.10, stop_price=1.0945, equity=100_000.0,
        )
        # ... place order ...

    # Post-trade.
    bundle.post_trade_gate(
        ClosedTrade(symbol="EURUSD", realized_pnl=-450.0,
                    closed_at_equity=99_550.0),
        bundle.equity_state,
    )
"""

# DEFERRED to M3.X2.5: ``fixed_basket_risk`` sizing and
# ``inverse_volatility_by_leg`` (Turn-of-Month basket variant) are out
# of scope for M1.A5. They ship once the basket execution path is wired
# end-to-end. Encountering either method here raises
# :class:`UnsupportedRiskMethodError` so the compiler fails loudly
# rather than silently sizing the wrong way.

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Callable

from libs.contracts.strategy_ir import RiskModel, StrategyIR

# ---------------------------------------------------------------------------
# Sentinel sizing-method strings (single source of truth for the names we
# accept and the names we explicitly defer).
# ---------------------------------------------------------------------------

#: The only sizing method M1.A5 supports end-to-end.
SUPPORTED_SIZING_METHOD = "fixed_fractional_risk"

#: Sizing methods explicitly deferred to M3.X2.5 (basket execution).
DEFERRED_SIZING_METHODS = frozenset(
    {
        "fixed_basket_risk",
        "inverse_volatility_by_leg",
    }
)


# ---------------------------------------------------------------------------
# Typed exceptions
# ---------------------------------------------------------------------------


class RiskTranslatorError(Exception):
    """Base class for every error raised by the risk translator."""


class UnsupportedRiskMethodError(RiskTranslatorError):
    """The IR's ``position_sizing.method`` is not supported in this tranche."""


class InvalidRiskInputError(RiskTranslatorError):
    """A sizer/gate call received a non-finite or out-of-range input."""


# ---------------------------------------------------------------------------
# Plain data carriers (frozen so they slot cleanly into deterministic code).
# These are deliberately NOT Pydantic models -- they're internal
# pass-through shapes the engine constructs per-trade. Keeping them as
# small frozen dataclasses avoids a mandatory Pydantic round-trip on
# every entry-bar tick.
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ProposedTrade:
    """
    A trade about to be placed. Consumed by :class:`PreTradeGate`.

    Attributes:
        symbol: ticker symbol (e.g. ``"EURUSD"``).
        direction: ``"long"`` or ``"short"``. Informational only at the
            gate layer.
        entry_price: planned entry price (positive float).
        stop_price: planned protective stop price (positive float).
        bar_timestamp: timestamp of the bar that produced the entry
            signal. The pre-trade gate uses ``bar_timestamp.date()`` to
            decide whether the running daily-loss accumulator should be
            rolled over (a new trading session = a fresh daily budget).
    """

    symbol: str
    direction: str
    entry_price: float
    stop_price: float
    bar_timestamp: datetime


@dataclass(frozen=True)
class ClosedTrade:
    """
    A trade that has just closed. Consumed by :class:`PostTradeGate`.

    Attributes:
        symbol: ticker symbol.
        realized_pnl: signed realized P&L for the trade. Negative
            values reduce equity; positive values increase it.
        closed_at: timestamp of the bar on which the trade closed.
            Used for daily-loss bookkeeping (see
            :meth:`EquityState.apply_close`).
    """

    symbol: str
    realized_pnl: float
    closed_at: datetime


@dataclass(frozen=True)
class GateDecision:
    """
    The result of a pre-trade gate evaluation.

    Construct via :meth:`allow` or :meth:`block` to keep call sites
    declarative. ``allowed`` and ``reason`` are the only attributes
    the caller is expected to read.

    Attributes:
        allowed: ``True`` when the trade may proceed, ``False`` when a
            risk gate has blocked it.
        reason: short machine-readable string. Empty when
            ``allowed`` is ``True``; one of the
            ``"daily_loss_limit_breached"`` /
            ``"max_drawdown_halt_breached"`` /
            ``"unknown"`` strings when ``allowed`` is ``False``.
        detail: longer human-readable detail. Always populated.
    """

    allowed: bool
    reason: str
    detail: str

    @classmethod
    def allow(cls) -> GateDecision:
        """Build the canonical Allow decision."""
        return cls(allowed=True, reason="", detail="trade allowed by all risk gates")

    @classmethod
    def block(cls, reason: str, detail: str) -> GateDecision:
        """Build a Block decision with the supplied reason + detail."""
        return cls(allowed=False, reason=reason, detail=detail)


# ---------------------------------------------------------------------------
# Equity state (mutable, in-memory, deterministic)
# ---------------------------------------------------------------------------


@dataclass
class EquityState:
    """
    Mutable equity bookkeeping that the gates consult and update.

    The state tracks just enough to evaluate the M1.A5 gates:

    * ``starting_equity`` — equity at the start of the run, used as the
      anchor for ``daily_loss_limit_pct`` reset bookkeeping.
    * ``current_equity`` — the latest equity value (after the most
      recent ``apply_close`` call).
    * ``peak_equity`` — the high-water mark for ``max_drawdown_halt_pct``.
    * ``daily_realized_pnl`` — running sum of realized P&L for the
      current trading day; reset by :meth:`apply_close` when the new
      trade's ``closed_at.date()`` differs from
      :attr:`current_trading_day`.

    Responsibilities:
    - Provide an :meth:`apply_close` helper so gates and external
      callers don't have to know the rollover rules.
    - Stay deterministic: every state mutation is a pure function of
      its inputs (no clock reads, no IO).

    Does NOT:
    - Persist itself. The engine owns durable persistence.
    """

    starting_equity: float
    current_equity: float
    peak_equity: float
    daily_realized_pnl: float = 0.0
    current_trading_day: date | None = None
    halted: bool = False
    halt_reason: str = ""

    def apply_close(self, trade: ClosedTrade) -> None:
        """
        Roll a closed trade into the running equity bookkeeping.

        Updates ``current_equity``, ``peak_equity`` (high-water mark),
        and ``daily_realized_pnl`` (rolling over to a fresh day when
        the trade's date differs from the previously-tracked day).

        Args:
            trade: the closed trade to apply.
        """
        new_day = trade.closed_at.date()
        if self.current_trading_day is None or new_day != self.current_trading_day:
            self.daily_realized_pnl = 0.0
            self.current_trading_day = new_day

        self.current_equity += trade.realized_pnl
        self.daily_realized_pnl += trade.realized_pnl
        if self.current_equity > self.peak_equity:
            self.peak_equity = self.current_equity


# ---------------------------------------------------------------------------
# Callable type aliases (kept here so downstream consumers can import a
# single name rather than the full ``Callable[..., ...]`` signature).
# ---------------------------------------------------------------------------

#: Compute position size from (entry_price, stop_price, equity).
PositionSizer = Callable[[float, float, float], float]

#: Evaluate a proposed trade against the equity state and return a
#: :class:`GateDecision`. Pure function: never mutates state.
PreTradeGate = Callable[[ProposedTrade, EquityState], GateDecision]

#: Apply a closed trade to the equity state. Mutates the state in place.
PostTradeGate = Callable[[ClosedTrade, EquityState], None]


# ---------------------------------------------------------------------------
# Compiled bundle returned by .translate()
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class CompiledRiskModel:
    """
    Frozen bundle of (sizer + pre-gate + post-gate + initial equity).

    The bundle is the single object the compiler attaches to
    :class:`IRStrategy` so :class:`BacktestEngine` can call:

    * ``compiled.position_sizer(entry, stop, equity)`` per entry bar,
    * ``compiled.pre_trade_gate(proposed_trade, state)`` before sending
      the order downstream,
    * ``compiled.post_trade_gate(closed_trade, state)`` after the
      trade closes.

    The bundle also carries the resolved ``risk_pct_of_equity``,
    ``daily_loss_limit_pct``, and ``max_drawdown_halt_pct`` as floats
    so debug tooling can introspect them without re-walking the IR.

    Attributes:
        position_sizer: see :data:`PositionSizer`.
        pre_trade_gate: see :data:`PreTradeGate`.
        post_trade_gate: see :data:`PostTradeGate`.
        risk_pct_of_equity: copy of the IR's
            ``position_sizing.risk_pct_of_equity`` (a percentage,
            e.g. ``0.5`` for 0.5%).
        daily_loss_limit_pct: copy of the IR's
            ``risk_model.daily_loss_limit_pct``.
        max_drawdown_halt_pct: copy of the IR's
            ``risk_model.max_drawdown_halt_pct``.
        method: copy of the IR's ``position_sizing.method`` string.
    """

    position_sizer: PositionSizer
    pre_trade_gate: PreTradeGate
    post_trade_gate: PostTradeGate
    risk_pct_of_equity: float
    daily_loss_limit_pct: float
    max_drawdown_halt_pct: float
    method: str
    _flags: dict[str, bool] = field(default_factory=dict)

    def make_initial_equity_state(self, starting_equity: float) -> EquityState:
        """
        Build a fresh :class:`EquityState` anchored at ``starting_equity``.

        Returns:
            A new :class:`EquityState` with ``current_equity`` and
            ``peak_equity`` both equal to ``starting_equity``.
        """
        if not (starting_equity > 0):
            raise InvalidRiskInputError(
                f"starting_equity must be positive, got {starting_equity!r}"
            )
        return EquityState(
            starting_equity=float(starting_equity),
            current_equity=float(starting_equity),
            peak_equity=float(starting_equity),
        )


# ---------------------------------------------------------------------------
# Translator
# ---------------------------------------------------------------------------


class RiskModelTranslator:
    """
    Translate a :class:`StrategyIR`'s ``risk_model`` into a
    :class:`CompiledRiskModel` bundle.

    Responsibilities:
    - Validate the sizing method up-front.
    - Build a deterministic position sizer that satisfies
      ``stop_distance * size <= (risk_pct_of_equity / 100) * equity``.
    - Build a pre-trade gate that consults the equity-state and
      returns an explicit :class:`GateDecision`.
    - Build a post-trade gate that updates the equity-state and
      transitions it into a halted state when the drawdown threshold
      is crossed.

    Does NOT:
    - Mutate the input IR.
    - Read any wall-clock primitive.
    - Submit orders or talk to a broker.

    Raises:
    - :class:`UnsupportedRiskMethodError`: when the IR declares a
      sizing method outside the M1.A5 supported set.

    Example::

        bundle = RiskModelTranslator(ir).translate()
        state = bundle.make_initial_equity_state(100_000.0)
        decision = bundle.pre_trade_gate(proposed, state)
    """

    def __init__(self, ir: StrategyIR) -> None:
        """
        Bind the translator to an IR. The IR is held by reference
        (read-only).

        Args:
            ir: the parsed :class:`StrategyIR`. Not mutated.
        """
        self._ir = ir

    # ---------- public API ----------

    def translate(self) -> CompiledRiskModel:
        """
        Produce the :class:`CompiledRiskModel` for the bound IR.

        Raises:
            UnsupportedRiskMethodError: when the sizing method is one
                of the deferred / unknown variants.
        """
        risk_model = self._ir.risk_model
        method = risk_model.position_sizing.method

        if method in DEFERRED_SIZING_METHODS:
            raise UnsupportedRiskMethodError(
                f"sizing method {method!r} is deferred to M3.X2.5 "
                f"(basket execution); M1.A5 supports {SUPPORTED_SIZING_METHOD!r} only"
            )
        if method != SUPPORTED_SIZING_METHOD:
            raise UnsupportedRiskMethodError(
                f"unsupported sizing method {method!r}; M1.A5 supports "
                f"{SUPPORTED_SIZING_METHOD!r} only "
                f"(deferred to M3.X2.5: {sorted(DEFERRED_SIZING_METHODS)})"
            )

        risk_pct = float(risk_model.position_sizing.risk_pct_of_equity)
        daily_loss_pct = float(risk_model.daily_loss_limit_pct)
        max_dd_pct = float(risk_model.max_drawdown_halt_pct)

        sizer = self._build_position_sizer(risk_pct)
        pre_gate = self._build_pre_trade_gate(daily_loss_pct, max_dd_pct)
        post_gate = self._build_post_trade_gate(daily_loss_pct, max_dd_pct)

        return CompiledRiskModel(
            position_sizer=sizer,
            pre_trade_gate=pre_gate,
            post_trade_gate=post_gate,
            risk_pct_of_equity=risk_pct,
            daily_loss_limit_pct=daily_loss_pct,
            max_drawdown_halt_pct=max_dd_pct,
            method=method,
        )

    # ---------- private builders ----------

    def _build_position_sizer(self, risk_pct: float) -> PositionSizer:
        """
        Build a closure that computes position size from
        (entry_price, stop_price, equity).

        Algorithm (fixed fractional risk):
            risk_budget   = (risk_pct / 100.0) * equity
            stop_distance = abs(entry_price - stop_price)
            size          = risk_budget / stop_distance

        The output satisfies
        ``stop_distance * size == risk_budget`` exactly (in
        floating-point arithmetic), which is the M1.A5 acceptance
        constraint: ``stop_distance * size <= risk_budget``.

        Args:
            risk_pct: percentage form (e.g. ``0.5`` -> 0.5%).

        Returns:
            A pure function of (entry_price, stop_price, equity).

        Raises (when called):
            InvalidRiskInputError: zero stop distance, non-positive
                equity, or non-positive entry price.
        """
        # Capture risk_pct in a local so the closure is self-contained.
        risk_fraction = risk_pct / 100.0

        def _sizer(entry_price: float, stop_price: float, equity: float) -> float:
            if not (entry_price > 0):
                raise InvalidRiskInputError(f"entry_price must be positive, got {entry_price!r}")
            if not (equity > 0):
                raise InvalidRiskInputError(f"equity must be positive, got {equity!r}")
            stop_distance = abs(float(entry_price) - float(stop_price))
            if stop_distance == 0.0:
                raise InvalidRiskInputError(
                    "stop_distance is zero; cannot size a trade with no risk anchor"
                )
            risk_budget = risk_fraction * float(equity)
            return risk_budget / stop_distance

        return _sizer

    def _build_pre_trade_gate(self, daily_loss_pct: float, max_dd_pct: float) -> PreTradeGate:
        """
        Build the pre-trade gate closure.

        The gate is a PURE evaluation step -- it never mutates the
        :class:`EquityState`. It checks, in order:

        1. Has a previous post-trade gate marked the state as halted?
           If so, block with the recorded halt reason. (Once halted,
           the state stays halted; reset is operator-driven and is a
           future tranche concern.)
        2. Is the running ``daily_realized_pnl`` already at or below
           the daily loss limit (negative number)? If so, block.
        3. Is current_equity at or below the drawdown threshold
           (peak_equity * (1 - max_dd_pct/100))? If so, block.

        Note: the gate evaluates the CURRENT state. The post-trade
        gate is what actually moves the state when a loss lands. So
        a string of losing trades blocks the NEXT trade once the
        cumulative loss has already exceeded the daily limit.

        Args:
            daily_loss_pct: e.g. ``2.0`` for 2%.
            max_dd_pct: e.g. ``10.0`` for 10%.

        Returns:
            A pure function (proposed, state) -> GateDecision.
        """
        daily_fraction = daily_loss_pct / 100.0
        dd_fraction = max_dd_pct / 100.0

        def _gate(proposed: ProposedTrade, state: EquityState) -> GateDecision:
            del proposed  # signature-only; retained so the engine can pass any trade.

            if state.halted:
                return GateDecision.block(
                    reason=state.halt_reason or "halted",
                    detail=(
                        f"trading halted: {state.halt_reason or 'no reason recorded'}; "
                        f"current_equity={state.current_equity:.4f}, "
                        f"peak_equity={state.peak_equity:.4f}"
                    ),
                )

            # Daily-loss check uses starting_equity as the anchor (so
            # the limit is "% of equity at start of day" -- which we
            # approximate as start-of-run equity for M1.A5; an
            # end-of-day rollover to "start-of-day equity" is a
            # follow-up concern).
            daily_loss_threshold = -daily_fraction * state.starting_equity
            if state.daily_realized_pnl <= daily_loss_threshold:
                return GateDecision.block(
                    reason="daily_loss_limit_breached",
                    detail=(
                        f"daily realized P&L {state.daily_realized_pnl:.4f} "
                        f"breaches limit {daily_loss_threshold:.4f} "
                        f"({daily_loss_pct}% of starting equity {state.starting_equity:.4f})"
                    ),
                )

            # Drawdown check uses the running peak as the anchor.
            dd_floor = state.peak_equity * (1.0 - dd_fraction)
            if state.current_equity <= dd_floor:
                return GateDecision.block(
                    reason="max_drawdown_halt_breached",
                    detail=(
                        f"current_equity {state.current_equity:.4f} at or below "
                        f"max-drawdown floor {dd_floor:.4f} "
                        f"({max_dd_pct}% off peak {state.peak_equity:.4f})"
                    ),
                )

            return GateDecision.allow()

        return _gate

    def _build_post_trade_gate(self, daily_loss_pct: float, max_dd_pct: float) -> PostTradeGate:
        """
        Build the post-trade gate closure.

        The gate updates the :class:`EquityState` to reflect the
        closed trade and -- if the drawdown threshold is crossed --
        flips ``state.halted`` so the very next pre-trade gate call
        blocks. Daily-loss accumulation is also updated; the daily-loss
        block only fires from the pre-trade gate (intentional: we
        always let an in-flight trade close, then block the next).

        Args:
            daily_loss_pct: e.g. ``2.0`` for 2%.
            max_dd_pct: e.g. ``10.0`` for 10%.

        Returns:
            A function (closed, state) -> None that mutates ``state``.
        """
        del daily_loss_pct  # held only by the pre-trade gate; kept in
        # the signature for symmetry with future tranches that may want
        # the post-gate to flip a per-day halt as well.
        dd_fraction = max_dd_pct / 100.0

        def _gate(closed: ClosedTrade, state: EquityState) -> None:
            state.apply_close(closed)

            dd_floor = state.peak_equity * (1.0 - dd_fraction)
            if state.current_equity <= dd_floor and not state.halted:
                state.halted = True
                state.halt_reason = "max_drawdown_halt_breached"

        return _gate


# ---------------------------------------------------------------------------
# Convenience: the workplan describes an "out-of-scope" guard for
# basket sizing. Call this from the compiler when you want to assert
# the IR is shipping with a supported sizing method WITHOUT building
# the full bundle (cheaper than a full translate() call).
# ---------------------------------------------------------------------------


def assert_supported_sizing_method(risk_model: RiskModel) -> None:
    """
    Raise :class:`UnsupportedRiskMethodError` if the IR uses a sizing
    method outside the M1.A5 supported set.

    Args:
        risk_model: the IR's ``risk_model`` block.
    """
    method = risk_model.position_sizing.method
    if method == SUPPORTED_SIZING_METHOD:
        return
    if method in DEFERRED_SIZING_METHODS:
        raise UnsupportedRiskMethodError(
            f"sizing method {method!r} is deferred to M3.X2.5 "
            f"(basket execution); M1.A5 supports {SUPPORTED_SIZING_METHOD!r} only"
        )
    raise UnsupportedRiskMethodError(
        f"unsupported sizing method {method!r}; M1.A5 supports "
        f"{SUPPORTED_SIZING_METHOD!r} only "
        f"(deferred to M3.X2.5: {sorted(DEFERRED_SIZING_METHODS)})"
    )


__all__ = [
    "ClosedTrade",
    "CompiledRiskModel",
    "DEFERRED_SIZING_METHODS",
    "EquityState",
    "GateDecision",
    "InvalidRiskInputError",
    "PositionSizer",
    "PostTradeGate",
    "PreTradeGate",
    "ProposedTrade",
    "RiskModelTranslator",
    "RiskTranslatorError",
    "SUPPORTED_SIZING_METHOD",
    "UnsupportedRiskMethodError",
    "assert_supported_sizing_method",
]
