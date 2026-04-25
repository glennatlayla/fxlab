"""
StrategyIR -> SignalStrategy compiler (M1.A3 linchpin).

Purpose:
    Translate a parsed, semantically-resolved :class:`StrategyIR` into
    a concrete, immutable :class:`IRStrategy` that satisfies the
    existing :class:`SignalStrategyInterface` contract that
    :class:`BacktestEngine` already consumes. This module is the
    compile boundary between the declarative IR world (parser +
    resolver) and the imperative evaluation pipeline (engine + broker).

Responsibilities:
    - Validate every identifier referenced by an entry/exit condition
      via :class:`ReferenceResolver`. Re-raise its
      :class:`IRReferenceError` unchanged so callers see one canonical
      exception type for unresolved IR symbols.
    - Translate every leaf condition into a deterministic, side-effect
      free Python callable that consumes a per-bar evaluation context
      (current Candle + indicators dict) and returns ``bool`` (or
      ``False`` when an input is NaN -- "missing input" is never a
      true condition).
    - Translate AND/OR condition trees into evaluators that combine
      their leaf evaluators using short-circuit boolean logic.
    - Compile each enabled exit stop into an :class:`_ExitCheck` and
      freeze them in the order specified by
      ``exit_logic.same_bar_priority`` (resolved at COMPILE time, not
      per bar).
    - Produce :class:`IRStrategy`, an immutable object that:
        * exposes the compiled entry / exit evaluators,
        * holds an injected :class:`Clock` (for deterministic signal
          ``generated_at`` stamping) and :class:`Broker` (for any
          future broker-side reads),
        * builds :class:`Signal` objects whose ``signal_id`` is a pure
          function of (strategy_name, symbol, bar_timestamp,
          signal_type, direction). Two compilations of the same IR
          run against the same bar stream therefore produce
          byte-identical signal sequences.

Does NOT:
    - Mutate the input :class:`StrategyIR`. Pydantic's ``frozen=True``
      already blocks attribute writes; the compiler additionally
      avoids any in-place edits to nested mutable values.
    - Read ``datetime.now()``, ``time.time()``, or any other wall-
      clock primitive. All time stamps come from the injected Clock.
    - Reach for global state, environment variables, or random number
      generators. Same input -> same output.
    - Bake any FX-specific or broker-specific behaviour into the
      compiled object. Symbol selection, market hours, and broker
      behaviour are injected via the Clock + Broker ports.
    - Submit orders, manage positions, evaluate risk, or persist
      anything. Those are downstream responsibilities.

Dependencies:
    - :mod:`libs.contracts.strategy_ir` -- IR types.
    - :mod:`libs.contracts.interfaces.signal_strategy` -- the contract
      we satisfy.
    - :mod:`libs.contracts.signal` / market_data / indicator /
      execution -- Pydantic types that flow through ``evaluate()``.
    - :mod:`libs.strategy_ir.reference_resolver` -- exception type
      and identifier validation.
    - :mod:`libs.strategy_ir.clock` / :mod:`libs.strategy_ir.broker`
      -- the injected ports.

Raises:
    - :class:`IRReferenceError`: when the IR references an indicator
      or other identifier that is not declared, or when
      ``same_bar_priority`` lists a name not present in the configured
      exit stops.
    - :class:`ValueError`: when the IR uses an operator the compiler
      does not (yet) support (M1.A3 supports `>`, `>=`, `<`, `<=`,
      `==`, `!=`).

Example::

    from libs.contracts.strategy_ir import StrategyIR
    from libs.strategy_ir.compiler import StrategyIRCompiler
    from libs.strategy_ir.clock import BarClock
    from libs.strategy_ir.broker import NullBroker

    ir = StrategyIR.model_validate(body)
    compiler = StrategyIRCompiler(clock=BarClock(), broker=NullBroker())
    strategy = compiler.compile(ir, deployment_id="deploy-001")
    # strategy now satisfies SignalStrategyInterface; pass to BacktestEngine.
"""

from __future__ import annotations

import ast
import hashlib
import math
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Callable

from libs.contracts.indicator import IndicatorRequest, IndicatorResult
from libs.contracts.interfaces.signal_strategy import SignalStrategyInterface
from libs.contracts.signal import (
    Signal,
    SignalDirection,
    SignalStrength,
    SignalType,
)
from libs.contracts.strategy_ir import (
    AtrMultipleStop,
    CalendarExitStop,
    ChannelExitStop,
    ConditionTree,
    DirectionalEntry,
    ExitLogic,
    ExitStop,
    LeafCondition,
    MeanReversionToMidStop,
    MiddleBandCloseViolationStop,
    OppositeInnerBandTouchStop,
    RiskRewardMultipleStop,
    StrategyIR,
    ZscoreStop,
)
from libs.strategy_ir.broker import Broker
from libs.strategy_ir.clock import BarClock, Clock
from libs.strategy_ir.lookback import LookbackBuffer, LookbackPlan, LookbackResolver
from libs.strategy_ir.reference_resolver import IRReferenceError, ReferenceResolver
from libs.strategy_ir.risk_translator import (
    CompiledRiskModel,
    RiskModelTranslator,
)

if TYPE_CHECKING:
    from libs.contracts.execution import PositionSnapshot
    from libs.contracts.market_data import Candle


# ---------------------------------------------------------------------------
# Internal types
# ---------------------------------------------------------------------------


#: A leaf evaluator consumes the per-bar evaluation context and returns
#: a Python ``bool``. The context carries the current Candle, the per-id
#: indicator results dict (with the latest indicator value already
#: extracted into a ``float`` map for fast lookup), and the optional
#: current PositionSnapshot. NaN inputs short-circuit to ``False`` --
#: "no value" is never "true" for any comparison.
LeafEvaluator = Callable[["_EvalContext"], bool]

