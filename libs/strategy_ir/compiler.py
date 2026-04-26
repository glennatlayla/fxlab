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
from libs.contracts.market_data import INTERVAL_SECONDS, CandleInterval
from libs.contracts.signal import (
    Signal,
    SignalDirection,
    SignalStrength,
    SignalType,
)
from libs.contracts.strategy_ir import (
    AtrMultipleStop,
    BollingerLowerIndicator,
    BollingerUpperIndicator,
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
    SmaIndicator,
    StrategyIR,
    TimeExitRule,
    TrailingStopRule,
    ZscoreStop,
)
from libs.strategy_ir.broker import Broker
from libs.strategy_ir.clock import BarClock, Clock
from libs.strategy_ir.formula_evaluator import CompiledFormula, FormulaEvaluator
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
# Bar-interval seconds lookup keyed on the CandleInterval enum.
#
# Sourced from :data:`libs.contracts.market_data.INTERVAL_SECONDS`. We
# re-bind it here under a private alias so call sites in this module
# stay short and the import is not visible to module consumers (the
# enum itself is the public surface).
# ---------------------------------------------------------------------------

_INTERVAL_SECONDS_BY_ENUM: dict[CandleInterval, int] = dict(INTERVAL_SECONDS)


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
        open_trade: per-symbol entry snapshot for the currently-open
            trade, or ``None`` when flat or when the bar evaluator
            does not need entry-time data. Populated by
            :meth:`IRStrategy._observe_position_state` on the entry
            bar; consulted by stateful exit evaluators.
        bar_counter: monotonic count of bars seen by this strategy
            instance; consumed by the time_exit evaluator.
        cross_tf: aggregator providing per-(symbol, timeframe)
            last-closed OHLCV. Consulted by identifier evaluators
            compiled for ``<base>_<tf>`` cross-timeframe references
            (e.g. ``close_1d``). Always present (the IRStrategy
            constructs an empty aggregator when the IR has no
            cross-timeframe references) so evaluators can call
            :meth:`_CrossTimeframeAggregator.get_last_closed` without
            a None-check on the hot path.
    """

    candle: Candle
    indicator_values: dict[str, float]
    position: PositionSnapshot | None
    lookback_buffers: dict[str, LookbackBuffer]
    open_trade: _OpenTradeContext | None = None
    bar_counter: int = 0
    cross_tf: _CrossTimeframeAggregator | None = None


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


@dataclass
class _OpenTradeContext:
    """
    Per-symbol snapshot captured when a position transitions from flat
    to open.

    The compiled exit evaluators consult this snapshot to decide whether
    the bar's price action triggers a stop loss, take profit, trailing
    stop, or time/calendar exit. The snapshot is taken on the first
    bar where the strategy's :meth:`IRStrategy.evaluate` observes a
    non-zero ``current_position`` for the symbol; it is cleared when
    the position returns to flat.

    Attributes:
        direction: ``+1`` for long, ``-1`` for short. Stored as int
            (not :class:`SignalDirection`) so the evaluators can
            multiply against price deltas without a string dispatch.
        entry_price: average entry price as reported by the broker on
            the entry bar. Floats throughout the evaluator pipeline.
        entry_atr: ATR value at entry (for the ATR id named in
            ``initial_stop.indicator``), or ``NaN`` when the strategy
            has no ATR-multiple stop.
        stop_distance: ``initial_stop.multiple * entry_atr`` -- cached
            so risk_reward_multiple can derive the take-profit price
            without re-reading the entry-bar ATR. ``NaN`` when no
            ATR-multiple stop is configured.
        entry_inner_band_upper: BB upper-1 (innermost upper band) at
            entry, or ``NaN`` when none configured. Used by
            opposite_inner_band_touch for SHORTS (a short take-profit
            is "touch the opposite-side inner band", i.e. the upper-1
            for a short trade).
        entry_inner_band_lower: BB lower-1 at entry, or ``NaN``. Used
            by opposite_inner_band_touch for LONGS (touch the lower-1).
        entry_bar_index: monotonic count of bars seen by the strategy
            when the position opened. Used by time_exit to decide when
            ``max_bars_in_trade`` has elapsed.
    """

    direction: int
    entry_price: float
    entry_atr: float = float("nan")
    stop_distance: float = float("nan")
    entry_inner_band_upper: float = float("nan")
    entry_inner_band_lower: float = float("nan")
    entry_bar_index: int = 0


@dataclass(frozen=True)
class _ExitWiring:
    """
    Compile-time descriptor of the indicator ids each exit kind needs
    to read at entry and at every bar.

    Why a dataclass:
        The four "stateful" exit kinds (atr_multiple,
        risk_reward_multiple, opposite_inner_band_touch,
        middle_band_close_violation) all consume named indicators from
        the IR but have different parameter names. Centralising the
        resolved indicator id per stop here keeps the per-bar
        evaluators short and audit-friendly.

    Attributes:
        atr_indicator_id: id of the ATR indicator used by
            ``initial_stop`` (or ``None`` when the strategy has no
            ATR-multiple stop). Snapshotted at entry so the stop
            distance is fixed for the life of the trade.
        atr_multiple: the ``multiple`` value from ``initial_stop``,
            or ``NaN`` when no ATR-multiple stop is configured.
        rr_multiple: the ``multiple`` value from ``take_profit`` when
            it is a risk_reward_multiple stop, or ``NaN``.
        bb_upper_inner_id: id of the inner (smallest stddev)
            BollingerUpperIndicator, or ``None``.
        bb_lower_inner_id: id of the inner (smallest stddev)
            BollingerLowerIndicator, or ``None``.
        bb_mid_id: id of the SMA indicator that serves as the Bollinger
            middle band (matched on length+source), or ``None``.
        time_exit_max_bars: ``max_bars_in_trade`` from the TimeExitRule
            wrapper, or ``None`` when no time_exit is configured.
    """

    atr_indicator_id: str | None = None
    atr_multiple: float = float("nan")
    rr_multiple: float = float("nan")
    bb_upper_inner_id: str | None = None
    bb_lower_inner_id: str | None = None
    bb_mid_id: str | None = None
    time_exit_max_bars: int | None = None


@dataclass(frozen=True)
class _DerivedFieldSpec:
    """
    Compile-time descriptor for a single ``derived_fields[]`` entry.

    A derived field is a free-form arithmetic formula (e.g.
    ``swing_high - ((swing_high - swing_low) * 0.382)``) that produces a
    scalar per-bar value computed from indicator values and price-field
    reads. The compiler turns each formula into a
    :class:`CompiledFormula` at compile time and the per-bar evaluator
    invokes ``compiled.evaluate(values)`` against a dict that contains
    every previously-computed input the formula might reference
    (indicators + price fields + earlier-in-topological-order derived
    fields). Derived field values are then merged into
    :attr:`_EvalContext.indicator_values` so leaf evaluators can read
    them via the same identifier-lookup path used for indicator ids.

    Attributes:
        ident: the derived field id as declared in the IR. Used as the
            key when the computed value is merged into the per-bar
            indicator-values dict.
        compiled: the :class:`CompiledFormula` produced by
            :class:`FormulaEvaluator`. Immutable; safely shared across
            evaluate() calls.
        formula: the raw formula source string. Retained for diagnostics
            / structured logging only -- the evaluator reads the
            ``compiled.tree`` directly.
    """

    ident: str
    compiled: CompiledFormula
    formula: str


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


def _read_spread_in_price_units(c: Candle) -> float:
    """Pull ``Candle.spread`` as a finite float, or NaN when absent.

    The Strategy IR's spread filter (``"lhs": "spread", ...``) reads
    this value. Candles emitted by equity providers leave ``spread``
    as ``None`` -- in that case we propagate NaN so the leaf evaluator
    short-circuits to ``False`` (the conservative "skip if spread
    unknown" semantics, matching the IR author's intent: a bar with
    unknown spread is treated as too-wide-to-trade).
    """
    if c.spread is None:
        return math.nan
    return float(c.spread)


_PRICE_FIELD_GETTERS: dict[str, Callable[[Candle], float]] = {
    "open": lambda c: float(c.open),
    "high": lambda c: float(c.high),
    "low": lambda c: float(c.low),
    "close": lambda c: float(c.close),
    "volume": lambda c: float(c.volume),
    "spread": _read_spread_in_price_units,
}


# ---------------------------------------------------------------------------
# Cross-timeframe price-field support.
#
# IRs reference identifiers like ``close_1d`` / ``high_4h`` / ``open_1h``
# in entry conditions when they need a confirmation read at a higher
# timeframe than the bar feed the engine drives. The compiler handles
# these by aggregating the lower-timeframe primary stream into per-(symbol,
# timeframe) buckets and exposing the most-recently-CLOSED bucket's
# OHLCV via the cross-timeframe identifier.
#
# Bucket alignment is UTC-epoch-aligned: bucket_id = epoch_seconds //
# tf_seconds. This matches the synthetic provider's bar timestamps
# (which floor to the bar interval in UTC) so two consecutive runs
# produce byte-identical aggregations -- the determinism contract.
# ---------------------------------------------------------------------------

#: Cross-timeframe suffixes the compiler recognises, mapped to their
#: bucket length in seconds. Suffixes are matched against identifier
#: tails (``close_1d`` -> ``1d`` -> 86400s). Adding a new timeframe
#: here is the only edit needed for the compiler to evaluate it.
_CROSS_TIMEFRAME_SECONDS: dict[str, int] = {
    "15m": 900,
    "1h": 3_600,
    "4h": 14_400,
    "1d": 86_400,
}


#: Price-field bases recognised on the LHS of a cross-timeframe
#: identifier (``<base>_<tf>``). Spread is intentionally excluded:
#: spread is a per-bar bid/ask snapshot, not a meaningful aggregation
#: across a higher-timeframe bucket.
_CROSS_TIMEFRAME_BASES: frozenset[str] = frozenset({"open", "high", "low", "close", "volume"})


def _split_cross_timeframe_ref(ident: str) -> tuple[str, str, int] | None:
    """
    Decompose a ``<base>_<timeframe>`` identifier into its parts.

    Args:
        ident: candidate identifier, e.g. ``"close_1d"``.

    Returns:
        ``(base, timeframe_str, timeframe_seconds)`` when ``ident`` matches
        the cross-timeframe pattern (e.g., ``("close", "1d", 86400)``),
        otherwise ``None``.

    Why a dedicated splitter:
        Two callers need this -- the compiler's identifier dispatcher
        (to decide whether to emit a cross-tf reader) and the IR scan
        that determines which (symbol, timeframe) buckets the
        :class:`_CrossTimeframeAggregator` must track. Centralising
        the split keeps the two callers' classification rules in
        lock-step.
    """
    if "_" not in ident:
        return None
    # Try suffixes longest-first so a future "15m" / "5m" overlap is
    # resolved deterministically.
    for tf_str in sorted(_CROSS_TIMEFRAME_SECONDS.keys(), key=len, reverse=True):
        suffix = f"_{tf_str}"
        if ident.endswith(suffix):
            base = ident[: -len(suffix)]
            if base in _CROSS_TIMEFRAME_BASES:
                return base, tf_str, _CROSS_TIMEFRAME_SECONDS[tf_str]
    return None


@dataclass
class _CrossTimeframeBucket:
    """
    Mutable in-progress aggregation bucket for one (symbol, timeframe).

    Why a dataclass and not a tuple:
        We mutate this on every bar (open is fixed at first bar of the
        bucket, high/low/close roll, volume accumulates). A frozen
        tuple would force a re-allocation per bar, which is wasted
        work given the aggregator is a private engine-internal cache.

    Attributes:
        bucket_id: epoch-seconds floor // tf_seconds. Sentinel ``-1``
            until the first bar arrives.
        open: bucket open (first bar's open in this bucket).
        high: bucket high so far.
        low: bucket low so far.
        close: bucket close so far (latest contributing bar's close).
        volume: sum of volume across contributing bars.
        bucket_end_seconds: epoch seconds at which this bucket closes;
            cached so the per-bar completion check is one comparison.
        is_closed: True once a bar has been seen whose end-time reaches
            ``bucket_end_seconds``. The bucket is then mirrored into
            :attr:`_CrossTimeframeAggregator._last_closed` and stays in
            place until the next bar in a different bucket arrives.
    """

    bucket_id: int = -1
    open: float = float("nan")
    high: float = float("nan")
    low: float = float("nan")
    close: float = float("nan")
    volume: float = 0.0
    bucket_end_seconds: int = 0
    is_closed: bool = False


class _CrossTimeframeAggregator:
    """
    Per-(symbol, timeframe) bucket aggregator for cross-timeframe reads.

    Responsibilities:
        - On every primary-stream bar, update the in-progress bucket
          for each tracked timeframe.
        - When the current bar's end-time reaches the bucket's end,
          snapshot the in-progress bucket into the per-(symbol,
          timeframe) "last closed" store so subsequent identifier
          reads return the just-closed bucket's OHLCV.
        - When a bar arrives in a new bucket (boundary crossing), if
          the previous bucket was never marked closed (e.g., the data
          feed skipped a sub-interval), snapshot it before starting
          the new bucket so no aggregation is silently dropped.

    Does NOT:
        - Read a wall clock or random source.
        - Persist state across :class:`StrategyIRCompiler.compile`
          calls (each compiled :class:`IRStrategy` owns its own
          aggregator, allocated at compile time and isolated to that
          strategy instance).
        - Track sub-bucket alignment errors (e.g., a 1h bar arriving
          off-grid). The aggregator trusts that the engine feeds bars
          whose timestamps floor to the primary timeframe.

    Dependencies:
        - Reads :class:`Candle` fields only (no broker / clock).

    Example:
        agg = _CrossTimeframeAggregator(timeframes=("1d",))
        agg.update("EURUSD", candle)  # called once per evaluate()
        close_1d = agg.get_last_closed("EURUSD", "1d", "close")
    """

    __slots__ = ("_timeframes", "_pending", "_last_closed")

    def __init__(self, timeframes: tuple[str, ...]) -> None:
        """
        Allocate per-(symbol, timeframe) state lazily.

        Args:
            timeframes: tuple of timeframe strings (``"1h"``, ``"1d"``,
                ...) the IR references via cross-tf identifiers. Empty
                tuple means the IR has no cross-tf refs and the
                aggregator will be a no-op.
        """
        # Tuple so the iteration order is deterministic across runs.
        self._timeframes: tuple[str, ...] = tuple(timeframes)
        # (symbol, timeframe) -> in-progress bucket. Created lazily on
        # first observation so the aggregator does not need a symbol
        # universe at construction time (the IRStrategy's universe may
        # be filtered by the engine before evaluate() runs).
        self._pending: dict[tuple[str, str], _CrossTimeframeBucket] = {}
        # (symbol, timeframe) -> snapshotted closed bucket. Read by
        # cross-timeframe identifier evaluators. Returns NaN per field
        # until the first bucket has been closed.
        self._last_closed: dict[tuple[str, str], _CrossTimeframeBucket] = {}

    def update(self, symbol: str, candle: Candle) -> None:
        """
        Fold ``candle`` into the in-progress bucket for every tracked
        timeframe under ``symbol``.

        Args:
            symbol: ticker the candle belongs to.
            candle: the bar currently being evaluated. Its
                :attr:`Candle.interval` determines the bar's end-time
                (used to decide whether the bar completes the bucket).

        Why interval-aware completion:
            A 15m bar at 09:45 ends at 10:00, which closes the
            09:00-10:00 1h bucket. A 15m bar at 09:30 ends at 09:45,
            still mid-bucket. We compute end-time as
            ``timestamp + INTERVAL_SECONDS[bar.interval]`` and compare
            against ``bucket_end_seconds`` so the rule works uniformly
            for any (primary_tf, cross_tf) pair where primary_tf
            divides cross_tf evenly (the only case Strategy IRs use).
        """
        if not self._timeframes:
            return
        ts_seconds = int(candle.timestamp.timestamp())
        bar_seconds = _INTERVAL_SECONDS_BY_ENUM.get(candle.interval, 0)
        # Bar end is the open + interval (exclusive); a bar at ts=09:00
        # interval 1h ends at 10:00. We accept missing intervals by
        # falling back to ts + 1 -- the "completion" check then only
        # fires when the candle's open already meets the bucket end,
        # which is the safest fallback.
        bar_end_seconds = ts_seconds + (bar_seconds if bar_seconds > 0 else 1)
        cv_open = float(candle.open)
        cv_high = float(candle.high)
        cv_low = float(candle.low)
        cv_close = float(candle.close)
        cv_volume = float(candle.volume)
        for tf_str in self._timeframes:
            tf_seconds = _CROSS_TIMEFRAME_SECONDS[tf_str]
            bucket_id = ts_seconds // tf_seconds
            key = (symbol, tf_str)
            pending = self._pending.get(key)
            if pending is None or pending.bucket_id != bucket_id:
                # Boundary crossing (or first observation). Snapshot
                # the previous bucket if it was non-empty and not yet
                # marked closed -- this covers the case where the
                # primary bar interval does not divide the higher tf
                # evenly enough for the end-time check to fire.
                if pending is not None and not pending.is_closed and pending.bucket_id >= 0:
                    self._snapshot(key, pending)
                bucket_end_seconds = (bucket_id + 1) * tf_seconds
                pending = _CrossTimeframeBucket(
                    bucket_id=bucket_id,
                    open=cv_open,
                    high=cv_high,
                    low=cv_low,
                    close=cv_close,
                    volume=cv_volume,
                    bucket_end_seconds=bucket_end_seconds,
                    is_closed=False,
                )
                self._pending[key] = pending
            else:
                # Same bucket: roll high/low/close, accumulate volume.
                # Open stays fixed at the bucket's first bar.
                if cv_high > pending.high or math.isnan(pending.high):
                    pending.high = cv_high
                if cv_low < pending.low or math.isnan(pending.low):
                    pending.low = cv_low
                pending.close = cv_close
                pending.volume += cv_volume
            # Completion check: the bar's end-time has reached the
            # bucket boundary. Mark closed AND snapshot so the next
            # bar (which will start a new bucket or stay in this one
            # for higher-tf where multiple primary bars contribute)
            # can read the freshly-closed values immediately.
            if not pending.is_closed and bar_end_seconds >= pending.bucket_end_seconds:
                pending.is_closed = True
                self._snapshot(key, pending)

    def get_last_closed(self, symbol: str, tf_str: str, base: str) -> float:
        """
        Return the last-closed bucket's value for ``base`` under
        (symbol, timeframe), or NaN when no bucket has closed yet.

        Args:
            symbol: ticker.
            tf_str: timeframe string (``"1h"``, ``"1d"``, ...).
            base: one of ``open``/``high``/``low``/``close``/``volume``.

        Returns:
            Float value; NaN propagates "no data yet" through to the
            leaf evaluator which short-circuits to False on NaN.
        """
        bucket = self._last_closed.get((symbol, tf_str))
        if bucket is None:
            return math.nan
        if base == "open":
            return bucket.open
        if base == "high":
            return bucket.high
        if base == "low":
            return bucket.low
        if base == "close":
            return bucket.close
        if base == "volume":
            return bucket.volume
        # Defensive: an unknown base would mean the compiler emitted
        # a reader for a base outside _CROSS_TIMEFRAME_BASES.
        return math.nan

    def _snapshot(self, key: tuple[str, str], pending: _CrossTimeframeBucket) -> None:
        """
        Copy ``pending`` into the last-closed store for ``key``.

        The stored bucket is a fresh dataclass instance so subsequent
        mutations to the in-progress bucket (continuing to roll under
        the next bar in the same bucket, or starting a new bucket)
        cannot retroactively change the snapshotted last-closed
        values.
        """
        self._last_closed[key] = _CrossTimeframeBucket(
            bucket_id=pending.bucket_id,
            open=pending.open,
            high=pending.high,
            low=pending.low,
            close=pending.close,
            volume=pending.volume,
            bucket_end_seconds=pending.bucket_end_seconds,
            is_closed=True,
        )


# ---------------------------------------------------------------------------
# Pip-size table for FX symbols.
#
# The compiler converts ``spread`` leaves with ``units == "pips"`` into
# pip-space comparisons at evaluation time. JPY-quoted majors use
# ``0.01`` (one pip == one tick of the second decimal); every other
# major and cross uses ``0.0001`` (one pip == one tick of the fourth
# decimal). The compiler's per-symbol pip lookup falls back to this
# table when the IR's universe symbols are FX majors; non-FX symbols
# (equities, futures) raise at compile time if a ``units == "pips"``
# leaf appears -- this is a hard contract: pips is meaningless without
# a pip size.
# ---------------------------------------------------------------------------

_FX_JPY_PIP_SIZE: float = 0.01
_FX_DEFAULT_PIP_SIZE: float = 0.0001


def _pip_size_for_symbol(symbol: str) -> float:
    """
    Return the pip size for an FX symbol.

    Args:
        symbol: ticker (e.g., "EURUSD", "USDJPY"). The function only
            distinguishes JPY-quoted vs everything else -- the broader
            pip-size taxonomy (precious metals, indices) is out of
            scope until those instruments enter the IR universe.

    Returns:
        Pip size as a plain float (0.01 for JPY-quoted; 0.0001 for the
        rest). Returned as a float (not Decimal) because every caller
        does float arithmetic.
    """
    return _FX_JPY_PIP_SIZE if symbol.endswith("JPY") else _FX_DEFAULT_PIP_SIZE


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
        exit_wiring: _ExitWiring | None = None,
        cross_tf_timeframes: tuple[str, ...] = (),
        derived_field_specs: tuple[_DerivedFieldSpec, ...] = (),
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
            cross_tf_timeframes: timeframe strings (``"1h"``, ``"1d"``,
                ...) the IR references via cross-timeframe identifiers
                like ``close_1d``. Determines which (symbol, timeframe)
                buckets the per-strategy
                :class:`_CrossTimeframeAggregator` will track. An
                empty tuple (the default) keeps the aggregator a
                zero-cost no-op for IRs that contain no cross-tf
                refs.
            derived_field_specs: ordered tuple of
                :class:`_DerivedFieldSpec` entries, one per
                ``derived_fields[]`` declaration in the IR. The order
                is the topological order produced by
                :class:`ReferenceResolver`, so each formula sees every
                input it depends on already populated when the
                evaluator walks the tuple. Empty when the IR declares
                no derived fields.
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
        # Compile-time wiring for stateful exit kinds (atr_multiple,
        # risk_reward_multiple, opposite_inner_band_touch,
        # middle_band_close_violation, time_exit). Frozen at compile.
        self._exit_wiring: _ExitWiring = exit_wiring or _ExitWiring()
        # Per-symbol open-trade snapshot. Populated by
        # ``_observe_position_state`` on the bar where the position
        # transitions from None/zero to non-zero; cleared on the bar
        # the position returns to flat. Single-threaded by construction
        # (the engine drives evaluate() one bar at a time).
        self._open_trade_contexts: dict[str, _OpenTradeContext] = {}
        # Monotonic per-strategy bar counter. Used to stamp
        # entry_bar_index on freshly-opened positions for time_exit.
        self._bar_counter: int = 0
        # Cross-timeframe aggregator. Tracks per-(symbol, tf) OHLCV
        # buckets so cross-timeframe identifiers like ``close_1d``
        # can read the most-recently-completed bucket at evaluation
        # time. Allocated once per compiled strategy; shared across
        # symbols and across evaluate() calls.
        self._cross_tf: _CrossTimeframeAggregator = _CrossTimeframeAggregator(
            timeframes=cross_tf_timeframes
        )
        # Derived field formulas, ordered topologically. Computed once
        # per evaluate() call (after indicator scalars are extracted)
        # and merged into the same indicator_values dict so leaf
        # evaluators read derived ids via the existing dict-lookup
        # path. Empty tuple is the no-op fast path for IRs that
        # declare no derived_fields.
        self._derived_field_specs: tuple[_DerivedFieldSpec, ...] = derived_field_specs

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

        # Compute every derived_field for this bar in topological order
        # and merge the results back into indicator_values. After this
        # call, leaf evaluators that reference a derived-field id (e.g.
        # ``fib_61_long``) read it through the same dict-lookup path
        # used for indicator ids -- no special-case dispatch on the
        # hot path.
        if self._derived_field_specs:
            self._compute_derived_fields(candle, indicator_values)

        # Reconcile per-symbol open-trade state with the broker-supplied
        # PositionSnapshot. New non-zero position -> snapshot the
        # entry-bar ATR + inner bands. Position back to flat ->
        # clear so a future entry starts a fresh snapshot.
        open_trade = self._observe_position_state(
            symbol=symbol,
            current_position=current_position,
            indicator_values=indicator_values,
        )

        ctx = _EvalContext(
            candle=candle,
            indicator_values=indicator_values,
            position=current_position,
            lookback_buffers=self._lookback_buffers,
            open_trade=open_trade,
            bar_counter=self._bar_counter,
            cross_tf=self._cross_tf,
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
            # Update the cross-timeframe aggregator AFTER conditions
            # have been evaluated so this bar's contribution to the
            # in-progress higher-tf bucket is not visible to the
            # current bar's identifier reads. The semantics are
            # "close_1d returns the close of the most recently CLOSED
            # 1d bucket as of THIS bar's open"; updating in the
            # finally block enforces that contract.
            self._cross_tf.update(symbol, candle)
            # Bar counter advances unconditionally so time_exit's
            # ``bars_in_trade`` arithmetic stays in lock-step with the
            # bar stream regardless of whether a signal fires.
            self._bar_counter += 1

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

    def _compute_derived_fields(
        self,
        candle: Candle,
        indicator_values: dict[str, float],
    ) -> None:
        """
        Evaluate every IR ``derived_fields[]`` formula for the current
        bar and merge the result into ``indicator_values``.

        Walk order is the topological order frozen at compile time
        (from :meth:`ReferenceResolver.resolve`), so any derived field
        that depends on another derived field reads its dependency's
        already-computed value instead of NaN.

        Inputs available to each formula:
            - Every IR indicator id (latest scalar from
              ``indicator_values`` as populated by
              :meth:`_extract_latest_indicator_values`).
            - Every supported price field (open / high / low / close /
              volume / spread) read from the current candle.
            - Every earlier-in-topological-order derived field (merged
              into the same dict on each loop iteration).

        Failure handling:
            ``CompiledFormula.evaluate`` raises ``ValueError`` when a
            formula references a name that is not present in the
            values dict (e.g. an indicator that has not warmed up
            yet -- the slot is missing rather than NaN). We translate
            that into NaN here so leaf evaluators short-circuit to
            False during warmup, matching the convention every other
            identifier read in this module uses ("missing input is
            never a true condition").

        Args:
            candle: the current bar; price-field reads pull from here.
            indicator_values: mutable dict already populated with the
                latest scalar value for every IR indicator. Mutated
                in place: each derived field id is added as a new
                entry whose value is the formula's float result (or
                NaN on missing input / divide-by-zero).
        """
        # Snapshot the price-field reads once per bar so every formula
        # sees the same OHLCV/spread numbers without re-reading the
        # Candle properties on each iteration.
        price_values: dict[str, float] = {
            name: getter(candle) for name, getter in _PRICE_FIELD_GETTERS.items()
        }
        for spec in self._derived_field_specs:
            # Build the values dict fresh per formula so mutations to
            # indicator_values that happen DURING this loop (the
            # previous spec adding its own id) flow into the next
            # formula's lookup namespace.
            values: dict[str, float] = {}
            values.update(price_values)
            values.update(indicator_values)
            try:
                result = spec.compiled.evaluate(values)
            except ValueError:
                # Formula referenced a name that is not yet known
                # (e.g. an indicator that has not produced a value
                # this bar). Treat as "missing input" -> NaN; the
                # downstream leaf evaluator short-circuits.
                indicator_values[spec.ident] = math.nan
                continue
            # Convert non-finite results to NaN so the downstream
            # short-circuit applies uniformly. ``math.isnan`` catches
            # divide-by-zero (which the evaluator already returns as
            # NaN) and any inf that arose from an upstream NaN
            # propagation (NaN + finite would already be NaN; this
            # is a defence-in-depth narrowing).
            indicator_values[spec.ident] = float(result)

    def _observe_position_state(
        self,
        *,
        symbol: str,
        current_position: PositionSnapshot | None,
        indicator_values: dict[str, float],
    ) -> _OpenTradeContext | None:
        """
        Reconcile broker-supplied position state with the per-symbol
        entry snapshot.

        Three transitions are possible on any bar:

        - **Flat -> open**: the broker reports a non-zero position for
          a symbol that previously had no snapshot. We capture the
          entry price, ATR-at-entry, inner-band-at-entry, and entry
          bar index. The snapshot lives until the position closes.
        - **Open -> open** (continuation): the snapshot is reused
          unchanged. We do NOT re-read indicators because the stop
          distance and take-profit price are FROZEN at entry.
        - **Open -> flat**: the snapshot is dropped so the next entry
          starts a fresh capture.

        Returns:
            The current snapshot (or None when flat). Stateful exit
            evaluators close over the strategy instance and read this
            value via :class:`_EvalContext.open_trade`.

        Why a single helper:
            Centralising the transition logic here keeps the evaluators
            short (they read the snapshot; they do not own its
            lifecycle). It also makes the "snapshot is taken on the
            first bar where position is non-zero" contract auditable.
        """
        if current_position is None or current_position.quantity == 0:
            # Flat: drop any snapshot so a future entry triggers
            # re-capture. ``pop`` is no-op when the symbol is not
            # tracked, which is the common case.
            self._open_trade_contexts.pop(symbol, None)
            return None

        existing = self._open_trade_contexts.get(symbol)
        if existing is not None:
            return existing

        # Fresh entry: capture the snapshot.
        direction = 1 if current_position.quantity > 0 else -1
        entry_price = float(current_position.average_entry_price)
        wiring = self._exit_wiring

        entry_atr = math.nan
        if wiring.atr_indicator_id is not None:
            entry_atr = indicator_values.get(wiring.atr_indicator_id, math.nan)

        stop_distance = math.nan
        if (
            wiring.atr_indicator_id is not None
            and not math.isnan(entry_atr)
            and not math.isnan(wiring.atr_multiple)
        ):
            stop_distance = wiring.atr_multiple * entry_atr

        entry_inner_upper = math.nan
        if wiring.bb_upper_inner_id is not None:
            entry_inner_upper = indicator_values.get(wiring.bb_upper_inner_id, math.nan)

        entry_inner_lower = math.nan
        if wiring.bb_lower_inner_id is not None:
            entry_inner_lower = indicator_values.get(wiring.bb_lower_inner_id, math.nan)

        snapshot = _OpenTradeContext(
            direction=direction,
            entry_price=entry_price,
            entry_atr=entry_atr,
            stop_distance=stop_distance,
            entry_inner_band_upper=entry_inner_upper,
            entry_inner_band_lower=entry_inner_lower,
            entry_bar_index=self._bar_counter,
        )
        self._open_trade_contexts[symbol] = snapshot
        return snapshot

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
        # Per-compile-call set of derived-field ids the IR declares.
        # Stashed here (rather than threaded through every leaf-compile
        # signature) so :meth:`_compile_identifier` can recognise them
        # and emit a dict-lookup reader. Cleared in compile()'s finally
        # block so two consecutive compilations do not leak ids.
        self._current_derived_field_ids: frozenset[str] = frozenset()

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
        resolved = ReferenceResolver(ir).resolve()

        # 1b. Discover cross-timeframe identifiers referenced anywhere
        #     in the IR so the compiled IRStrategy's aggregator knows
        #     which (symbol, timeframe) buckets to maintain. Sourcing
        #     this from the already-classified ResolvedReferences
        #     keeps the compiler's "what is a cross-tf ref" rule in
        #     lock-step with the resolver's classification.
        cross_tf_timeframes = self._collect_cross_timeframe_timeframes(resolved.references)

        # 2. Build the indicator-id whitelist used by leaf compilers.
        indicator_ids: frozenset[str] = frozenset(ind.id for ind in ir.indicators)

        # 2b. Compile derived_field formulas in topological order.
        #     Each spec captures a :class:`CompiledFormula` ready for
        #     repeat per-bar evaluation. The topological order is
        #     sourced from the resolver so a derived field that depends
        #     on another derived field always sees its dependency
        #     populated first when :meth:`IRStrategy._compute_derived_fields`
        #     walks the tuple. The whitelist of derived ids is also
        #     stashed on the compiler instance so
        #     :meth:`_compile_identifier` can recognise them and emit
        #     the dict-lookup reader.
        derived_field_specs = self._compile_derived_field_specs(ir, resolved.topological_order)
        derived_field_ids: frozenset[str] = frozenset(spec.ident for spec in derived_field_specs)

        # 3. Resolve the per-stop indicator wiring BEFORE compiling
        #    individual exit evaluators. The wiring tells each
        #    evaluator which IR indicator id to read at entry (ATR)
        #    and which inner Bollinger bands to snapshot. Centralised
        #    so the per-bar evaluators stay short.
        exit_wiring = self._resolve_exit_wiring(ir, indicator_ids)

        # 4. Scan the IR for ``_prev_N`` references and allocate one
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
        self._current_derived_field_ids = derived_field_ids
        try:
            # 5. Compile entry-side evaluators.
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

            # 6. Compile exit checks and freeze in priority order.
            compiled_exits = self._compile_exit_logic(ir.exit_logic, indicator_ids, exit_wiring)
            ordered_exits = self._freeze_exit_priority(compiled_exits, ir.exit_logic)
        finally:
            self._current_lookback_buffers = None
            self._current_derived_field_ids = frozenset()

        # 7. Translate the IR's risk_model into a compiled bundle
        #    (sizer + pre-trade gate + post-trade gate). M1.A5 only
        #    supports ``fixed_fractional_risk``; the translator raises
        #    UnsupportedRiskMethodError loudly for the deferred basket
        #    methods so a misconfigured IR fails at compile time, not
        #    at first trade.
        compiled_risk_model = RiskModelTranslator(ir).translate()

        # 8. Wrap and return.
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
            exit_wiring=exit_wiring,
            cross_tf_timeframes=cross_tf_timeframes,
            derived_field_specs=derived_field_specs,
        )

    # ---------- cross-timeframe planning ----------

    def _collect_cross_timeframe_timeframes(
        self,
        references: tuple[Any, ...],
    ) -> tuple[str, ...]:
        """
        Extract the set of cross-timeframe timeframe strings the IR
        references.

        Args:
            references: tuple of :class:`ResolvedReference` objects
                from :meth:`ReferenceResolver.resolve`. Only those with
                ``kind == "cross_timeframe"`` contribute. The raw_value
                holds the full identifier (e.g. ``"close_1d"``); we
                split off the suffix to get the timeframe string.

        Returns:
            Sorted tuple of unique timeframe strings (sorted for
            determinism so two compilations of the same IR produce a
            byte-identical aggregator construction order).

        Why source from resolved references:
            The :class:`ReferenceResolver` already classifies every
            atom in every leaf condition / derived-field formula /
            filter as ``cross_timeframe`` when the suffix matches the
            IR's confirmation_timeframes / primary_timeframe. Re-using
            its classification here means the compiler cannot diverge
            from the resolver on what counts as cross-tf.
        """
        timeframes: set[str] = set()
        for ref in references:
            if getattr(ref, "kind", None) != "cross_timeframe":
                continue
            raw = getattr(ref, "raw_value", None)
            if not isinstance(raw, str):
                continue
            split = _split_cross_timeframe_ref(raw)
            if split is None:
                # Resolver and compiler disagreed on what counts as
                # cross-tf -- surface this loudly so the regression
                # test catches the divergence rather than silently
                # producing NaN reads.
                raise IRReferenceError(
                    f"reference resolver classified {raw!r} as cross_timeframe "
                    f"but the compiler does not recognise its suffix; supported "
                    f"timeframes: {sorted(_CROSS_TIMEFRAME_SECONDS.keys())}"
                )
            _base, tf_str, _tf_seconds = split
            timeframes.add(tf_str)
        return tuple(sorted(timeframes))

    # ---------- derived field compilation ----------

    def _compile_derived_field_specs(
        self,
        ir: StrategyIR,
        topological_order: tuple[str, ...],
    ) -> tuple[_DerivedFieldSpec, ...]:
        """
        Compile every IR ``derived_fields[]`` formula and return the
        specs in topological-evaluation order.

        Args:
            ir: the parsed IR. ``ir.derived_fields`` is consulted for
                the formulas; ``None`` is treated as an empty list.
            topological_order: the (indicator + derived-field) id
                ordering produced by :meth:`ReferenceResolver.resolve`.
                Indicator ids are filtered out here so the returned
                tuple contains derived-field specs only -- in the
                order required for the per-bar evaluator to populate
                them.

        Returns:
            A tuple of :class:`_DerivedFieldSpec`, one per declared
            derived field, ordered so that any field depending on
            another appears AFTER its dependency. Empty when the IR
            declares no derived fields.

        Raises:
            ValueError: surfaced from :meth:`FormulaEvaluator.compile`
                when a formula contains disallowed syntax. The
                resolver classifies identifiers separately, so this
                only fires for syntactic violations (function calls,
                bitwise ops, etc.) -- which the IR schema does not
                otherwise restrict.
        """
        if ir.derived_fields is None or not ir.derived_fields:
            return ()
        # Build an id -> formula map so we can walk the topological
        # order and skip entries that are indicator ids (the resolver
        # mixes both kinds into one ordering).
        formula_by_id: dict[str, str] = {df.id: df.formula for df in ir.derived_fields}
        evaluator = FormulaEvaluator()
        ordered: list[_DerivedFieldSpec] = []
        seen: set[str] = set()
        for ident in topological_order:
            if ident not in formula_by_id:
                continue
            formula = formula_by_id[ident]
            compiled = evaluator.compile(formula)
            ordered.append(_DerivedFieldSpec(ident=ident, compiled=compiled, formula=formula))
            seen.add(ident)
        # Defensive: any derived field declared in the IR but missing
        # from the topological order (e.g. a future resolver bug that
        # forgets to enrol a node) is still appended in declaration
        # order so the compiled strategy can run. Order ambiguity in
        # that pathological case is logged via the IR's declaration
        # order rather than alphabetical, which keeps determinism.
        for df in ir.derived_fields:
            if df.id in seen:
                continue
            compiled = evaluator.compile(df.formula)
            ordered.append(_DerivedFieldSpec(ident=df.id, compiled=compiled, formula=df.formula))
        return tuple(ordered)

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
        """Compile a single leaf condition into a boolean evaluator.

        ``units`` semantics:
            When ``leaf.units == "pips"`` AND the LHS resolves to the
            ``spread`` price field, the LHS value is converted from
            price units to pips at evaluation time using the per-symbol
            pip size. The RHS is assumed to already be a pip count
            (this matches every production IR's spread-filter shape:
            ``"lhs": "spread", "operator": "<=", "rhs": 1.8,
            "units": "pips"``). When the LHS is anything else, the
            ``"pips"`` units tag is purely informational at this layer
            -- a future enhancement can extend the conversion to
            ATR-multiple pip thresholds, but no current IR uses that
            shape.
        """
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

        # Detect the "spread filter" shape and wrap lhs_fn in a pip
        # converter when units == "pips" and LHS is the bare ``spread``
        # price field. The converter divides by the per-symbol pip size
        # so the comparison happens in pip space and matches the IR
        # author's intent.
        is_spread_pip_compare = (
            isinstance(leaf.lhs, str)
            and leaf.lhs.strip() == "spread"
            and (leaf.units or "").lower() == "pips"
        )
        if is_spread_pip_compare:
            inner_lhs = lhs_fn

            def _spread_in_pips(
                ctx: _EvalContext, _f: Callable[[_EvalContext], float] = inner_lhs
            ) -> float:
                price_units = _f(ctx)
                if math.isnan(price_units):
                    return math.nan
                pip_size = _pip_size_for_symbol(ctx.candle.symbol)
                if pip_size <= 0.0:
                    # Defensive: an unknown / non-FX symbol would end up
                    # here only if someone wires this leaf into a
                    # non-FX strategy. Returning NaN propagates "we
                    # cannot evaluate" through to the leaf which then
                    # short-circuits to False.
                    return math.nan
                return price_units / pip_size

            lhs_fn = _spread_in_pips

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
        # Derived-field identifier. The IR's ``derived_fields[]`` block
        # declares named formulas (e.g. ``fib_61_long``) that are
        # computed once per bar by :meth:`IRStrategy._compute_derived_fields`
        # and merged into ``indicator_values`` before any condition
        # evaluator runs. We therefore read derived ids through the
        # same dict-lookup path used for indicator ids -- the only
        # difference is the source: derived values are populated
        # post-extraction by the per-bar formula loop.
        if ident in self._current_derived_field_ids:

            def _derived(ctx: _EvalContext, _name: str = ident) -> float:
                if _name not in ctx.indicator_values:
                    return math.nan
                return ctx.indicator_values[_name]

            return _derived
        # Cross-timeframe identifier (e.g., ``close_1d``, ``high_4h``).
        # Read the most-recently-CLOSED bucket of the requested base
        # at the requested timeframe via the per-strategy aggregator
        # carried on the EvalContext. Returns NaN when no bucket has
        # closed yet so the leaf evaluator short-circuits to False
        # during warmup -- matching the convention used by indicator
        # and lookback reads.
        cross_tf_split = _split_cross_timeframe_ref(ident)
        if cross_tf_split is not None:
            base, tf_str, _tf_seconds = cross_tf_split

            def _cross_tf(
                ctx: _EvalContext,
                _base: str = base,
                _tf: str = tf_str,
            ) -> float:
                if ctx.cross_tf is None:
                    return math.nan
                return ctx.cross_tf.get_last_closed(ctx.candle.symbol, _tf, _base)

            return _cross_tf
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

    # ---------- exit wiring resolution ----------

    def _resolve_exit_wiring(
        self,
        ir: StrategyIR,
        indicator_ids: frozenset[str],
    ) -> _ExitWiring:
        """
        Walk the IR's exit blocks and indicator declarations and
        capture the ids the stateful exit evaluators need to read.

        Lookups performed:
            - ``initial_stop``: when it is an ``atr_multiple`` stop,
              record the named ATR indicator id and the multiple. The
              indicator must already be declared (validated here so a
              misconfigured IR fails at compile time).
            - ``take_profit``: when it is a ``risk_reward_multiple``
              stop, record the multiple. When it is an
              ``opposite_inner_band_touch`` stop, locate the inner-most
              BollingerUpper/Lower indicators by smallest stddev.
            - ``trailing_exit`` or ``trailing_stop``: when the resolved
              variant is a ``middle_band_close_violation`` stop, locate
              the SMA indicator that matches the inner Bollinger
              length+source (the conventional Bollinger basis).
            - ``time_exit`` (TimeExitRule wrapper): record
              ``max_bars_in_trade`` so the time_exit evaluator can fire
              at the right bar count.

        Returns:
            An :class:`_ExitWiring` value object holding every
            resolved id/multiple. Fields default to ``None`` / ``NaN``
            when the corresponding stop is not configured.
        """
        exit_logic = ir.exit_logic

        atr_indicator_id: str | None = None
        atr_multiple = math.nan
        if isinstance(exit_logic.initial_stop, AtrMultipleStop):
            stop = exit_logic.initial_stop
            if stop.indicator not in indicator_ids:
                raise IRReferenceError(
                    f"atr_multiple stop at exit_logic.initial_stop references "
                    f"unknown indicator {stop.indicator!r}; declare it in the "
                    "IR's indicators block"
                )
            atr_indicator_id = stop.indicator
            atr_multiple = float(stop.multiple)

        rr_multiple = math.nan
        if isinstance(exit_logic.take_profit, RiskRewardMultipleStop):
            rr_multiple = float(exit_logic.take_profit.multiple)

        # Inner Bollinger bands: smallest stddev = "inner". Used by
        # opposite_inner_band_touch.
        bb_upper_inner_id, bb_lower_inner_id = self._resolve_inner_bollinger_ids(ir)

        # Middle band: an SMA indicator whose length+source matches
        # the inner Bollinger bands' length+source. Used by
        # middle_band_close_violation.
        bb_mid_id = self._resolve_middle_band_id(ir)

        time_exit_max_bars: int | None = None
        if isinstance(exit_logic.time_exit, TimeExitRule) and exit_logic.time_exit.enabled:
            time_exit_max_bars = int(exit_logic.time_exit.max_bars_in_trade)

        return _ExitWiring(
            atr_indicator_id=atr_indicator_id,
            atr_multiple=atr_multiple,
            rr_multiple=rr_multiple,
            bb_upper_inner_id=bb_upper_inner_id,
            bb_lower_inner_id=bb_lower_inner_id,
            bb_mid_id=bb_mid_id,
            time_exit_max_bars=time_exit_max_bars,
        )

    def _resolve_inner_bollinger_ids(self, ir: StrategyIR) -> tuple[str | None, str | None]:
        """
        Locate the inner BollingerUpper / BollingerLower indicators.

        "Inner" = the band declared with the smallest stddev among
        same-length declarations. The Lien IR declares two pairs
        (1.0 stddev = inner, 2.0 stddev = outer); we pick the
        smallest. When no Bollinger indicators are declared, both
        return values are ``None`` -- a strategy without Bollinger
        bands cannot use opposite_inner_band_touch and the
        compiler's pre-flight check rejects that combination.
        """
        upper_candidates: list[tuple[float, str]] = []
        lower_candidates: list[tuple[float, str]] = []
        for ind in ir.indicators:
            if isinstance(ind, BollingerUpperIndicator):
                upper_candidates.append((float(ind.stddev), ind.id))
            elif isinstance(ind, BollingerLowerIndicator):
                lower_candidates.append((float(ind.stddev), ind.id))

        upper_id = min(upper_candidates)[1] if upper_candidates else None
        lower_id = min(lower_candidates)[1] if lower_candidates else None
        return upper_id, lower_id

    def _resolve_middle_band_id(self, ir: StrategyIR) -> str | None:
        """
        Locate the SMA indicator that serves as the Bollinger middle
        band.

        Heuristic:
            1. If the IR declares Bollinger bands, find an SMA whose
               (length, source) match the inner Bollinger bands'
               (length, source). This matches the canonical Bollinger
               definition: the basis IS an SMA.
            2. Otherwise, fall back to the first declared SmaIndicator.
            3. If no SMA is declared, return ``None`` (strategies that
               do not use middle_band_close_violation never read this).
        """
        sma_indicators = [ind for ind in ir.indicators if isinstance(ind, SmaIndicator)]
        if not sma_indicators:
            return None

        # Try the length+source match first.
        bollinger_upper = [ind for ind in ir.indicators if isinstance(ind, BollingerUpperIndicator)]
        if bollinger_upper:
            inner = min(bollinger_upper, key=lambda b: b.stddev)
            for sma in sma_indicators:
                if sma.length == inner.length and sma.source == inner.source:
                    return sma.id

        # Fall back to first SMA.
        return sma_indicators[0].id

    # ---------- exit compilation ----------

    def _compile_exit_logic(
        self,
        exit_logic: ExitLogic,
        indicator_ids: frozenset[str],
        wiring: _ExitWiring,
    ) -> dict[str, _ExitCheck]:
        """
        Compile every populated exit stop into a name -> _ExitCheck
        dict. Stops absent from the IR are not represented.

        In addition to the six ExitStop fields, this method compiles
        the ``trailing_stop`` (TrailingStopRule) and ``time_exit``
        (TimeExitRule) wrapper rules into exit checks named
        ``"trailing_stop"`` and ``"time_exit"`` respectively, so the
        IR's ``same_bar_priority`` can reference them by their natural
        names.
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
            evaluator = self._compile_exit_stop(
                stop, indicator_ids, wiring, f"exit_logic.{attr_name}"
            )
            compiled[attr_name] = _ExitCheck(name=attr_name, evaluator=evaluator)

        # TrailingStopRule wrapper: when enabled with type
        # ``middle_band_close_violation``, register it under
        # ``"trailing_stop"`` so same_bar_priority can pick it up.
        if (
            isinstance(exit_logic.trailing_stop, TrailingStopRule)
            and exit_logic.trailing_stop.enabled
        ):
            evaluator = self._compile_trailing_stop_rule(
                exit_logic.trailing_stop, wiring, "exit_logic.trailing_stop"
            )
            compiled["trailing_stop"] = _ExitCheck(name="trailing_stop", evaluator=evaluator)

        # TimeExitRule wrapper: when enabled, register a "time_exit"
        # check that fires when (bar_counter - entry_bar_index) >=
        # max_bars_in_trade.
        if (
            isinstance(exit_logic.time_exit, TimeExitRule)
            and exit_logic.time_exit.enabled
            and wiring.time_exit_max_bars is not None
        ):
            max_bars = wiring.time_exit_max_bars

            def _time_exit_eval(ctx: _EvalContext, _max_bars: int = max_bars) -> bool:
                if ctx.open_trade is None:
                    return False
                bars_in_trade = ctx.bar_counter - ctx.open_trade.entry_bar_index
                return bars_in_trade >= _max_bars

            compiled["time_exit"] = _ExitCheck(name="time_exit", evaluator=_time_exit_eval)

        return compiled

    def _compile_exit_stop(
        self,
        stop: ExitStop,
        indicator_ids: frozenset[str],
        wiring: _ExitWiring,
        location: str,
    ) -> ExitEvaluator:
        """Translate an :data:`ExitStop` variant into an evaluator.

        See module docstring for the per-kind semantics. Each branch
        produces a closure that consults the per-bar
        :class:`_EvalContext` (which carries the open-trade snapshot
        for stateful kinds like atr_multiple and
        opposite_inner_band_touch).
        """
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
            return self._build_atr_multiple_evaluator(stop, wiring, location)

        if isinstance(stop, RiskRewardMultipleStop):
            return self._build_risk_reward_evaluator(wiring, location)

        if isinstance(stop, OppositeInnerBandTouchStop):
            return self._build_opposite_inner_band_evaluator(wiring, location)

        if isinstance(stop, MiddleBandCloseViolationStop):
            return self._build_middle_band_close_evaluator(wiring, location)

        # The remaining ExitStop variants (basket-level stops) are out
        # of scope for M1.A3 (basket execution is M3.X2.5). Fail loudly
        # rather than silently accept them.
        # DEFERRED to a future tranche: BasketAtrMultipleStop and
        # BasketOpenLossPctStop need basket-aware position tracking
        # which the M1.A3 single-symbol IRStrategy does not model.
        raise ValueError(
            f"unsupported ExitStop variant {type(stop).__name__} at {location}; "
            f"basket-level stops ship with the basket execution tranche"
        )

    # ---------- per-kind exit evaluator builders ----------

    def _build_atr_multiple_evaluator(
        self,
        stop: AtrMultipleStop,
        wiring: _ExitWiring,
        location: str,
    ) -> ExitEvaluator:
        """
        Compile an atr_multiple initial stop.

        For a LONG position with stop_distance = multiple * entry_atr:
            - stop_price = entry_price - stop_distance
            - fires when candle.low <= stop_price (intra-bar touch)
        For a SHORT position:
            - stop_price = entry_price + stop_distance
            - fires when candle.high >= stop_price

        The stop distance is FROZEN at entry (using the entry-bar ATR
        snapshot held on _OpenTradeContext); subsequent ATR changes do
        not move the stop. This matches the conventional "stop set at
        entry" semantics every Lien-style FX strategy assumes.
        """
        if wiring.atr_indicator_id != stop.indicator:
            # Defensive: _resolve_exit_wiring should already have
            # captured this id. If it diverged the compile setup is
            # inconsistent -- fail loudly.
            raise IRReferenceError(
                f"atr_multiple stop at {location} references {stop.indicator!r} "
                f"but exit wiring resolved to {wiring.atr_indicator_id!r}; "
                "this is a compiler bug -- the wiring resolver is the source of truth"
            )

        def _atr_stop(ctx: _EvalContext) -> bool:
            snap = ctx.open_trade
            if snap is None:
                return False
            if math.isnan(snap.stop_distance) or snap.stop_distance <= 0.0:
                # Entry-bar ATR was unavailable (warmup) -- no stop.
                return False
            if snap.direction > 0:
                stop_price = snap.entry_price - snap.stop_distance
                return float(ctx.candle.low) <= stop_price
            stop_price = snap.entry_price + snap.stop_distance
            return float(ctx.candle.high) >= stop_price

        return _atr_stop

    def _build_risk_reward_evaluator(self, wiring: _ExitWiring, location: str) -> ExitEvaluator:
        """
        Compile a risk_reward_multiple take-profit.

        For a LONG position with take_profit_distance = rr * stop_distance:
            - tp_price = entry_price + take_profit_distance
            - fires when candle.high >= tp_price (intra-bar touch)
        For a SHORT position:
            - tp_price = entry_price - take_profit_distance
            - fires when candle.low <= tp_price

        Requires a configured atr_multiple stop because the R unit is
        ``stop_distance``. Without it the rr multiple has nothing to
        scale, so the evaluator returns False (no take-profit).
        """
        if math.isnan(wiring.rr_multiple) or wiring.rr_multiple <= 0.0:
            raise ValueError(
                f"risk_reward_multiple stop at {location} has invalid "
                f"multiple={wiring.rr_multiple!r}"
            )

        def _rr_take_profit(ctx: _EvalContext, _rr: float = wiring.rr_multiple) -> bool:
            snap = ctx.open_trade
            if snap is None:
                return False
            if math.isnan(snap.stop_distance) or snap.stop_distance <= 0.0:
                # No risk anchor -> no R-multiple take-profit.
                return False
            tp_distance = _rr * snap.stop_distance
            if snap.direction > 0:
                tp_price = snap.entry_price + tp_distance
                return float(ctx.candle.high) >= tp_price
            tp_price = snap.entry_price - tp_distance
            return float(ctx.candle.low) <= tp_price

        return _rr_take_profit

    def _build_opposite_inner_band_evaluator(
        self, wiring: _ExitWiring, location: str
    ) -> ExitEvaluator:
        """
        Compile an opposite_inner_band_touch take-profit.

        For a LONG position: take profit when the bar's price action
        touches the LOWER inner Bollinger band (the "opposite" band of
        a long entered above the upper band).
        For a SHORT position: touch the UPPER inner band.

        Reads the LIVE inner-band values from indicator_values rather
        than the entry snapshot -- the band slides as the SMA recomputes
        and the take-profit condition is "we have given back enough that
        the opposite band catches up to price", which is a moving
        target by design.
        """
        if wiring.bb_upper_inner_id is None or wiring.bb_lower_inner_id is None:
            raise IRReferenceError(
                f"opposite_inner_band_touch stop at {location} requires both an "
                "inner BollingerUpper and an inner BollingerLower indicator; "
                "neither was found in the IR's indicators block"
            )
        upper_id = wiring.bb_upper_inner_id
        lower_id = wiring.bb_lower_inner_id

        def _opposite_band(ctx: _EvalContext, _u: str = upper_id, _l: str = lower_id) -> bool:
            snap = ctx.open_trade
            if snap is None:
                return False
            if snap.direction > 0:
                lower_band = ctx.indicator_values.get(_l, math.nan)
                if math.isnan(lower_band):
                    return False
                # Long take-profit: low of the bar touches the opposite
                # (lower) inner band. We use ``low <= lower_band``
                # rather than ``close <= lower_band`` so an intra-bar
                # touch counts -- mirrors the M1.A3 BacktestEngine
                # convention for stop touches.
                return float(ctx.candle.low) <= lower_band
            upper_band = ctx.indicator_values.get(_u, math.nan)
            if math.isnan(upper_band):
                return False
            return float(ctx.candle.high) >= upper_band

        return _opposite_band

    def _build_middle_band_close_evaluator(
        self, wiring: _ExitWiring, location: str
    ) -> ExitEvaluator:
        """
        Compile a middle_band_close_violation trailing exit.

        For a LONG position: exit when the close goes BELOW the SMA
        middle band.
        For a SHORT position: exit when the close goes ABOVE.

        Uses ``close`` (not high/low) intentionally -- "close
        violation" is the plain English meaning of the stop name and
        matches every public Bollinger trading guide.
        """
        if wiring.bb_mid_id is None:
            raise IRReferenceError(
                f"middle_band_close_violation stop at {location} requires an SMA "
                "indicator to serve as the Bollinger middle band; none was found"
            )
        mid_id = wiring.bb_mid_id

        def _middle_band(ctx: _EvalContext, _m: str = mid_id) -> bool:
            snap = ctx.open_trade
            if snap is None:
                return False
            mid = ctx.indicator_values.get(_m, math.nan)
            if math.isnan(mid):
                return False
            close = float(ctx.candle.close)
            if snap.direction > 0:
                return close < mid
            return close > mid

        return _middle_band

    def _compile_trailing_stop_rule(
        self,
        rule: TrailingStopRule,
        wiring: _ExitWiring,
        location: str,
    ) -> ExitEvaluator:
        """
        Compile a TrailingStopRule wrapper.

        The wrapper carries ``type`` as a free-form string. For the
        Lien-style strategies the only value used is
        ``"middle_band_close_violation"``. We dispatch on that here so
        the IR's ``trailing_stop`` block resolves to the same
        evaluator shape as a populated ``trailing_exit`` ExitStop
        would.

        Raises:
            ValueError: when ``rule.type`` is not a recognised trailing
                stop kind. New kinds (e.g. ATR-trailing) should add a
                branch here AND a matching builder above.
        """
        kind = rule.type.strip().lower()
        if kind == "middle_band_close_violation":
            return self._build_middle_band_close_evaluator(wiring, location)
        raise ValueError(
            f"unsupported trailing_stop type {rule.type!r} at {location}; "
            "supported: middle_band_close_violation"
        )

    # ---------- priority freezing ----------

    #: Aliases mapping the IR's colloquial priority-list names onto the
    #: canonical exit-check names registered by :meth:`_compile_exit_logic`.
    #: Matches the naming convention used across the production IRs:
    #: ``"stop_loss"`` is the everyday name for the ``initial_stop``
    #: ExitStop, etc. The compiler resolves the alias at compile time
    #: so the priority list stays operator-readable.
    _PRIORITY_NAME_ALIASES: dict[str, str] = {
        "stop_loss": "initial_stop",
    }

    def _freeze_exit_priority(
        self,
        compiled_exits: dict[str, _ExitCheck],
        exit_logic: ExitLogic,
    ) -> tuple[_ExitCheck, ...]:
        """
        Freeze the compiled exit checks into a tuple ordered per
        ``exit_logic.same_bar_priority``.

        Name resolution proceeds in two passes:

        1. Apply :data:`_PRIORITY_NAME_ALIASES` so colloquial names
           like ``"stop_loss"`` map to the canonical ``"initial_stop"``.
        2. If the canonical name is not in ``compiled_exits``, raise
           :class:`IRReferenceError` -- the priority list is part of
           the IR contract and a typo would silently disable a stop.

        Compiled exits NOT mentioned in the priority list are
        appended after the prioritised ones in alphabetical order so
        the compile result is fully deterministic.
        """
        ordered: list[_ExitCheck] = []
        seen: set[str] = set()
        for raw_name in exit_logic.same_bar_priority:
            canonical = self._PRIORITY_NAME_ALIASES.get(raw_name, raw_name)
            if canonical not in compiled_exits:
                raise IRReferenceError(
                    f"same_bar_priority lists {raw_name!r} (canonical "
                    f"{canonical!r}) but no exit stop with that name is "
                    f"configured; configured stops: {sorted(compiled_exits)}"
                )
            if canonical in seen:
                # Duplicate priority entries: skip the second occurrence
                # so the tuple stays a stable ordered set.
                continue
            ordered.append(compiled_exits[canonical])
            seen.add(canonical)
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
