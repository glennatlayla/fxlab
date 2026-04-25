"""
Reference resolver and dependency-DAG builder for a parsed StrategyIR.

Purpose:
    Bridge the gap between a syntactically valid :class:`StrategyIR`
    (validated by :mod:`libs.contracts.strategy_ir`) and a semantically
    valid one. The contracts layer guarantees the document parses; this
    layer guarantees every identifier referenced from a leaf condition,
    a stop wrapper, a derived-field formula, or a filter resolves to a
    declared symbol -- and that the indicators / derived-fields can be
    evaluated in a deterministic topological order with no cycles.

Responsibilities:
    - Build a name->Indicator map keyed on the indicator ``id``.
    - For every leaf condition encountered in entry_logic, exit_logic,
      and filters: classify ``lhs`` and (when string-valued) ``rhs`` as
      one of the known reference kinds (indicator, derived field, price
      field, cross-timeframe field, previous-bar reference, basket
      synthetic field, or numeric literal). An identifier that does not
      match any known kind raises :class:`IRReferenceError` with a
      location hint.
    - Validate stop-wrapper indicator references (e.g. the ``indicator``
      field on :class:`AtrMultipleStop`).
    - Validate the cross-references inside a :class:`ZscoreIndicator`
      definition (``mean_source`` / ``std_source``).
    - Build a dependency DAG over (indicator | derived_field) nodes
      whose edges encode "B reads from A", and return a topological
      ordering with alphabetical tie-break so the result is reproducible.

Does NOT:
    - Read files from disk (that is the parser's job).
    - Evaluate any indicator (the engine's job).
    - Translate expressions into runtime AST (the compiler's job).
    - Validate exotic synthetic fields beyond the limited set the
      production IRs already require (basket-spread average) -- adding
      a new synthetic kind is a deliberate schema event, not silent.

Dependencies:
    - :mod:`libs.contracts.strategy_ir` (Pydantic models).
    - Standard library only otherwise.

Raises:
    - :class:`IRReferenceError` whenever an identifier cannot be
      classified, or when a cycle is detected in the dependency DAG.

Example::

    from libs.contracts.strategy_ir import StrategyIR
    from libs.strategy_ir.reference_resolver import ReferenceResolver

    ir = StrategyIR.model_validate(body)
    resolved = ReferenceResolver(ir).resolve()
    for node_id in resolved.topological_order:
        ...
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Iterable

from libs.contracts.strategy_ir import (
    AtrMultipleStop,
    BasketAtrMultipleStop,
    BasketTemplate,
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
    ZscoreIndicator,
    ZscoreStop,
)

# ---------------------------------------------------------------------------
# Module-level constants
# ---------------------------------------------------------------------------

#: Regex matching a single identifier token within a free-form expression
#: string (e.g. ``ema_100`` inside ``"ema_100 * 0.985"``). Numeric
#: literals do NOT match because the leading character is forced to be a
#: letter or underscore.
_IDENT_RE = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")

#: Names that look like identifiers but are math built-ins, NOT references
#: to indicators or fields. The compiler will translate these to runtime
#: function calls; the resolver simply ignores them when classifying.
_MATH_FUNCTIONS = frozenset(
    {
        "abs",
        "min",
        "max",
        "sqrt",
        "log",
        "exp",
        "pow",
        "sign",
        "floor",
        "ceil",
        "round",
    }
)

#: Synthetic per-basket fields the engine computes on the fly. They are
#: only valid inside an entry_filters / basket_templates context (i.e.
#: when the IR declares ``basket_templates``). Adding a new synthetic
#: name here is a deliberate schema event.
_BASKET_SYNTHETIC_FIELDS = frozenset({"spread_basket_average"})

#: Suffix pattern for a "previous bar N back" reference, e.g.
#: ``close_prev_1``, ``bb_upper_1_prev_1``. The base name (everything
#: before the suffix) must itself resolve cleanly.
_PREV_BAR_SUFFIX_RE = re.compile(r"^(?P<base>.+)_prev_(?P<lag>\d+)$")


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class IRReferenceError(Exception):
    """
    Raised when a StrategyIR contains an unresolvable identifier
    or a cycle in its indicator / derived-field dependency graph.

    The exception message always names the offending value AND a
    location hint (e.g. "entry_logic.long.conditions[0].lhs") so an
    operator can find the broken IR field without diff-hunting.
    """


# ---------------------------------------------------------------------------
# Data classes -- small, immutable result types for the resolver
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class ResolvedReference:
    """
    A single classified reference encountered in the IR.

    Attributes:
        location: human-readable path inside the IR (e.g.
            ``entry_logic.long.conditions[2].rhs``) used for error
            messages and debugging.
        raw_value: the string or numeric literal as it appeared in the
            IR field.
        kind: classification, one of ``indicator``, ``derived_field``,
            ``price_field``, ``cross_timeframe``, ``literal``,
            ``previous_bar``, ``basket_synthetic``, ``expression_atom``.
        target_id: when the reference points to a declared node
            (indicator id, derived field id, or the base of a
            previous-bar reference), the id is captured here. ``None``
            for pure literals.
    """

    location: str
    raw_value: object
    kind: str
    target_id: str | None


@dataclass(frozen=True)
class ResolvedReferences:
    """
    The full output of :meth:`ReferenceResolver.resolve`.

    Attributes:
        references: every reference resolved during the pass, ordered
            by the order in which the resolver encountered them. Useful
            for downstream debugging / IR linting.
        topological_order: indicator and derived-field ids in an order
            such that every node appears AFTER all the nodes it depends
            on. Tie-break is alphabetical for reproducibility.
    """

    references: tuple[ResolvedReference, ...]
    topological_order: tuple[str, ...]


# ---------------------------------------------------------------------------
# Resolver
# ---------------------------------------------------------------------------


@dataclass
class _ResolverState:
    """Mutable working state for a single resolve() invocation."""

    indicator_ids: frozenset[str]
    derived_field_ids: frozenset[str]
    price_fields: frozenset[str]
    confirmation_timeframes: frozenset[str]
    primary_timeframe: str
    has_basket_templates: bool
    references: list[ResolvedReference] = field(default_factory=list)
    # Adjacency list for the dependency DAG over node ids
    # (indicators + derived fields). Edge ``a -> b`` means b depends on a.
    edges_out: dict[str, set[str]] = field(default_factory=dict)


class ReferenceResolver:
    """
    Resolve identifiers and build a dependency DAG over a StrategyIR.

    Responsibilities:
        - Classify every identifier in every leaf condition / stop /
          filter / derived-field formula.
        - Build the (indicator | derived_field) dependency graph and
          return a deterministic topological order.

    Does NOT:
        - Mutate the input IR.
        - Evaluate or compile any expression.

    Dependencies:
        - StrategyIR (immutable input).

    Raises:
        - IRReferenceError: dangling identifier, or cycle in the DAG.

    Example::

        resolver = ReferenceResolver(ir)
        resolved = resolver.resolve()
    """

    def __init__(self, ir: StrategyIR) -> None:
        """
        Bind the resolver to a StrategyIR. The IR is not inspected
        until :meth:`resolve` is called so construction is cheap.

        Args:
            ir: a parsed and validated StrategyIR.
        """
        self._ir = ir

    # ---------------------------------------------------------------
    # Public API
    # ---------------------------------------------------------------

    def resolve(self) -> ResolvedReferences:
        """
        Walk the IR, classify every reference, build the DAG, and
        return a :class:`ResolvedReferences` carrying the topological
        order of (indicator | derived_field) ids.

        Returns:
            ResolvedReferences with the full reference inventory and
            a deterministic topological ordering.

        Raises:
            IRReferenceError: when any identifier is unresolved, a
                stop wrapper points at a non-existent indicator, a
                derived-field formula references unknown ids, or the
                dependency graph contains a cycle.
        """
        state = self._build_state()

        # 1. Validate indicator-internal cross references (zscore, etc.)
        #    These also contribute edges to the dependency DAG.
        self._resolve_indicator_definitions(state)

        # 2. Resolve derived-field formulas. These contribute edges too.
        self._resolve_derived_fields(state)

        # 3. Walk every leaf condition in entry_logic, exit_logic,
        #    filters. These do NOT contribute DAG edges (conditions
        #    consume nodes; they are not nodes themselves).
        self._resolve_entry_logic(state, self._ir.entry_logic)
        self._resolve_exit_logic(state, self._ir.exit_logic)
        if self._ir.filters is not None:
            self._resolve_filters(state, self._ir.filters)

        # 4. Topologically sort the DAG.
        order = self._topological_sort(state)

        return ResolvedReferences(
            references=tuple(state.references),
            topological_order=tuple(order),
        )

    # ---------------------------------------------------------------
    # Initial state
    # ---------------------------------------------------------------

    def _build_state(self) -> _ResolverState:
        """Snapshot the IR's namespace into a working _ResolverState."""
        ir = self._ir
        indicator_ids = frozenset(ind.id for ind in ir.indicators)
        derived_field_ids = (
            frozenset(df.id for df in ir.derived_fields)
            if ir.derived_fields is not None
            else frozenset()
        )

        # Reject duplicate ids across indicators + derived_fields. A
        # duplicate would silently shadow one definition with another
        # at lookup time -- worse than a parse failure, so block it
        # loudly here.
        overlap = indicator_ids & derived_field_ids
        if overlap:
            raise IRReferenceError(
                f"duplicate id(s) declared in both indicators and derived_fields: {sorted(overlap)}"
            )

        return _ResolverState(
            indicator_ids=indicator_ids,
            derived_field_ids=derived_field_ids,
            price_fields=frozenset(ir.data_requirements.required_fields),
            confirmation_timeframes=frozenset(ir.data_requirements.confirmation_timeframes),
            primary_timeframe=ir.data_requirements.primary_timeframe,
            has_basket_templates=ir.entry_logic.basket_templates is not None,
            edges_out={node_id: set() for node_id in (indicator_ids | derived_field_ids)},
        )

    # ---------------------------------------------------------------
    # Indicator definitions -- only zscore carries cross-references
    # ---------------------------------------------------------------

    def _resolve_indicator_definitions(self, state: _ResolverState) -> None:
        """
        Validate identifier fields embedded in indicator definitions.

        Today only ZscoreIndicator references other indicator ids
        (mean_source / std_source). Future indicator types that gain
        cross-references should be added here.
        """
        for index, ind in enumerate(self._ir.indicators):
            if isinstance(ind, ZscoreIndicator):
                location_mean = f"indicators[{index}].mean_source"
                location_std = f"indicators[{index}].std_source"
                self._classify_indicator_only_ref(
                    state, ind.mean_source, location_mean, dependent_id=ind.id
                )
                self._classify_indicator_only_ref(
                    state, ind.std_source, location_std, dependent_id=ind.id
                )

    # ---------------------------------------------------------------
    # Derived fields
    # ---------------------------------------------------------------

    def _resolve_derived_fields(self, state: _ResolverState) -> None:
        """Tokenize each derived-field formula and resolve every identifier."""
        if self._ir.derived_fields is None:
            return
        for index, df in enumerate(self._ir.derived_fields):
            self._resolve_expression(
                state,
                expression=df.formula,
                location=f"derived_fields[{index}].formula",
                dependent_node_id=df.id,
            )

    # ---------------------------------------------------------------
    # Entry logic
    # ---------------------------------------------------------------

    def _resolve_entry_logic(self, state: _ResolverState, entry_logic: EntryLogic) -> None:
        """Walk every leaf condition reachable from entry_logic."""
        if entry_logic.long is not None:
            self._resolve_condition_tree(
                state,
                tree=entry_logic.long.logic,
                location="entry_logic.long.logic",
            )
        if entry_logic.short is not None:
            self._resolve_condition_tree(
                state,
                tree=entry_logic.short.logic,
                location="entry_logic.short.logic",
            )
        if entry_logic.basket_templates is not None:
            for index, template in enumerate(entry_logic.basket_templates):
                self._resolve_basket_template(
                    state,
                    template=template,
                    location=f"entry_logic.basket_templates[{index}]",
                )
        if entry_logic.entry_filters is not None:
            self._resolve_condition_tree(
                state,
                tree=entry_logic.entry_filters,
                location="entry_logic.entry_filters",
            )

    def _resolve_basket_template(
        self,
        state: _ResolverState,
        template: BasketTemplate,
        location: str,
    ) -> None:
        """Resolve the active_when leaf condition on a basket template."""
        self._resolve_leaf_condition(
            state,
            leaf=template.active_when,
            location=f"{location}.active_when",
        )

    # ---------------------------------------------------------------
    # Exit logic
    # ---------------------------------------------------------------

    def _resolve_exit_logic(self, state: _ResolverState, exit_logic: ExitLogic) -> None:
        """Walk every leaf condition + indicator ref reachable from exit_logic."""
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
            self._resolve_exit_stop(state, stop=stop, location=f"exit_logic.{attr_name}")

    def _resolve_exit_stop(
        self,
        state: _ResolverState,
        stop: ExitStop,
        location: str,
    ) -> None:
        """Validate a single ExitStop variant."""
        if isinstance(stop, (AtrMultipleStop, BasketAtrMultipleStop)):
            # The .indicator field MUST be a known indicator id.
            self._classify_indicator_only_ref(
                state,
                identifier=stop.indicator,
                location=f"{location}.indicator",
                dependent_id=None,
            )
        elif isinstance(stop, (ChannelExitStop, MeanReversionToMidStop)):
            # Both stop variants carry direction-specific leaf
            # conditions under the same field names.
            self._resolve_leaf_condition(
                state, leaf=stop.long_condition, location=f"{location}.long_condition"
            )
            self._resolve_leaf_condition(
                state, leaf=stop.short_condition, location=f"{location}.short_condition"
            )
        elif isinstance(stop, (CalendarExitStop, ZscoreStop)):
            # Both wrap a single ``condition`` leaf.
            self._resolve_leaf_condition(
                state, leaf=stop.condition, location=f"{location}.condition"
            )
        # Other stop variants (RiskRewardMultipleStop,
        # OppositeInnerBandTouchStop, MiddleBandCloseViolationStop,
        # BasketOpenLossPctStop) carry no identifier references and
        # need no resolution.

    # ---------------------------------------------------------------
    # Filters
    # ---------------------------------------------------------------

    def _resolve_filters(self, state: _ResolverState, filters: list[Filter]) -> None:
        """Resolve identifier fields on every Filter that carries an lhs."""
        for index, flt in enumerate(filters):
            if flt.lhs is None:
                # Named-rule filters (e.g. ``bars_since_last_exit``)
                # carry no identifier reference.
                continue
            location = f"filters[{index}]"
            self._classify_atom(
                state,
                identifier=flt.lhs,
                location=f"{location}.lhs",
                dependent_node_id=None,
            )
            if isinstance(flt.rhs, str):
                self._resolve_expression(
                    state,
                    expression=flt.rhs,
                    location=f"{location}.rhs",
                    dependent_node_id=None,
                )

    # ---------------------------------------------------------------
    # Condition trees and leaves
    # ---------------------------------------------------------------

    def _resolve_condition_tree(
        self,
        state: _ResolverState,
        tree: ConditionTree,
        location: str,
    ) -> None:
        """Recursively walk a condition tree."""
        for index, child in enumerate(tree.conditions):
            child_location = f"{location}.conditions[{index}]"
            if isinstance(child, ConditionTree):
                self._resolve_condition_tree(state, tree=child, location=child_location)
            else:
                self._resolve_leaf_condition(state, leaf=child, location=child_location)

    def _resolve_leaf_condition(
        self,
        state: _ResolverState,
        leaf: LeafCondition,
        location: str,
    ) -> None:
        """Resolve the lhs and (when string-valued) rhs of a leaf condition."""
        # lhs may be a single identifier OR an expression like
        # "abs(price_zscore)".
        self._resolve_expression(
            state,
            expression=leaf.lhs,
            location=f"{location}.lhs",
            dependent_node_id=None,
        )
        if isinstance(leaf.rhs, str):
            self._resolve_expression(
                state,
                expression=leaf.rhs,
                location=f"{location}.rhs",
                dependent_node_id=None,
            )
        else:
            # Numeric literal -- record it so downstream linting can
            # see every reference, even pure literals.
            state.references.append(
                ResolvedReference(
                    location=f"{location}.rhs",
                    raw_value=leaf.rhs,
                    kind="literal",
                    target_id=None,
                )
            )

    # ---------------------------------------------------------------
    # Expression / atom classification
    # ---------------------------------------------------------------

    def _resolve_expression(
        self,
        state: _ResolverState,
        expression: str,
        location: str,
        dependent_node_id: str | None,
    ) -> None:
        """
        Resolve every identifier token inside a free-form expression.

        Args:
            state: working resolver state.
            expression: raw expression string from the IR.
            location: location hint for error messages.
            dependent_node_id: when the expression appears inside the
                definition of an indicator or derived field, the id of
                that node is recorded so DAG edges can be drawn from
                each referenced node into the dependent node. ``None``
                when the expression appears in a leaf condition or
                filter (those consume nodes; they are not nodes).
        """
        tokens = _IDENT_RE.findall(expression)
        if not tokens:
            # Pure numeric expression -- record one literal entry.
            state.references.append(
                ResolvedReference(
                    location=location,
                    raw_value=expression,
                    kind="literal",
                    target_id=None,
                )
            )
            return
        for token in tokens:
            if token in _MATH_FUNCTIONS:
                state.references.append(
                    ResolvedReference(
                        location=location,
                        raw_value=token,
                        kind="expression_atom",
                        target_id=None,
                    )
                )
                continue
            self._classify_atom(
                state,
                identifier=token,
                location=location,
                dependent_node_id=dependent_node_id,
            )

    def _classify_atom(
        self,
        state: _ResolverState,
        identifier: str,
        location: str,
        dependent_node_id: str | None,
    ) -> None:
        """
        Classify a single identifier atom and record it.

        Adds a DAG edge from the referenced node to ``dependent_node_id``
        when both are graph nodes (indicator or derived field) and a
        dependent context was provided. Raises IRReferenceError when
        the identifier is not classifiable.
        """
        kind, target_id = self._lookup_identifier(state, identifier)
        if kind is None:
            raise IRReferenceError(
                f"unresolved identifier {identifier!r} at {location}; "
                f"not an indicator id, derived_field id, price field, "
                f"cross-timeframe field, or basket synthetic"
            )
        state.references.append(
            ResolvedReference(
                location=location,
                raw_value=identifier,
                kind=kind,
                target_id=target_id,
            )
        )
        if dependent_node_id is not None and target_id is not None and target_id in state.edges_out:
            state.edges_out[target_id].add(dependent_node_id)

    def _classify_indicator_only_ref(
        self,
        state: _ResolverState,
        identifier: str,
        location: str,
        dependent_id: str | None,
    ) -> None:
        """
        Classify an identifier that MUST be an indicator id.

        Used by zscore indicators (mean_source / std_source) and by
        atr_multiple stops (.indicator). A non-indicator value here is
        always an error -- e.g. a price field would not satisfy the
        compiler, so we reject it eagerly.
        """
        if identifier not in state.indicator_ids:
            raise IRReferenceError(
                f"unresolved indicator reference {identifier!r} at "
                f"{location}; expected one of the declared indicator ids"
            )
        state.references.append(
            ResolvedReference(
                location=location,
                raw_value=identifier,
                kind="indicator",
                target_id=identifier,
            )
        )
        if dependent_id is not None and identifier in state.edges_out:
            state.edges_out[identifier].add(dependent_id)

    def _lookup_identifier(
        self, state: _ResolverState, identifier: str
    ) -> tuple[str | None, str | None]:
        """
        Try every reference-kind classifier in priority order.

        Returns:
            (kind, target_id) on success; (None, None) on failure.
            ``target_id`` is the id of a graph node when applicable
            (indicator, derived field, or the base of a previous-bar
            reference whose base is a graph node). For pure
            field-style references (price field, cross-timeframe,
            basket synthetic) ``target_id`` is None.
        """
        # 1. Direct indicator id.
        if identifier in state.indicator_ids:
            return "indicator", identifier
        # 2. Direct derived field id.
        if identifier in state.derived_field_ids:
            return "derived_field", identifier
        # 3. Bare price field (open/high/low/close/volume/spread).
        if identifier in state.price_fields:
            return "price_field", None
        # 4. Cross-timeframe field, e.g. close_1d, close_1h.
        if self._is_cross_timeframe_ref(state, identifier):
            return "cross_timeframe", None
        # 5. Basket synthetic, e.g. spread_basket_average -- only valid
        #    inside a basket-driven IR.
        if state.has_basket_templates and identifier in _BASKET_SYNTHETIC_FIELDS:
            return "basket_synthetic", None
        # 6. Previous-bar reference, e.g. close_prev_1, bb_mid_prev_1.
        prev = _PREV_BAR_SUFFIX_RE.match(identifier)
        if prev is not None:
            base = prev.group("base")
            base_kind, base_target = self._lookup_identifier(state, base)
            if base_kind is not None:
                # Record the base as the target_id so downstream
                # consumers can wire the lookback into the right
                # indicator stream.
                target_id_for_prev = (
                    base_target
                    if base_target is not None
                    else (base if base in state.edges_out else None)
                )
                return "previous_bar", target_id_for_prev
        return None, None

    @staticmethod
    def _is_cross_timeframe_ref(state: _ResolverState, identifier: str) -> bool:
        """
        Return True if ``identifier`` looks like ``<price>_<tf>`` where
        ``<price>`` is a declared required field and ``<tf>`` is one of
        the declared confirmation_timeframes (or the primary_timeframe).
        """
        if "_" not in identifier:
            return False
        # Try each split point so timeframes containing underscores
        # (none today, but defensive) still work.
        candidates: Iterable[str] = (
            *state.confirmation_timeframes,
            state.primary_timeframe,
        )
        for tf in candidates:
            suffix = f"_{tf}"
            if identifier.endswith(suffix):
                base = identifier[: -len(suffix)]
                if base in state.price_fields:
                    return True
        return False

    # ---------------------------------------------------------------
    # Topological sort
    # ---------------------------------------------------------------

    @staticmethod
    def _topological_sort(state: _ResolverState) -> list[str]:
        """
        Kahn's algorithm with alphabetical tie-break.

        Args:
            state: resolver state with a fully-built ``edges_out`` map.

        Returns:
            list of node ids in dependency order.

        Raises:
            IRReferenceError: when the graph contains a cycle (Kahn's
                algorithm fails to drain to all nodes).
        """
        # Build in-degree from edges_out: each entry edges_out[a]
        # contains the set of b such that a -> b.
        all_nodes = sorted(state.edges_out.keys())
        in_degree: dict[str, int] = dict.fromkeys(all_nodes, 0)
        for targets in state.edges_out.values():
            for target in targets:
                in_degree[target] += 1

        # Initial frontier: nodes with no inbound edges. Sorted for
        # deterministic output.
        ready: list[str] = sorted(node for node, deg in in_degree.items() if deg == 0)
        order: list[str] = []

        while ready:
            ready.sort()  # alphabetical tie-break each step
            node = ready.pop(0)
            order.append(node)
            for downstream in sorted(state.edges_out[node]):
                in_degree[downstream] -= 1
                if in_degree[downstream] == 0:
                    ready.append(downstream)

        if len(order) != len(all_nodes):
            unresolved = sorted(set(all_nodes) - set(order))
            raise IRReferenceError(
                f"cycle detected in indicator/derived-field dependency "
                f"graph; nodes involved: {unresolved}"
            )
        return order


__all__ = [
    "IRReferenceError",
    "ReferenceResolver",
    "ResolvedReference",
    "ResolvedReferences",
]