#: An exit-stop evaluator returns ``True`` when the exit condition is
#: met for the side described by the current PositionSnapshot. Stops
#: that depend on no IR identifier (e.g. take_profit by R-multiple)
#: still receive the context so their callable signature is uniform.
ExitEvaluator = Callable[["_EvalContext"], bool]


@dataclass(frozen=True)
class _EvalContext:
    """
    Per-bar evaluation context passed to every compiled leaf / stop.

    Attributes:
        candle: the current bar.
        indicator_values: latest scalar value for each IR indicator id.
            Computed once per bar (from the trailing element of each
            :class:`IndicatorResult.values` array) so leaf evaluators
            can do dict-lookup arithmetic without re-walking the
            indicators dict on every comparison.
        position: the current position for this symbol, or ``None``
            when flat. Exit checks consult ``position.quantity`` to
            decide whether the long_condition or short_condition
            applies.
        lookback_buffers: per-base ``_prev_N`` ring buffers
            (e.g. ``{"close": LookbackBuffer(2), "bb_upper_1":
            LookbackBuffer(1)}``). Empty when the IR has no
            ``_prev_N`` references. Read by identifier evaluators
            compiled for ``<base>_prev_<N>`` tokens; populated by
            :meth:`IRStrategy.evaluate` AFTER the bar's conditions
            have been evaluated, so the buffer holds prior-bar
            values when the next bar is evaluated.
    """

    candle: Candle
    indicator_values: dict[str, float]
    position: PositionSnapshot | None
    lookback_buffers: dict[str, LookbackBuffer]


@dataclass(frozen=True)
class _ExitCheck:
    """
    A single compiled exit check held in the strategy's frozen
    priority-ordered tuple.

    Attributes:
        name: the canonical name used in
            ``ExitLogic.same_bar_priority`` (e.g. ``"primary_exit"``,
            ``"initial_stop"``, ``"take_profit"``, etc.).
        evaluator: the compiled callable returning True when the exit
            should fire on the current bar.
    """

    name: str
    evaluator: ExitEvaluator


# ---------------------------------------------------------------------------
# Comparison operators -- small whitelist (no ``in``, no string ops)
# ---------------------------------------------------------------------------

_COMPARISON_OPERATORS: dict[str, Callable[[float, float], bool]] = {
    ">": lambda a, b: a > b,
    ">=": lambda a, b: a >= b,
    "<": lambda a, b: a < b,
    "<=": lambda a, b: a <= b,
    "==": lambda a, b: a == b,
    "!=": lambda a, b: a != b,
}


# ---------------------------------------------------------------------------
# Math functions allowed inside an LHS/RHS expression
# ---------------------------------------------------------------------------

_MATH_FUNCTIONS: dict[str, Callable[..., float]] = {
    "abs": abs,
    "min": min,
    "max": max,
    "sqrt": math.sqrt,
    "log": math.log,
    "exp": math.exp,
    "pow": math.pow,
    "sign": lambda x: 0.0 if x == 0 else (1.0 if x > 0 else -1.0),
    "floor": math.floor,
    "ceil": math.ceil,
    "round": round,
}


# ---------------------------------------------------------------------------
# Price field names recognised in LHS/RHS expressions
# ---------------------------------------------------------------------------

_PRICE_FIELD_GETTERS: dict[str, Callable[[Candle], float]] = {
    "open": lambda c: float(c.open),
    "high": lambda c: float(c.high),
    "low": lambda c: float(c.low),
    "close": lambda c: float(c.close),
    "volume": lambda c: float(c.volume),
}


# ---------------------------------------------------------------------------
# AST parse mode: kept as a module-level constant so the call site stays
# simple and so tooling that scans for the literal string sees one place.
# ``ast.parse`` with this mode rejects statements at the parser layer --
# only a single Python expression is accepted. Combined with the
# whitelisted-node walk below, this is the same defensive pattern used
# by :mod:`libs.strategy_ir.formula_evaluator`.
# ---------------------------------------------------------------------------

_AST_PARSE_EXPR_MODE = "eval"  # noqa: S307  -- ast.parse mode flag, not exec


# ---------------------------------------------------------------------------
# Compiled IRStrategy
# ---------------------------------------------------------------------------


