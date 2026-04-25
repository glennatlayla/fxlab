"""
Per-indicator lookback buffers and IR scanning for ``_prev_N`` references.

Purpose:
    Support the ``_prev_N`` suffix on any indicator id or price-field
    reference appearing in a StrategyIR leaf condition (e.g.
    ``bb_upper_1_prev_1``, ``close_prev_2``). The compiler consumes
    this module at compile time to:

      1. Discover every ``_prev_N`` reference under
         ``entry_logic`` / ``exit_logic`` / ``filters``.
      2. For each base name (the part before ``_prev_N``), record the
         maximum N observed so a single ring buffer of the right size
         can be allocated -- bases that nobody references with
         ``_prev_*`` get no buffer at all.
      3. Hand the resulting :class:`LookbackPlan` to the compiler so
         identifier compilation can emit "read this buffer at offset N"
         closures.

Responsibilities:
    - :class:`LookbackBuffer` -- a fixed-size, deterministic ring
      buffer that stores the last ``capacity`` values pushed into it
      and exposes ``get(n)`` returning "the value from N bars ago"
      (or NaN when fewer than N bars have been observed). The buffer
      is purely in-process; it never reads a wall clock and never
      consults any external source.
    - :class:`LookbackResolver` -- walks a parsed :class:`StrategyIR`,
      discovers every ``_prev_N`` reference, and returns a
      :class:`LookbackPlan` mapping each base name to its required
      capacity (= MAX(N) across all references to that base).

Does NOT:
    - Mutate the input IR. The resolver is read-only.
    - Validate that the base of a ``_prev_N`` reference exists. That
      is :mod:`libs.strategy_ir.reference_resolver`'s job; this
      module just collects the lookback shape.
    - Persist anything; buffers are pure in-process objects rebuilt
      on every compile.
    - Care about WHEN values are pushed. The compiler chooses the
      push order (after a bar's evaluation completes) so the buffer
      holds prior-bar values at the start of the next bar's
      evaluation.

Dependencies:
    - :mod:`libs.contracts.strategy_ir` -- IR types.
    - Standard library only otherwise.

Raises:
    - :class:`ValueError`: when a ``_prev_N`` suffix specifies an N
      that is zero or negative -- the IR contracts already constrain
      this at parse time, but the resolver guards against malformed
      input defensively.

Example::

    from libs.contracts.strategy_ir import StrategyIR
    from libs.strategy_ir.lookback import LookbackResolver

    ir = StrategyIR.model_validate(body)
    plan = LookbackResolver(ir).resolve()
    # plan.capacities == {"bb_upper_1": 1, "close": 1, "bb_mid": 1}
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass, field
from typing import Iterable

from libs.contracts.strategy_ir import (
    AtrMultipleStop,
    BasketAtrMultipleStop,
    CalendarExitStop,
    ChannelExitStop,
    ConditionTree,
    EntryLogic,
    ExitLogic,
    ExitStop,
    Filter,
    LeafCondition,
    MeanReversionToMidStop,
    StrategyIR,
    ZscoreStop,
)

# ---------------------------------------------------------------------------
# Module-level constants
# ---------------------------------------------------------------------------

#: Regex matching a single identifier token within a free-form expression
#: string. Mirrors the resolver's tokenizer so the two stay in sync.
_IDENT_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")

#: Suffix pattern for a "previous bar N back" reference, e.g.
#: ``close_prev_1``, ``bb_upper_1_prev_2``. The base name (everything
#: before ``_prev_<N>``) plus ``N`` are captured.
_PREV_BAR_SUFFIX_RE = re.compile(r"^(?P<base>.+)_prev_(?P<lag>\d+)$")


# ---------------------------------------------------------------------------
# LookbackBuffer
# ---------------------------------------------------------------------------


class LookbackBuffer:
    """
    Fixed-capacity ring buffer of recent ``float`` values for ONE
    indicator id or price field.

    Responsibilities:
    - Store the most recent ``capacity`` values pushed into the buffer
      via :meth:`push` in O(1).
    - Return "the value from ``n`` bars ago" via :meth:`get` in O(1),
      where ``n=1`` means "the most recently pushed value".
    - Yield NaN whenever the requested lag exceeds the number of
      values pushed so far (so leaf-condition evaluators short-circuit
      to ``False`` on warmup bars instead of raising).

    Does NOT:
    - Read a wall clock or any external source.
    - Auto-evict on time; eviction is purely positional (oldest value
      is overwritten when capacity is exceeded).
    - Validate the value's domain. Callers must hand in plain floats
      (NaN is allowed and propagates through ``get``).

    Dependencies:
    - Standard library only.

    Raises:
    - :class:`ValueError`: when ``capacity < 1`` at construction, or
      when :meth:`get` is called with ``n < 1`` or ``n > capacity``.

    Example::

        buf = LookbackBuffer(capacity=2)
        buf.push(1.10)
        buf.push(1.11)
        assert buf.get(1) == 1.11   # most recent push
        assert buf.get(2) == 1.10   # one before that
    """

    __slots__ = ("_capacity", "_values", "_count")

    def __init__(self, capacity: int) -> None:
        """
        Allocate a buffer that retains the last ``capacity`` pushes.

        Args:
            capacity: maximum number of values retained. Must be >= 1.

        Raises:
            ValueError: when ``capacity < 1``.
        """
        if capacity < 1:
            raise ValueError(
                f"LookbackBuffer capacity must be >= 1, got {capacity}; "
                f"a zero-sized buffer cannot serve any _prev_N reference"
            )
        self._capacity = capacity
        # Pre-fill with NaN so reads before any push return NaN cleanly.
        # We use a plain list (not collections.deque) so :meth:`get`
        # is O(1) by index arithmetic rather than O(n) by deque
        # traversal.
        self._values: list[float] = [math.nan] * capacity
        # Number of values pushed so far. Caps at ``capacity`` once the
        # buffer is full -- we don't need to track beyond that.
        self._count: int = 0

    @property
    def capacity(self) -> int:
        """Maximum number of recent values this buffer retains."""
        return self._capacity

    @property
    def filled(self) -> int:
        """Number of valid (non-warmup) values currently in the buffer."""
        return self._count

    def push(self, value: float) -> None:
        """
        Append a new value, evicting the oldest if at capacity.

        Args:
            value: the latest scalar value (typically the trailing
                element of an indicator's values array, or a bar's
                price field). NaN is permitted and propagates through
                subsequent :meth:`get` calls at the corresponding lag.
        """
        # Shift left by one and write the new value at the tail. Using
        # a Python list in-place keeps the operation allocation-free
        # after construction. For the small capacities typical in IR
        # lookbacks (single digits), this is faster than a deque.
        self._values[:-1] = self._values[1:]
        self._values[-1] = float(value)
        if self._count < self._capacity:
            self._count += 1

    def get(self, n: int) -> float:
        """
        Return the value pushed ``n`` bars ago.

        ``n=1`` returns the most recently pushed value, ``n=2`` the
        one before that, and so on up to ``n=capacity``.

        Args:
            n: lag in bars; 1 means "most recent push", capacity means
                "oldest retained value". Must satisfy
                ``1 <= n <= capacity``.

        Returns:
            The float value at the requested lag, or ``NaN`` when
            fewer than ``n`` values have been pushed so far.

        Raises:
            ValueError: when ``n < 1`` or ``n > capacity``.
        """
        if n < 1 or n > self._capacity:
            raise ValueError(f"LookbackBuffer.get(n={n}) out of range; capacity={self._capacity}")
        if n > self._count:
            # Warmup: not enough history yet.
            return math.nan
        # The most recent value lives at index -1; n bars ago lives
        # at index -n. Indexing from the tail keeps the math the same
        # whether the buffer is full or only partially filled.
        return self._values[-n]

    def reset(self) -> None:
        """
        Clear all stored values. After ``reset``, every ``get`` returns
        NaN until ``push`` has been called enough times.

        Used by tests that replay a strategy over multiple synthetic
        streams; production compiled strategies build a fresh buffer
        per :meth:`compile` call so reset is rarely needed in the live
        path.
        """
        for i in range(self._capacity):
            self._values[i] = math.nan
        self._count = 0


# ---------------------------------------------------------------------------
# LookbackPlan + LookbackResolver
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class LookbackPlan:
    """
    Result of scanning a StrategyIR for ``_prev_N`` references.

    Attributes:
        capacities: mapping ``{base_name: max_N}`` covering every
            indicator id or price field that ANY leaf condition
            references with a ``_prev_N`` suffix. Bases never
            referenced via ``_prev_*`` are absent from the map (they
            do not need a buffer). The integer value is the maximum N
            seen across all references to that base, so the compiler
            allocates one buffer of exactly the right size.

    Example::

        plan = LookbackResolver(ir).resolve()
        for base, n in plan.capacities.items():
            buffers[base] = LookbackBuffer(capacity=n)
    """

    capacities: dict[str, int]


@dataclass
class _LookbackState:
    """Mutable working state for one resolve() invocation."""

    capacities: dict[str, int] = field(default_factory=dict)


class LookbackResolver:
    """
    Walk a StrategyIR and collect the maximum lookback per indicator /
    price-field base name.

    Responsibilities:
    - Visit every leaf condition reachable from
      ``entry_logic`` (long, short, basket templates, entry filters),
      ``exit_logic`` (every populated stop wrapper), and the
      top-level ``filters`` block.
    - Tokenise the ``lhs`` and (when string-valued) ``rhs`` of each
      leaf, extract any ``_prev_N`` suffix, and merge it into a
      ``{base: max_N}`` map.
    - Return a frozen :class:`LookbackPlan` the compiler consumes.

    Does NOT:
    - Mutate the input IR.
    - Verify that the base of a ``_prev_N`` reference resolves to a
      declared indicator or price field. That is the
      :mod:`reference_resolver`'s job; this resolver only collects
      shape information.
    - Allocate buffers. The compiler decides how to allocate based on
      the returned plan.

    Dependencies:
    - :class:`StrategyIR` (immutable input).

    Raises:
    - :class:`ValueError`: when a ``_prev_N`` suffix specifies a
      non-positive N. The IR contracts forbid this at parse time but
      we guard defensively.

    Example::

        plan = LookbackResolver(ir).resolve()
        # plan.capacities == {"bb_upper_1": 1, "close": 1}
    """

    def __init__(self, ir: StrategyIR) -> None:
        """
        Bind the resolver to an IR. The IR is not inspected until
        :meth:`resolve` is called so construction is cheap.

        Args:
            ir: a parsed and validated StrategyIR.
        """
        self._ir = ir

    # ---------------------------------------------------------------
    # Public API
    # ---------------------------------------------------------------

    def resolve(self) -> LookbackPlan:
        """
        Scan the IR and return the per-base maximum lookback plan.

        Returns:
            :class:`LookbackPlan` whose ``capacities`` dict covers
            every base referenced via ``_prev_N`` somewhere in the
            IR. Bases never referenced are absent.

        Raises:
            ValueError: when a ``_prev_N`` suffix has N < 1.
        """
        state = _LookbackState()

        self._scan_entry_logic(state, self._ir.entry_logic)
        self._scan_exit_logic(state, self._ir.exit_logic)
        if self._ir.filters is not None:
            self._scan_filters(state, self._ir.filters)

        # Freeze a copy of the capacities into the returned plan so
        # callers cannot mutate the resolver's working state.
        return LookbackPlan(capacities=dict(state.capacities))

    # ---------------------------------------------------------------
    # Entry logic
    # ---------------------------------------------------------------

    def _scan_entry_logic(self, state: _LookbackState, entry_logic: EntryLogic) -> None:
        """Walk every leaf condition reachable from entry_logic."""
        if entry_logic.long is not None:
            self._scan_condition_tree(state, entry_logic.long.logic)
        if entry_logic.short is not None:
            self._scan_condition_tree(state, entry_logic.short.logic)
        if entry_logic.basket_templates is not None:
            for template in entry_logic.basket_templates:
                self._scan_leaf(state, template.active_when)
        if entry_logic.entry_filters is not None:
            self._scan_condition_tree(state, entry_logic.entry_filters)

    # ---------------------------------------------------------------
    # Exit logic
    # ---------------------------------------------------------------

    def _scan_exit_logic(self, state: _LookbackState, exit_logic: ExitLogic) -> None:
        """Walk every leaf condition reachable from exit_logic."""
        for attr_name in (
            "primary_exit",
            "initial_stop",
            "take_profit",
            "trailing_exit",
            "catastrophic_zscore_stop",
            "scheduled_exit",
            "equity_stop",
        ):
            stop = getattr(exit_logic, attr_name)
            if stop is None:
                continue
            self._scan_exit_stop(state, stop)

    def _scan_exit_stop(self, state: _LookbackState, stop: ExitStop) -> None:
        """Tokenise leaf conditions on a single ExitStop variant."""
        if isinstance(stop, (ChannelExitStop, MeanReversionToMidStop)):
            self._scan_leaf(state, stop.long_condition)
            self._scan_leaf(state, stop.short_condition)
        elif isinstance(stop, (CalendarExitStop, ZscoreStop)):
            self._scan_leaf(state, stop.condition)
        # AtrMultipleStop / BasketAtrMultipleStop carry only an
        # indicator name (no _prev_N suffix is meaningful there);
        # other variants (RiskReward, OppositeInnerBand, etc.) carry
        # no leaf conditions at all. Nothing to scan.
        elif isinstance(stop, (AtrMultipleStop, BasketAtrMultipleStop)):
            return

    # ---------------------------------------------------------------
    # Filters
    # ---------------------------------------------------------------

    def _scan_filters(self, state: _LookbackState, filters: list[Filter]) -> None:
        """Tokenise lhs/rhs on every Filter that carries an lhs."""
        for flt in filters:
            if flt.lhs is None:
                continue
            self._scan_expression(state, flt.lhs)
            if isinstance(flt.rhs, str):
                self._scan_expression(state, flt.rhs)

    # ---------------------------------------------------------------
    # Trees and leaves
    # ---------------------------------------------------------------

    def _scan_condition_tree(self, state: _LookbackState, tree: ConditionTree) -> None:
        """Recursively walk a condition tree."""
        for child in tree.conditions:
            if isinstance(child, ConditionTree):
                self._scan_condition_tree(state, child)
            else:
                self._scan_leaf(state, child)

    def _scan_leaf(self, state: _LookbackState, leaf: LeafCondition) -> None:
        """Tokenise the lhs (always) and rhs (when string) of a leaf."""
        self._scan_expression(state, leaf.lhs)
        if isinstance(leaf.rhs, str):
            self._scan_expression(state, leaf.rhs)

    def _scan_expression(self, state: _LookbackState, expression: str) -> None:
        """
        Pull every ``_prev_N`` token out of a free-form expression and
        merge into the running ``{base: max_N}`` map.
        """
        for token in _IDENT_RE.findall(expression):
            self._record_token(state, token)

    def _record_token(self, state: _LookbackState, token: str) -> None:
        """Record a single token if it carries a ``_prev_N`` suffix."""
        match = _PREV_BAR_SUFFIX_RE.match(token)
        if match is None:
            return
        base = match.group("base")
        lag = int(match.group("lag"))
        if lag < 1:
            raise ValueError(
                f"_prev_N suffix on {token!r} specifies non-positive N={lag}; "
                f"lookback offsets must be >= 1"
            )
        existing = state.capacities.get(base, 0)
        if lag > existing:
            state.capacities[base] = lag

    # ---------------------------------------------------------------
    # Convenience helpers exposed for tests
    # ---------------------------------------------------------------

    @staticmethod
    def split_prev_suffix(token: str) -> tuple[str, int] | None:
        """
        Split a token into ``(base, lag)`` if it carries a ``_prev_N``
        suffix; return ``None`` otherwise.

        Args:
            token: identifier token to inspect.

        Returns:
            ``(base, lag)`` when ``token`` matches ``<base>_prev_<N>``
            with N >= 1, else ``None``.

        Example::

            assert LookbackResolver.split_prev_suffix("close_prev_2") == ("close", 2)
            assert LookbackResolver.split_prev_suffix("close") is None
        """
        match = _PREV_BAR_SUFFIX_RE.match(token)
        if match is None:
            return None
        lag = int(match.group("lag"))
        if lag < 1:
            return None
        return match.group("base"), lag

    @staticmethod
    def iter_tokens(expression: str) -> Iterable[str]:
        """
        Iterate identifier tokens inside a free-form expression. Useful
        for tests asserting tokenisation parity with the resolver.
        """
        return _IDENT_RE.findall(expression)


__all__ = [
    "LookbackBuffer",
    "LookbackPlan",
    "LookbackResolver",
]