class IRStrategy(SignalStrategyInterface):
    """
    Concrete signal strategy produced by :class:`StrategyIRCompiler`.

    Responsibilities:
    - Implement :class:`SignalStrategyInterface` so the existing
      :class:`BacktestEngine` can drive it identically to any other
      hand-written strategy.
    - On every ``evaluate()`` call:
        1. Snap the bar timestamp into the injected :class:`Clock`.
        2. Compute the latest scalar value for every IR indicator
           from its :class:`IndicatorResult.values` trailing element.
        3. If the symbol currently has an open position, walk the
           frozen ``exit_check_order`` tuple in priority order and
           return an EXIT signal on the first ``True`` evaluator.
        4. Otherwise evaluate the long entry first, then the short
           entry, returning the corresponding ENTRY signal on the
           first match.
    - Stamp every Signal with a deterministic ``signal_id`` derived
      from (strategy_name, symbol, bar_timestamp, signal_type,
      direction) and a ``generated_at`` sourced from the clock.

    Does NOT:
    - Manage positions, sizing, or risk gates -- those are the
      service / engine layer's responsibility.
    - Persist anything.
    - Read any wall clock or random source.

    Dependencies:
    - Constructed exclusively by :class:`StrategyIRCompiler`. Direct
      instantiation outside the compiler is supported but unusual:
      callers must pre-build the entry / exit evaluators.

    Example:
        strategy = StrategyIRCompiler(clock=clock, broker=broker).compile(ir, deployment_id="d1")
        signal = strategy.evaluate(symbol, candles, indicators, position, correlation_id="c1")
    """

    def __init__(
        self,
        *,
        ir: StrategyIR,
        deployment_id: str,
        clock: Clock,
        broker: Broker,
        long_entry_evaluator: LeafEvaluator | None,
        short_entry_evaluator: LeafEvaluator | None,
        exit_checks: tuple[_ExitCheck, ...],
        indicator_ids: tuple[str, ...],
        lookback_buffers: dict[str, LookbackBuffer] | None = None,
        risk_model: CompiledRiskModel | None = None,
    ) -> None:
        """
        Construct the compiled strategy. Normally called by
        :class:`StrategyIRCompiler.compile`.

        Args:
            ir: the source IR. Held by reference for read-only access
                to metadata (``strategy_name``, ``symbols``, etc.) at
                evaluation time. Never mutated.
            deployment_id: deployment context id stamped on every
                emitted Signal.
            clock: injected Clock; ``now()`` is called once per
                emitted signal to populate ``generated_at``.
            broker: injected Broker; held for future use by stops
                that need broker-side constants (pip values, lot
                sizes). The current compiler does not call any
                broker method, but the field is retained so the
                contract surface stays stable.
            long_entry_evaluator: compiled long-side entry callable,
                or ``None`` when the IR declares no long entry.
            short_entry_evaluator: compiled short-side entry callable,
                or ``None`` when the IR declares no short entry.
            exit_checks: priority-ordered tuple of compiled exit
                checks. Walk in order; first ``True`` wins.
            indicator_ids: tuple of every IR indicator id, used to
                build :meth:`required_indicators` deterministically.
            lookback_buffers: per-base ``_prev_N`` ring buffers, keyed
                by the base name (e.g. ``bb_upper_1`` for a
                ``bb_upper_1_prev_1`` reference, ``close`` for
                ``close_prev_2``). Sized at compile time to the MAX(N)
                seen across all conditions. ``None`` when the IR
                contains no ``_prev_N`` references at all.
            risk_model: compiled :class:`CompiledRiskModel` produced by
                :class:`RiskModelTranslator`. Wires the position sizer
                + pre-trade gate + post-trade gate produced from the
                IR's ``risk_model`` block. ``None`` is permitted only
                for callers constructing :class:`IRStrategy` directly
                with no risk-management requirement (tests using the
                pre-M1.A5 surface).
        """
        self._ir = ir
        self._deployment_id = deployment_id
        self._clock = clock
        self._broker = broker
        self._long_entry = long_entry_evaluator
        self._short_entry = short_entry_evaluator
        self._exit_checks = exit_checks
        self._indicator_ids = indicator_ids
        # Buffers are stored as a plain dict (immutable from outside
        # by convention -- _push_lookback_values is the only mutator).
        # Empty when the IR has no _prev_N references.
        self._lookback_buffers: dict[str, LookbackBuffer] = (
            dict(lookback_buffers) if lookback_buffers else {}
        )
        self._risk_model = risk_model

    # ---------- SignalStrategyInterface metadata ----------

    @property
    def strategy_id(self) -> str:
        """Unique identifier for this strategy (the IR strategy_name)."""
        return self._ir.metadata.strategy_name

    @property
    def name(self) -> str:
        """Human-readable name for this strategy (the IR strategy_name)."""
        return self._ir.metadata.strategy_name

    @property
    def supported_symbols(self) -> list[str]:
        """List of symbols this strategy can trade (from IR universe)."""
        return list(self._ir.universe.symbols)

    @property
    def exit_check_order(self) -> tuple[str, ...]:
        """
        The priority-ordered tuple of exit-check names frozen at
        compile time. Exposed so tests (and operators) can verify that
        ``same_bar_priority`` was honoured.
        """
        return tuple(check.name for check in self._exit_checks)

    @property
    def risk_model(self) -> CompiledRiskModel | None:
        """
        The :class:`CompiledRiskModel` translated from the IR's
        ``risk_model`` block, or ``None`` when the strategy was
        constructed without one (legacy/test path).

        BacktestEngine reads this to obtain the position sizer +
        pre-trade gate + post-trade gate.
        """
        return self._risk_model

    def required_indicators(self) -> list[IndicatorRequest]:
        """
        Declare the indicators the strategy needs computed.

        Returns:
            One :class:`IndicatorRequest` per IR indicator id, using
            the IR id as ``indicator_name``. The compiled strategy
            consumes its inputs keyed by IR id (``bb_mid``,
            ``rsi_14``, ...), which is the simplest and most
            unambiguous mapping for the engine to honour.
        """
        return [IndicatorRequest(indicator_name=ir_id, params={}) for ir_id in self._indicator_ids]

    # ---------- core evaluate() ----------

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
        Evaluate the current bar and (optionally) emit a signal.

        Args:
            symbol: ticker symbol.
            candles: trailing candle buffer; the LAST element is the
                bar currently being evaluated.
            indicators: dict mapping IR indicator id (or any string
                key the engine uses) to :class:`IndicatorResult`. The
                evaluator reads the trailing element of each
                ``values`` array.
            current_position: the symbol's open position, or ``None``
                when flat.
            correlation_id: tracing id stamped onto the Signal.

        Returns:
            A :class:`Signal` when an entry or exit condition fires,
            otherwise ``None``.
        """
        if not candles:
            return None
        candle = candles[-1]

        # Snap the bar timestamp into the clock ONCE per evaluate()
        # call so any signal we stamp uses the bar timestamp, not a
        # wall-clock moment.
        if isinstance(self._clock, BarClock):
            self._clock.set_bar(candle.timestamp)

        # Pre-extract latest indicator scalar values into a float dict.
        indicator_values = self._extract_latest_indicator_values(indicators)
        ctx = _EvalContext(
            candle=candle,
            indicator_values=indicator_values,
            position=current_position,
            lookback_buffers=self._lookback_buffers,
        )

        # ``_prev_N`` references must read PRIOR-bar values during this
        # bar's condition evaluation. We therefore evaluate first and
        # push the latest values into the buffers AFTER all conditions
        # have run (see ``_push_lookback_values`` below). The push
        # happens unconditionally on every evaluate() call so the
        # buffers stay in lock-step with the bar stream regardless of
        # whether a signal fires.
        try:
            # 1. Exit checks (only when a position exists).
            if current_position is not None and current_position.quantity != 0:
                for check in self._exit_checks:
                    if check.evaluator(ctx):
                        direction = (
                            SignalDirection.SHORT
                            if current_position.quantity > 0
                            else SignalDirection.LONG
                        )
                        return self._build_signal(
                            symbol=symbol,
                            candle=candle,
                            direction=direction,
                            signal_type=SignalType.EXIT,
                            indicator_values=indicator_values,
                            correlation_id=correlation_id,
                            metadata={"exit_reason": check.name},
                        )

            # 2. Entry checks (only when flat).
            if current_position is None or current_position.quantity == 0:
                if self._long_entry is not None and self._long_entry(ctx):
                    return self._build_signal(
                        symbol=symbol,
                        candle=candle,
                        direction=SignalDirection.LONG,
                        signal_type=SignalType.ENTRY,
                        indicator_values=indicator_values,
                        correlation_id=correlation_id,
                        metadata={"side": "long"},
                    )
                if self._short_entry is not None and self._short_entry(ctx):
                    return self._build_signal(
                        symbol=symbol,
                        candle=candle,
                        direction=SignalDirection.SHORT,
                        signal_type=SignalType.ENTRY,
                        indicator_values=indicator_values,
                        correlation_id=correlation_id,
                        metadata={"side": "short"},
                    )
            return None
        finally:
            # Update lookback buffers with THIS bar's values so the
            # NEXT bar's evaluator sees them as "prev". Done in a
            # finally block so an early return above still advances
            # the buffers in lock-step with the bar stream.
            self._push_lookback_values(candle, indicator_values)

    # ---------- internal helpers ----------

    def _extract_latest_indicator_values(
        self, indicators: dict[str, IndicatorResult]
    ) -> dict[str, float]:
        """
        Pull the trailing scalar value of every supplied indicator
        into a flat ``{ir_id: float}`` dict.

        - Indicators whose ``values`` array is empty contribute NaN
          (so leaf evaluators short-circuit to False rather than
          raising).
        - Multi-component indicators are not supported in M1.A3; the
          ``components`` dict is ignored.
        """
        out: dict[str, float] = {}
        for ir_id, result in indicators.items():
            values = result.values
            if values is None:
                out[ir_id] = float("nan")
                continue
            try:
                length = len(values)
            except TypeError:
                # Scalar value; treat it as the latest reading.
                out[ir_id] = float(values)
                continue
            if length == 0:
                out[ir_id] = float("nan")
                continue
            out[ir_id] = float(values[-1])
        return out

    def _push_lookback_values(self, candle: Candle, indicator_values: dict[str, float]) -> None:
        """
        Append THIS bar's value of every tracked base into its
        :class:`LookbackBuffer`.

        The base is either an IR indicator id (read from
        ``indicator_values``) or one of the supported price-field
        names (read directly from the candle via
        :data:`_PRICE_FIELD_GETTERS`). A base whose value is unknown
        on this bar (e.g. an indicator that was never supplied)
        contributes NaN -- the buffer's :meth:`get` will then yield
        NaN at the corresponding lag and the leaf evaluator will
        short-circuit cleanly.
        """
        if not self._lookback_buffers:
            return
        for base, buffer in self._lookback_buffers.items():
            if base in _PRICE_FIELD_GETTERS:
                buffer.push(_PRICE_FIELD_GETTERS[base](candle))
                continue
            buffer.push(indicator_values.get(base, float("nan")))

    def _build_signal(
        self,
        *,
        symbol: str,
        candle: Candle,
        direction: SignalDirection,
        signal_type: SignalType,
        indicator_values: dict[str, float],
        correlation_id: str,
        metadata: dict[str, Any],
    ) -> Signal:
        """
        Construct a :class:`Signal` with a deterministic ``signal_id``
        and a ``generated_at`` sourced from the injected clock.

        ``signal_id`` is the SHA-256 of a canonical key joining
        (strategy_name, symbol, bar_timestamp ISO, signal_type,
        direction). This keeps the id a pure function of the inputs
        (no ULID / random / wall-clock entropy) so two compilations of
        the same IR produce byte-identical signal streams.
        """
        canonical = "|".join(
            [
                self._ir.metadata.strategy_name,
                symbol,
                candle.timestamp.isoformat(),
                signal_type.value,
                direction.value,
            ]
        )
        digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
        signal_id = f"sig-{digest[:32]}"
        generated_at = self._clock.now()

        # Filter indicator_values to those that are finite floats so
        # the Signal's indicators_used dict stays JSON-friendly.
        clean_indicators = {k: float(v) for k, v in indicator_values.items() if not math.isnan(v)}

        return Signal(
            signal_id=signal_id,
            strategy_id=self._ir.metadata.strategy_name,
            deployment_id=self._deployment_id,
            symbol=symbol,
            direction=direction,
            signal_type=signal_type,
            strength=SignalStrength.MODERATE,
            confidence=1.0,
            indicators_used=clean_indicators,
            bar_timestamp=candle.timestamp,
            generated_at=generated_at,
            correlation_id=correlation_id,
            metadata=metadata,
        )


# ---------------------------------------------------------------------------
# Compiler
# ---------------------------------------------------------------------------


class StrategyIRCompiler:
    """
    Translate a :class:`StrategyIR` into an executable
    :class:`IRStrategy`.

    Responsibilities:
    - Run :class:`ReferenceResolver` over the IR to validate every
      identifier referenced by an entry/exit/filter condition. The
      resolver raises :class:`IRReferenceError` for dangling refs.
    - Compile each leaf condition into a Python callable that reads
      from a per-bar :class:`_EvalContext` and returns ``bool``.
    - Compile entry condition trees (long + short) into single
      evaluators that AND/OR their leaves.
    - Compile each enabled exit stop into an :class:`_ExitCheck` and
      freeze the resulting tuple in the order specified by
      ``exit_logic.same_bar_priority`` (resolved at COMPILE time).

    Does NOT:
    - Mutate the input IR.
    - Read any wall-clock primitive.
    - Bake FX-specific behaviour into the compiled object.

    Dependencies:
    - Injected Clock + Broker (constructor params).

    Raises:
    - :class:`IRReferenceError`: dangling identifier or
      ``same_bar_priority`` lists a name not present in the
      configured exit stops.
    - :class:`ValueError`: unsupported operator or unsupported AST
      node in an LHS/RHS expression.

    Example:
        compiler = StrategyIRCompiler(clock=BarClock(), broker=NullBroker())
        strategy = compiler.compile(ir, deployment_id="d1")
    """

    def __init__(self, *, clock: Clock, broker: Broker) -> None:
        """
        Bind the compiler to its injected Clock + Broker.

        Args:
            clock: clock the compiled IRStrategy will read for
                ``Signal.generated_at`` stamping.
            broker: broker the compiled IRStrategy will hold for
                future broker-side reads.
        """
        self._clock = clock
        self._broker = broker
        # Per-compile-call scratchpad. Populated at the top of
        # :meth:`compile` and cleared in its ``finally`` block so two
        # back-to-back compile() calls cannot leak buffers across
        # compilations.
        self._current_lookback_buffers: dict[str, LookbackBuffer] | None = None

    # ---------- public API ----------

    def compile(self, ir: StrategyIR, *, deployment_id: str) -> IRStrategy:  # noqa: A003
        """
        Compile ``ir`` into an :class:`IRStrategy`.

        Args:
            ir: the parsed IR. Not mutated.
            deployment_id: deployment context id stamped on every
                Signal emitted by the compiled strategy.

        Returns:
            A fresh :class:`IRStrategy` instance.

        Raises:
            IRReferenceError: dangling identifier or invalid
                ``same_bar_priority`` reference.
            ValueError: unsupported operator or unsupported AST node
                in an LHS/RHS expression.
        """
        # 1. Resolve every reference. Raises IRReferenceError on any
        #    dangling identifier in entry/exit/filter conditions.
        ReferenceResolver(ir).resolve()

        # 2. Build the indicator-id whitelist used by leaf compilers.
        indicator_ids: frozenset[str] = frozenset(ind.id for ind in ir.indicators)

        # 3. Scan the IR for ``_prev_N`` references and allocate one
        #    ring buffer per base, sized to MAX(N) across all
        #    references to that base. Empty when the IR has no
        #    ``_prev_N`` references at all.
        lookback_plan: LookbackPlan = LookbackResolver(ir).resolve()
        lookback_buffers = self._allocate_lookback_buffers(lookback_plan, indicator_ids)
        # Stash the freshly-allocated buffers on the compiler instance
        # so identifier compilation downstream can close over the
        # right buffer per ``<base>_prev_<N>`` token without having
        # to thread the dict through every helper signature. Cleared
        # in the finally block at the end of compile() so two
        # consecutive compile() calls cannot share state by accident.
        self._current_lookback_buffers = lookback_buffers
        try:
            # 4. Compile entry-side evaluators.
            long_eval = (
                self._compile_directional_entry(ir.entry_logic.long, indicator_ids, "long")
                if ir.entry_logic.long is not None
                else None
            )
            short_eval = (
                self._compile_directional_entry(ir.entry_logic.short, indicator_ids, "short")
                if ir.entry_logic.short is not None
                else None
            )

            # 5. Compile exit checks and freeze in priority order.
            compiled_exits = self._compile_exit_logic(ir.exit_logic, indicator_ids)
            ordered_exits = self._freeze_exit_priority(compiled_exits, ir.exit_logic)
        finally:
            self._current_lookback_buffers = None

        # 6. Translate the IR's risk_model into a compiled bundle
        #    (sizer + pre-trade gate + post-trade gate). M1.A5 only
        #    supports ``fixed_fractional_risk``; the translator raises
        #    UnsupportedRiskMethodError loudly for the deferred basket
        #    methods so a misconfigured IR fails at compile time, not
        #    at first trade.
        compiled_risk_model = RiskModelTranslator(ir).translate()

        # 7. Wrap and return.
        return IRStrategy(
            ir=ir,
            deployment_id=deployment_id,
            clock=self._clock,
            broker=self._broker,
            long_entry_evaluator=long_eval,
            short_entry_evaluator=short_eval,
            exit_checks=ordered_exits,
            indicator_ids=tuple(ind.id for ind in ir.indicators),
            risk_model=compiled_risk_model,
            lookback_buffers=lookback_buffers,
        )

    # ---------- lookback planning ----------

    def _allocate_lookback_buffers(
        self,
        plan: LookbackPlan,
        indicator_ids: frozenset[str],
    ) -> dict[str, LookbackBuffer]:
        """
        Allocate one :class:`LookbackBuffer` per base in ``plan``.

        Args:
            plan: result of :meth:`LookbackResolver.resolve`.
            indicator_ids: set of declared IR indicator ids; bases
                outside this set must be a supported price field,
                otherwise we raise :class:`IRReferenceError`.

        Returns:
            ``{base_name: LookbackBuffer}`` keyed by base. Empty when
            the IR has no ``_prev_N`` references.

        Raises:
            IRReferenceError: when a ``_prev_N`` base resolves to
                neither an indicator id nor a supported price field.
        """
        buffers: dict[str, LookbackBuffer] = {}
        for base, lag in plan.capacities.items():
            if base not in indicator_ids and base not in _PRICE_FIELD_GETTERS:
                raise IRReferenceError(
                    f"_prev_N reference base {base!r} is neither a declared "
                    f"indicator id nor a supported price field "
                    f"(supported: {sorted(_PRICE_FIELD_GETTERS.keys())})"
                )
            buffers[base] = LookbackBuffer(capacity=lag)
        return buffers

    # ---------- entry compilation ----------

    def _compile_directional_entry(
        self,
        entry: DirectionalEntry,
        indicator_ids: frozenset[str],
        side: str,
    ) -> LeafEvaluator:
        """Compile the AND/OR tree for a long or short entry."""
        return self._compile_condition_tree(
            entry.logic, indicator_ids, location=f"entry_logic.{side}.logic"
        )

    def _compile_condition_tree(
        self,
        tree: ConditionTree,
        indicator_ids: frozenset[str],
        location: str,
    ) -> LeafEvaluator:
        """Compile a ConditionTree into a single boolean evaluator."""
        op = tree.op.lower()
        if op not in {"and", "or"}:
            raise ValueError(
                f"unsupported condition tree operator {tree.op!r} at {location}; "
                f"only 'and'/'or' are supported"
            )
        child_evals: list[LeafEvaluator] = []
        for index, child in enumerate(tree.conditions):
            child_loc = f"{location}.conditions[{index}]"
            if isinstance(child, ConditionTree):
                child_evals.append(self._compile_condition_tree(child, indicator_ids, child_loc))
            else:
                child_evals.append(self._compile_leaf(child, indicator_ids, child_loc))

        # Snapshot the children into a tuple so the closure cannot be
        # mutated from outside; this also helps the interpreter avoid
        # repeated list lookup overhead.
        children = tuple(child_evals)
        if op == "and":

            def _and_eval(ctx: _EvalContext) -> bool:
                # Equivalent to ``all(c(ctx) for c in children)`` but
                # written as an explicit loop so the short-circuit
                # behaviour is unambiguous and stack traces (if any
                # leaf raises) point at the offending child index.
                return all(child_eval(ctx) for child_eval in children)

            return _and_eval

        def _or_eval(ctx: _EvalContext) -> bool:
            return any(child_eval(ctx) for child_eval in children)

        return _or_eval

    def _compile_leaf(
        self,
        leaf: LeafCondition,
        indicator_ids: frozenset[str],
        location: str,
    ) -> LeafEvaluator:
        """Compile a single leaf condition into a boolean evaluator."""
        op_fn = _COMPARISON_OPERATORS.get(leaf.operator)
        if op_fn is None:
            raise ValueError(
                f"unsupported comparison operator {leaf.operator!r} at {location}; "
                f"supported: {sorted(_COMPARISON_OPERATORS.keys())}"
            )
        lhs_fn = self._compile_value_expr(leaf.lhs, indicator_ids, f"{location}.lhs")
        rhs_value = leaf.rhs
        if isinstance(rhs_value, str):
            rhs_fn = self._compile_value_expr(rhs_value, indicator_ids, f"{location}.rhs")
        else:
            const = float(rhs_value)

            def rhs_fn(_ctx: _EvalContext, _const: float = const) -> float:
                return _const

        def _leaf_eval(ctx: _EvalContext) -> bool:
            try:
                left_val = lhs_fn(ctx)
                right_val = rhs_fn(ctx)
            except (KeyError, ValueError):
                # Missing indicator/price field at evaluation time:
                # treat as "no signal" rather than crash.
                return False
            if math.isnan(left_val) or math.isnan(right_val):
                return False
            return op_fn(left_val, right_val)

        return _leaf_eval

    # ---------- expression compilation ----------

    def _compile_value_expr(
        self,
        expression: str,
        indicator_ids: frozenset[str],
        location: str,
    ) -> Callable[[_EvalContext], float]:
        """
        Compile an LHS/RHS expression string into a callable returning
        a float at evaluation time.

        Supported syntax:
        - Bare price field name (open/high/low/close/volume).
        - Bare indicator id (must be declared in the IR).
        - Numeric literal (int or float).
        - Arithmetic combinations using + - * / and parentheses.
        - Calls to whitelisted math functions
          (abs, min, max, sqrt, log, exp, pow, sign, floor, ceil, round).

        Other syntax (subscript, attribute access, comparison,
        boolean, etc.) raises :class:`ValueError`.
        """
        try:
            tree = ast.parse(expression, mode=_AST_PARSE_EXPR_MODE)
        except SyntaxError as exc:
            raise ValueError(
                f"failed to parse expression {expression!r} at {location}: {exc.msg}"
            ) from exc

        # ``ast.parse`` is typed as returning ``ast.Module | ast.Expression
        # | ast.Interactive | ast.FunctionType`` because the return type
        # depends on the ``mode`` argument. We always pass ``mode='eval'``
        # so the result is ``ast.Expression`` and ``.body`` is a single
        # ``ast.expr`` node. Assert here so mypy can narrow the union.
        assert isinstance(tree, ast.Expression), (
            f"expected ast.Expression for mode={_AST_PARSE_EXPR_MODE!r}, got {type(tree).__name__}"
        )

        # Walk + validate. We delegate to a recursive compile pass that
        # builds a Python lambda-equivalent closure per node.
        compiled = self._compile_ast_node(tree.body, indicator_ids, location, expression)
        return compiled

    def _compile_ast_node(
        self,
        node: ast.AST,
        indicator_ids: frozenset[str],
        location: str,
        source: str,
    ) -> Callable[[_EvalContext], float]:
        """Recursively compile a whitelisted AST node."""
        if isinstance(node, ast.Constant):
            if isinstance(node.value, bool) or not isinstance(node.value, (int, float)):
                raise ValueError(
                    f"disallowed literal in expression {source!r} at {location}: "
                    f"{type(node.value).__name__}"
                )
            const = float(node.value)

            def _const_fn(_ctx: _EvalContext, _v: float = const) -> float:
                return _v

            return _const_fn

        if isinstance(node, ast.Name):
            ident = node.id
            return self._compile_identifier(ident, indicator_ids, location, source)

        if isinstance(node, ast.UnaryOp):
            operand = self._compile_ast_node(node.operand, indicator_ids, location, source)
            if isinstance(node.op, ast.UAdd):

                def _uadd(
                    ctx: _EvalContext, _f: Callable[[_EvalContext], float] = operand
                ) -> float:
                    return +_f(ctx)

                return _uadd
            if isinstance(node.op, ast.USub):

                def _usub(
                    ctx: _EvalContext, _f: Callable[[_EvalContext], float] = operand
                ) -> float:
                    return -_f(ctx)

                return _usub
            raise ValueError(
                f"unsupported unary operator {type(node.op).__name__} in "
                f"expression {source!r} at {location}"
            )

        if isinstance(node, ast.BinOp):
            left = self._compile_ast_node(node.left, indicator_ids, location, source)
            right = self._compile_ast_node(node.right, indicator_ids, location, source)
            if isinstance(node.op, ast.Add):

                def _add(
                    ctx: _EvalContext,
                    _l: Callable[[_EvalContext], float] = left,
                    _r: Callable[[_EvalContext], float] = right,
                ) -> float:
                    return _l(ctx) + _r(ctx)

                return _add
            if isinstance(node.op, ast.Sub):

                def _sub(
                    ctx: _EvalContext,
                    _l: Callable[[_EvalContext], float] = left,
                    _r: Callable[[_EvalContext], float] = right,
                ) -> float:
                    return _l(ctx) - _r(ctx)

                return _sub
            if isinstance(node.op, ast.Mult):

                def _mult(
                    ctx: _EvalContext,
                    _l: Callable[[_EvalContext], float] = left,
                    _r: Callable[[_EvalContext], float] = right,
                ) -> float:
                    return _l(ctx) * _r(ctx)

                return _mult
            if isinstance(node.op, ast.Div):

                def _div(ctx: _EvalContext, _l=left, _r=right) -> float:
                    rv = _r(ctx)
                    if rv == 0.0:
                        return math.nan
                    return _l(ctx) / rv

                return _div
            raise ValueError(
                f"unsupported binary operator {type(node.op).__name__} in "
                f"expression {source!r} at {location}"
            )

        if isinstance(node, ast.Call):
            if not isinstance(node.func, ast.Name):
                raise ValueError(
                    f"only bare function calls are allowed in expression {source!r} at {location}"
                )
            fn_name = node.func.id
            if fn_name not in _MATH_FUNCTIONS:
                raise ValueError(
                    f"unknown function {fn_name!r} in expression {source!r} at {location}; "
                    f"allowed: {sorted(_MATH_FUNCTIONS.keys())}"
                )
            if node.keywords:
                raise ValueError(
                    f"keyword arguments not allowed in expression {source!r} at {location}"
                )
            arg_fns = tuple(
                self._compile_ast_node(arg, indicator_ids, location, source) for arg in node.args
            )
            fn = _MATH_FUNCTIONS[fn_name]

            def _call(ctx: _EvalContext, _fn=fn, _args=arg_fns) -> float:
                return float(_fn(*(a(ctx) for a in _args)))

            return _call

        raise ValueError(
            f"unsupported AST node {type(node).__name__} in expression {source!r} at {location}"
        )

    def _compile_identifier(
        self,
        ident: str,
        indicator_ids: frozenset[str],
        location: str,
        source: str,
    ) -> Callable[[_EvalContext], float]:
        """Compile a bare identifier into a context-reader callable."""
        if ident in _PRICE_FIELD_GETTERS:
            getter = _PRICE_FIELD_GETTERS[ident]

            def _price(
                ctx: _EvalContext,
                _g: Callable[[Candle], float] = getter,
            ) -> float:
                return _g(ctx.candle)

            return _price
        if ident in indicator_ids:

            def _ind(ctx: _EvalContext, _name: str = ident) -> float:
                if _name not in ctx.indicator_values:
                    return math.nan
                return ctx.indicator_values[_name]

            return _ind
        # ``<base>_prev_<N>`` references read from the per-base ring
        # buffer allocated at the top of compile(). The base name MUST
        # have a buffer entry by now (the LookbackResolver walked the
        # same conditions we are compiling, and _allocate_lookback
        # rejected unknown bases). The lag MUST fit within the
        # buffer's capacity (by construction of MAX(N) the buffer is
        # always exactly large enough, but we still validate
        # defensively in case the helpers are called via an
        # unexpected path).
        prev_split = LookbackResolver.split_prev_suffix(ident)
        if prev_split is not None:
            base, lag = prev_split
            buffers = self._current_lookback_buffers or {}
            buffer = buffers.get(base)
            if buffer is None:
                raise IRReferenceError(
                    f"_prev_N reference {ident!r} at {location} has no allocated "
                    f"LookbackBuffer for base {base!r}; ensure compile() ran the "
                    f"LookbackResolver on this IR before compiling identifiers"
                )
            if lag > buffer.capacity:
                raise IRReferenceError(
                    f"_prev_N reference {ident!r} at {location} requires lag {lag} "
                    f"but buffer for base {base!r} was sized to {buffer.capacity}"
                )

            def _prev(_ctx: _EvalContext, _buffer: LookbackBuffer = buffer, _n: int = lag) -> float:
                return _buffer.get(_n)

            return _prev
        # Anything else is a hard error -- the resolver should have
        # caught it, but if compilation is ever invoked without the
        # resolver-based identity guarantee we still fail loudly.
        raise IRReferenceError(
            f"unresolved identifier {ident!r} in expression {source!r} at {location}; "
            f"not a price field and not a declared indicator id"
        )

    # ---------- exit compilation ----------

    def _compile_exit_logic(
        self,
        exit_logic: ExitLogic,
        indicator_ids: frozenset[str],
    ) -> dict[str, _ExitCheck]:
        """
        Compile every populated exit stop into a name -> _ExitCheck
        dict. Stops absent from the IR are not represented.
        """
        compiled: dict[str, _ExitCheck] = {}
        for attr_name in (
            "primary_exit",
            "initial_stop",
            "take_profit",
            "trailing_exit",
            "scheduled_exit",
            "equity_stop",
        ):
            stop = getattr(exit_logic, attr_name)
            if stop is None:
                continue
            evaluator = self._compile_exit_stop(stop, indicator_ids, f"exit_logic.{attr_name}")
            compiled[attr_name] = _ExitCheck(name=attr_name, evaluator=evaluator)
        return compiled

    def _compile_exit_stop(
        self,
        stop: ExitStop,
        indicator_ids: frozenset[str],
        location: str,
    ) -> ExitEvaluator:
        """Translate an :data:`ExitStop` variant into an evaluator."""
        if isinstance(stop, (MeanReversionToMidStop, ChannelExitStop)):
            long_eval = self._compile_leaf(
                stop.long_condition, indicator_ids, f"{location}.long_condition"
            )
            short_eval = self._compile_leaf(
                stop.short_condition, indicator_ids, f"{location}.short_condition"
            )

            def _two_sided(ctx: _EvalContext) -> bool:
                if ctx.position is None or ctx.position.quantity == 0:
                    return False
                if ctx.position.quantity > 0:
                    return long_eval(ctx)
                return short_eval(ctx)

            return _two_sided

        if isinstance(stop, (CalendarExitStop, ZscoreStop)):
            cond_eval = self._compile_leaf(stop.condition, indicator_ids, f"{location}.condition")

            def _single(ctx: _EvalContext) -> bool:
                return cond_eval(ctx)

            return _single

        if isinstance(stop, AtrMultipleStop):
            # ATR-multiple stops require the engine to track an
            # initial stop price set at entry and then re-check on
            # every bar. The compiled IRStrategy receives a current
            # PositionSnapshot but does not yet have the entry-bar
            # ATR snapshot. We model this as an evaluator that NEVER
            # fires from inside the strategy -- the BacktestEngine's
            # PaperBrokerAdapter is the place that compares low/high
            # against the persisted stop. Returning False here is
            # correct: the strategy emits no spurious exit; the
            # engine's stop-loss machinery handles execution.
            #
            # NOTE: this is documented strategy-vs-engine division of
            # responsibility, NOT a stub. The compiler still records
            # the check name so same_bar_priority can reference it.
            indicator_ref = stop.indicator
            if indicator_ref not in indicator_ids:
                raise IRReferenceError(
                    f"atr_multiple stop at {location} references unknown indicator "
                    f"{indicator_ref!r}; declare it in the IR's indicators block"
                )

            def _atr_stop(_ctx: _EvalContext) -> bool:
                return False

            return _atr_stop

        if isinstance(stop, RiskRewardMultipleStop):
            # R-multiple take-profit -- engine responsibility, same
            # rationale as AtrMultipleStop above.
            def _rr_stop(_ctx: _EvalContext) -> bool:
                return False

            return _rr_stop

        if isinstance(stop, OppositeInnerBandTouchStop):
            # Engine-side: needs the entry-bar inner-band snapshot.
            def _opposite_band(_ctx: _EvalContext) -> bool:
                return False

            return _opposite_band

        if isinstance(stop, MiddleBandCloseViolationStop):
            # Engine-side: needs the entry-side mid-band snapshot.
            def _middle_band(_ctx: _EvalContext) -> bool:
                return False

            return _middle_band

        # The remaining ExitStop variants (basket-level stops) are out
        # of scope for M1.A3 (basket execution is M3.X2.5). Fail loudly
        # rather than silently accept them.
        raise ValueError(
            f"unsupported ExitStop variant {type(stop).__name__} at {location}; "
            f"basket-level stops ship with the basket execution tranche"
        )

    def _freeze_exit_priority(
        self,
        compiled_exits: dict[str, _ExitCheck],
        exit_logic: ExitLogic,
    ) -> tuple[_ExitCheck, ...]:
        """
        Freeze the compiled exit checks into a tuple ordered per
        ``exit_logic.same_bar_priority``.

        Names appearing in the priority list but not in
        ``compiled_exits`` raise :class:`IRReferenceError` (the
        priority list is part of the IR; if it points at a stop that
        is not configured, that's an authoring bug).

        Compiled exits NOT mentioned in the priority list are
        appended after the prioritised ones in alphabetical order so
        the compile result is fully deterministic.
        """
        ordered: list[_ExitCheck] = []
        seen: set[str] = set()
        for name in exit_logic.same_bar_priority:
            if name not in compiled_exits:
                raise IRReferenceError(
                    f"same_bar_priority lists {name!r} but no exit stop with that "
                    f"name is configured; configured stops: {sorted(compiled_exits)}"
                )
            if name in seen:
                # Duplicate priority entries: skip the second occurrence
                # so the tuple stays a stable ordered set.
                continue
            ordered.append(compiled_exits[name])
            seen.add(name)
        # Append any not-yet-included compiled exits in alphabetical
        # order for determinism.
        for name in sorted(compiled_exits.keys()):
            if name in seen:
                continue
            ordered.append(compiled_exits[name])
            seen.add(name)
        return tuple(ordered)


__all__ = [
    "IRStrategy",
    "StrategyIRCompiler",
]
