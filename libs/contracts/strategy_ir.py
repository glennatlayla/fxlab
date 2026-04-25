"""
Pydantic schema for the FXLab Strategy IR (Intermediate Representation).

Purpose:
    Parse and validate every ``strategy_ir.json`` artifact in the
    ``Strategy Repo/`` so downstream tracks (parser, compiler, engine)
    can rely on a typed, immutable representation rather than raw dict
    access. This module is the schema-only layer — no business logic,
    no I/O, no compiler concerns. Parsing of files from disk and
    cross-reference resolution are M1.A2/M1.A3 concerns.

Responsibilities:
    - Define the root :class:`StrategyIR` model and every nested model
      that appears in any production IR file or the canonical example.
    - Express discriminated unions over ``Indicator`` (15 types) and
      every wrapper around an exit-logic stop (``initial_stop``,
      ``take_profit``, ``trailing_*``, etc.).
    - Pin ``schema_version`` to ``"0.1-inferred"`` and ``artifact_type``
      to ``"strategy_ir"`` (per workplan M1.A1 acceptance criterion).
    - Mark every model frozen + ``extra='forbid'`` so any new IR field
      lands as a loud ValidationError rather than silent loss.

Does NOT:
    - Read files from disk (parser layer — M1.A2).
    - Resolve indicator references between blocks (resolver — M1.A2).
    - Translate IR into runtime evaluators (compiler — M1.A3).
    - Contain FX-specific or broker-specific behaviour.

Dependencies:
    - Pydantic v2 only.

Schema reference:
    - ``User Spec/Algo Specfication and Examples/strategy_ir.example.json``
    - The five production IRs under ``Strategy Repo/``.

Example::

    import json
    from libs.contracts.strategy_ir import StrategyIR

    with open("FX_DoubleBollinger_TrendZone.strategy_ir.json") as fh:
        ir = StrategyIR.model_validate(json.load(fh))

    assert ir.metadata.strategy_name == "FX_DoubleBollinger_TrendZone"
    for indicator in ir.indicators:
        ...
"""

from __future__ import annotations

from typing import Annotated, Any, Literal, Union

from pydantic import BaseModel, ConfigDict, Field

# ---------------------------------------------------------------------------
# Common scalar types
# ---------------------------------------------------------------------------

#: A condition's left-hand side is always an identifier-or-expression
#: string (e.g. ``"close"``, ``"ema_fast"``, ``"abs(price_zscore)"``).
LhsExpr = str

#: A condition's right-hand side may be a numeric literal OR an
#: identifier / expression string (e.g. ``"ema_100 * 0.985"``).
RhsValue = Union[float, int, str]


# ---------------------------------------------------------------------------
# Reusable strict-frozen model base
# ---------------------------------------------------------------------------


class _StrictFrozenModel(BaseModel):
    """
    Internal base providing the project-wide strict immutability config.

    Every IR model inherits from this so we never have to remember to
    repeat ``model_config = ConfigDict(extra='forbid', frozen=True)`` —
    forgetting it on even one nested model would silently allow extra
    fields and mutation, defeating the schema's whole job.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)


# ---------------------------------------------------------------------------
# Metadata
# ---------------------------------------------------------------------------


class Metadata(_StrictFrozenModel):
    """
    Strategy provenance and bookkeeping fields.

    The ``notes`` field is intentionally polymorphic: the canonical
    example uses a single string, but the OpenAI-authored production
    IRs all use a list of strings. Both shapes are accepted as-is — the
    rest of the system reads ``notes`` for display only.
    """

    strategy_name: str = Field(..., min_length=1, max_length=256)
    strategy_version: str = Field(..., min_length=1, max_length=64)
    author: str = Field(..., min_length=1, max_length=256)
    created_utc: str = Field(..., min_length=1, max_length=64)
    objective: str = Field(..., min_length=1)
    status: str = Field(..., min_length=1, max_length=64)
    notes: Union[str, list[str], None] = None


# ---------------------------------------------------------------------------
# Universe
# ---------------------------------------------------------------------------


class Universe(_StrictFrozenModel):
    """
    Tradable universe and direction policy.

    ``selection_mode`` is optional because the example and the Lien-pack
    IRs omit it (defaulting to a single-asset / per-symbol model);
    ``fixed_basket`` and ``independent_symbols`` appear in the Chan
    pack. ``direction`` of ``basket_rules`` is the basket-template
    indicator that long/short blocks will be absent.
    """

    asset_class: str = Field(..., min_length=1, max_length=64)
    symbols: list[str] = Field(..., min_length=1)
    selection_mode: str | None = Field(default=None, max_length=64)
    direction: str = Field(..., min_length=1, max_length=64)


# ---------------------------------------------------------------------------
# Data requirements
# ---------------------------------------------------------------------------


class BlockedEntryWindow(_StrictFrozenModel):
    """
    A weekday + clock-time window during which entries are forbidden.

    The data is read by the engine's session gate. We accept HH:MM
    strings rather than parsing to ``datetime.time`` because the IR
    is timezone-aware via the ``timezone`` field on
    :class:`SessionRules` — keeping these as strings avoids implicit
    timezone coupling at the schema layer.
    """

    day: str = Field(..., min_length=1, max_length=16)
    start_time: str = Field(..., min_length=1, max_length=8)
    end_time: str = Field(..., min_length=1, max_length=8)


class SessionRules(_StrictFrozenModel):
    """
    Session-level entry rules: allowed weekdays + blocked windows.
    """

    allowed_entry_days: list[str] = Field(default_factory=list)
    blocked_entry_windows: list[BlockedEntryWindow] = Field(default_factory=list)


class DataRequirements(_StrictFrozenModel):
    """
    Bar feed, timezone, warm-up and missing-data policy.

    ``confirmation_timeframes`` and ``calendar_dependencies`` are
    optional — only some strategies declare them.
    """

    primary_timeframe: str = Field(..., min_length=1, max_length=16)
    confirmation_timeframes: list[str] = Field(default_factory=list)
    required_fields: list[str] = Field(..., min_length=1)
    timezone: str = Field(..., min_length=1, max_length=64)
    session_rules: SessionRules
    warmup_bars: int = Field(..., ge=0, le=100_000)
    missing_bar_policy: str = Field(..., min_length=1, max_length=128)
    calendar_dependencies: list[str] | None = None


# ---------------------------------------------------------------------------
# Indicators (discriminated union)
# ---------------------------------------------------------------------------


class _IndicatorBase(_StrictFrozenModel):
    """
    Shared fields every indicator carries: id and timeframe.

    Concrete subclasses pin ``type`` to a literal so the union below can
    discriminate at parse time. Each subclass declares the additional
    fields it needs (``length``, ``stddev``, ``source``, …).
    """

    id: str = Field(..., min_length=1, max_length=128)
    timeframe: str = Field(..., min_length=1, max_length=16)


class _LengthBarsMixin(_StrictFrozenModel):
    """
    Mixin for indicators that use ``length_bars`` rather than ``length``.

    The two field names are NOT interchangeable in the production IRs —
    e.g. ``rolling_high`` uses ``length_bars`` while ``sma`` uses
    ``length``. Faithfully preserving the source field name avoids
    silent rewrites during round-trip.
    """


class EmaIndicator(_IndicatorBase):
    """Exponential moving average over a price source."""

    type: Literal["ema"]
    source: str = Field(..., min_length=1, max_length=32)
    length: int = Field(..., ge=1, le=100_000)


class SmaIndicator(_IndicatorBase):
    """Simple moving average over a price source."""

    type: Literal["sma"]
    source: str = Field(..., min_length=1, max_length=32)
    length: int = Field(..., ge=1, le=100_000)


class RsiIndicator(_IndicatorBase):
    """Relative strength index over a price source."""

    type: Literal["rsi"]
    source: str = Field(..., min_length=1, max_length=32)
    length: int = Field(..., ge=1, le=100_000)


class AtrIndicator(_IndicatorBase):
    """Average true range; consumes OHLC implicitly, no source field."""

    type: Literal["atr"]
    length: int = Field(..., ge=1, le=100_000)


class AdxIndicator(_IndicatorBase):
    """Average directional index; consumes OHLC implicitly."""

    type: Literal["adx"]
    length: int = Field(..., ge=1, le=100_000)


class BollingerUpperIndicator(_IndicatorBase):
    """Upper Bollinger band at ``stddev`` standard deviations."""

    type: Literal["bollinger_upper"]
    source: str = Field(..., min_length=1, max_length=32)
    length: int = Field(..., ge=1, le=100_000)
    stddev: float = Field(..., gt=0)


class BollingerLowerIndicator(_IndicatorBase):
    """Lower Bollinger band at ``stddev`` standard deviations."""

    type: Literal["bollinger_lower"]
    source: str = Field(..., min_length=1, max_length=32)
    length: int = Field(..., ge=1, le=100_000)
    stddev: float = Field(..., gt=0)


class RollingStddevIndicator(_IndicatorBase):
    """Rolling sample standard deviation over ``length_bars``."""

    type: Literal["rolling_stddev"]
    source: str = Field(..., min_length=1, max_length=32)
    length_bars: int = Field(..., ge=1, le=100_000)


class RollingHighIndicator(_IndicatorBase):
    """Rolling maximum (Donchian-style) over ``length_bars``."""

    type: Literal["rolling_high"]
    source: str = Field(..., min_length=1, max_length=32)
    length_bars: int = Field(..., ge=1, le=100_000)


class RollingLowIndicator(_IndicatorBase):
    """Rolling minimum (Donchian-style) over ``length_bars``."""

    type: Literal["rolling_low"]
    source: str = Field(..., min_length=1, max_length=32)
    length_bars: int = Field(..., ge=1, le=100_000)


class RollingMaxIndicator(_IndicatorBase):
    """Rolling maximum over ``length`` (not ``length_bars`` — see Lien MTF IR)."""

    type: Literal["rolling_max"]
    source: str = Field(..., min_length=1, max_length=32)
    length: int = Field(..., ge=1, le=100_000)


class RollingMinIndicator(_IndicatorBase):
    """Rolling minimum over ``length``."""

    type: Literal["rolling_min"]
    source: str = Field(..., min_length=1, max_length=32)
    length: int = Field(..., ge=1, le=100_000)


class ZscoreIndicator(_IndicatorBase):
    """
    Standardised z-score of ``source`` against an external mean / stddev.

    Both ``mean_source`` and ``std_source`` reference the ``id`` of
    another indicator (e.g. ``bb_mid`` and ``bb_std``); the resolver
    layer (M1.A2) is responsible for verifying those IDs exist.
    """

    type: Literal["zscore"]
    source: str = Field(..., min_length=1, max_length=32)
    mean_source: str = Field(..., min_length=1, max_length=128)
    std_source: str = Field(..., min_length=1, max_length=128)


class CalendarBusinessDayIndexIndicator(_IndicatorBase):
    """1-based business-day index of the current bar within its month."""

    type: Literal["calendar_business_day_index"]


class CalendarDaysToMonthEndIndicator(_IndicatorBase):
    """Business days remaining until month-end."""

    type: Literal["calendar_days_to_month_end"]


#: Discriminated union over every indicator shape we have ever seen
#: in a strategy_ir.json. Adding a new indicator type means adding a
#: new model AND extending this union — there is no fallback branch on
#: purpose, so an unknown ``type`` raises ValidationError loudly.
Indicator = Annotated[
    Union[
        EmaIndicator,
        SmaIndicator,
        RsiIndicator,
        AtrIndicator,
        AdxIndicator,
        BollingerUpperIndicator,
        BollingerLowerIndicator,
        RollingStddevIndicator,
        RollingHighIndicator,
        RollingLowIndicator,
        RollingMaxIndicator,
        RollingMinIndicator,
        ZscoreIndicator,
        CalendarBusinessDayIndexIndicator,
        CalendarDaysToMonthEndIndicator,
    ],
    Field(discriminator="type"),
]


# ---------------------------------------------------------------------------
# Conditions and condition trees
# ---------------------------------------------------------------------------


class LeafCondition(_StrictFrozenModel):
    """
    A single comparison: ``lhs OP rhs`` with optional ``units`` tag.

    ``lhs`` is always an identifier or expression string. ``rhs`` may be
    a numeric literal (e.g. ``2.0``) or another identifier / expression
    string (e.g. ``"ema_100 * 0.985"``). ``units`` (e.g. ``"pips"``,
    ``"price"``) is purely informational at this layer; the compiler
    decides what to do with it.
    """

    lhs: LhsExpr = Field(..., min_length=1)
    operator: str = Field(..., min_length=1, max_length=4)
    rhs: RhsValue
    units: str | None = Field(default=None, max_length=32)


class ConditionTree(_StrictFrozenModel):
    """
    A boolean combinator over leaf conditions.

    Production IRs only ever use ``op == "and"`` with a flat list of
    leaf conditions, but we accept the general shape so a future IR can
    nest trees without a schema change. ``conditions`` may contain
    either leaves or nested trees.
    """

    op: str = Field(..., min_length=1, max_length=8)
    conditions: list[Union[ConditionTree, LeafCondition]] = Field(..., min_length=1)


# ---------------------------------------------------------------------------
# Entry logic
# ---------------------------------------------------------------------------


class DirectionalEntry(_StrictFrozenModel):
    """
    Long-or-short side entry: a condition tree plus an order type.
    """

    logic: ConditionTree
    order_type: str = Field(..., min_length=1, max_length=32)


class BasketLeg(_StrictFrozenModel):
    """
    One leg of a basket entry: symbol, side, and weight.
    """

    symbol: str = Field(..., min_length=1, max_length=32)
    side: str = Field(..., min_length=1, max_length=8)
    weight: float = Field(..., ge=0)


class BasketTemplate(_StrictFrozenModel):
    """
    A named basket trigger: when ``active_when`` evaluates true, the
    engine opens every leg simultaneously.
    """

    id: str = Field(..., min_length=1, max_length=128)
    active_when: LeafCondition
    legs: list[BasketLeg] = Field(..., min_length=1)


class EntryLogic(_StrictFrozenModel):
    """
    Entry rules: directional (long/short) AND/OR basket-based.

    Every production IR uses one of two shapes: per-direction
    (``long`` + ``short`` blocks, used by 4 of 5 IRs) or basket-driven
    (``basket_templates`` + ``entry_filters``, used by the
    Turn-of-Month strategy). Both shapes coexist as optional fields so
    a single :class:`EntryLogic` model covers every IR variant. The
    compiler is expected to pick the populated branch.
    """

    evaluation_timing: str = Field(..., min_length=1, max_length=64)
    execution_timing: str = Field(..., min_length=1, max_length=64)
    long: DirectionalEntry | None = None
    short: DirectionalEntry | None = None
    basket_templates: list[BasketTemplate] | None = None
    entry_filters: ConditionTree | None = None
    signal_expiration_bars: int | None = Field(default=None, ge=0, le=10_000)


# ---------------------------------------------------------------------------
# Exit logic — discriminated union per stop wrapper
# ---------------------------------------------------------------------------


class AtrMultipleStop(_StrictFrozenModel):
    """Initial stop expressed as N × an ATR indicator."""

    type: Literal["atr_multiple"]
    indicator: str = Field(..., min_length=1, max_length=128)
    multiple: float = Field(..., gt=0)


class BasketAtrMultipleStop(_StrictFrozenModel):
    """Basket-level initial stop expressed as N × ATR (basket variant)."""

    type: Literal["basket_atr_multiple"]
    indicator: str = Field(..., min_length=1, max_length=128)
    multiple: float = Field(..., gt=0)


class RiskRewardMultipleStop(_StrictFrozenModel):
    """Take-profit at N × the initial stop distance."""

    type: Literal["risk_reward_multiple"]
    multiple: float = Field(..., gt=0)


class OppositeInnerBandTouchStop(_StrictFrozenModel):
    """Take-profit on touching the opposite inner Bollinger band."""

    type: Literal["opposite_inner_band_touch"]


class MiddleBandCloseViolationStop(_StrictFrozenModel):
    """Trailing stop on a close beyond the Bollinger middle band."""

    type: Literal["middle_band_close_violation"]


class ChannelExitStop(_StrictFrozenModel):
    """Donchian-style trailing exit; direction-specific conditions."""

    type: Literal["channel_exit"]
    long_condition: LeafCondition
    short_condition: LeafCondition


class MeanReversionToMidStop(_StrictFrozenModel):
    """Exit on close crossing back through the Bollinger middle band."""

    type: Literal["mean_reversion_to_mid"]
    long_condition: LeafCondition
    short_condition: LeafCondition


class CalendarExitStop(_StrictFrozenModel):
    """Calendar-driven exit (e.g. business day index ≥ N)."""

    type: Literal["calendar_exit"]
    condition: LeafCondition


class BasketOpenLossPctStop(_StrictFrozenModel):
    """Basket-level equity stop expressed as % of open loss."""

    type: Literal["basket_open_loss_pct"]
    threshold_pct: float = Field(..., gt=0)


class ZscoreStop(_StrictFrozenModel):
    """Catastrophic z-score stop with explicit condition leaf."""

    type: Literal["zscore_stop"]
    condition: LeafCondition


#: Discriminated union over every exit-logic stop wrapper. Like
#: :data:`Indicator`, an unknown ``type`` raises ValidationError.
ExitStop = Annotated[
    Union[
        AtrMultipleStop,
        BasketAtrMultipleStop,
        RiskRewardMultipleStop,
        OppositeInnerBandTouchStop,
        MiddleBandCloseViolationStop,
        ChannelExitStop,
        MeanReversionToMidStop,
        CalendarExitStop,
        BasketOpenLossPctStop,
        ZscoreStop,
    ],
    Field(discriminator="type"),
]


class BreakEvenRule(_StrictFrozenModel):
    """Move stop to break-even once R-multiple trigger is hit."""

    enabled: bool
    trigger_r_multiple: float = Field(..., gt=0)
    offset_pips: float = Field(..., ge=0)


class TimeExitRule(_StrictFrozenModel):
    """Force exit after N bars in the trade."""

    enabled: bool
    max_bars_in_trade: int = Field(..., ge=1, le=100_000)


class TrailingStopRule(_StrictFrozenModel):
    """Wraps an :data:`ExitStop` discriminated subtype with an enabled flag."""

    enabled: bool
    type: str = Field(..., min_length=1, max_length=64)


class FridayCloseExitRule(_StrictFrozenModel):
    """Force exit before Friday market close in the given timezone."""

    enabled: bool
    close_time: str = Field(..., min_length=1, max_length=8)
    timezone: str = Field(..., min_length=1, max_length=64)


class SessionCloseExitRule(_StrictFrozenModel):
    """Pre-Friday-close exit using the example IR's ``friday_close_time`` shape."""

    enabled: bool
    friday_close_time: str = Field(..., min_length=1, max_length=8)
    timezone: str = Field(..., min_length=1, max_length=64)


class ExitLogic(_StrictFrozenModel):
    """
    Exit ruleset: stops, take-profits, trailing exits, time/calendar exits.

    Every wrapper is optional — different strategies populate different
    subsets. ``same_bar_priority`` is a pure ordering hint; the
    compiler resolves it at compile time per the M1.A3 hard constraint.

    ``max_bars_in_trade`` appears at the top level in the example and
    Lien IRs (a raw int), but as a nested ``time_exit`` block in the
    Chan IRs. We model both.
    """

    primary_exit: ExitStop | None = None
    initial_stop: ExitStop | None = None
    take_profit: ExitStop | None = None
    trailing_exit: ExitStop | None = None
    catastrophic_zscore_stop: ExitStop | None = None
    scheduled_exit: ExitStop | None = None
    equity_stop: ExitStop | None = None
    trailing_stop: TrailingStopRule | None = None
    break_even: BreakEvenRule | None = None
    time_exit: TimeExitRule | None = None
    max_bars_in_trade: int | None = Field(default=None, ge=1, le=100_000)
    friday_close_exit: FridayCloseExitRule | None = None
    session_close_exit: SessionCloseExitRule | None = None
    same_bar_priority: list[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# Risk model
# ---------------------------------------------------------------------------


class PositionSizing(_StrictFrozenModel):
    """
    Position-sizing parameters.

    ``method`` covers ``fixed_fractional_risk`` (the common case) and
    ``fixed_basket_risk`` (Turn-of-Month). ``stop_distance_source``
    appears only when sizing depends on a specific stop wrapper.
    """

    method: str = Field(..., min_length=1, max_length=64)
    risk_pct_of_equity: float = Field(..., gt=0)
    stop_distance_source: str | None = Field(default=None, max_length=64)
    allocation_mode: str | None = Field(default=None, max_length=64)


class RiskModel(_StrictFrozenModel):
    """
    Account-level risk gates and sizing config.

    ``max_open_positions`` and ``max_open_baskets`` are mutually
    exclusive in practice, but both are optional here so per-strategy
    + per-basket risk shapes can coexist in the same model.
    """

    position_sizing: PositionSizing
    max_open_positions: int | None = Field(default=None, ge=0, le=10_000)
    max_positions_per_symbol: int | None = Field(default=None, ge=0, le=10_000)
    max_open_baskets: int | None = Field(default=None, ge=0, le=10_000)
    gross_exposure_cap_pct_of_equity: float | None = Field(default=None, ge=0)
    daily_loss_limit_pct: float = Field(..., gt=0)
    max_drawdown_halt_pct: float = Field(..., gt=0)
    pyramiding: bool


# ---------------------------------------------------------------------------
# Execution model
# ---------------------------------------------------------------------------


class ExecutionModel(_StrictFrozenModel):
    """
    Engine-level execution policy: fill, slippage, spread, commissions,
    swaps, partial-fill and reject handling.
    """

    fill_model: str = Field(..., min_length=1, max_length=64)
    slippage_model_ref: str = Field(..., min_length=1, max_length=128)
    spread_model_ref: str = Field(..., min_length=1, max_length=128)
    commission_model_ref: str = Field(..., min_length=1, max_length=128)
    swap_model_ref: str = Field(..., min_length=1, max_length=128)
    partial_fill_policy: str = Field(..., min_length=1, max_length=128)
    reject_policy: str = Field(..., min_length=1, max_length=128)


# ---------------------------------------------------------------------------
# Filters
# ---------------------------------------------------------------------------


class Filter(_StrictFrozenModel):
    """
    Heterogeneous engine filter.

    Filters in the production IRs come in two broad shapes: comparison
    filters (``lhs``/``operator``/``rhs``/``units``) and named-rule
    filters (``type`` plus rule-specific knobs like ``day``, ``time``,
    ``month``, ``business_day_start``). Rather than fragment this into
    a discriminated union, we model the union of all observed fields
    with sensible optionality. The compiler/runtime layer interprets
    each filter according to which fields are populated.

    Adding a new filter shape to a future IR will require extending the
    optional-field set here — that is the intended pressure point so
    schema evolution stays explicit.
    """

    id: str = Field(..., min_length=1, max_length=128)
    type: str | None = Field(default=None, max_length=128)
    lhs: str | None = Field(default=None, max_length=128)
    operator: str | None = Field(default=None, max_length=4)
    rhs: RhsValue | None = None
    units: str | None = Field(default=None, max_length=32)
    day: str | None = Field(default=None, max_length=16)
    time: str | None = Field(default=None, max_length=8)
    timezone: str | None = Field(default=None, max_length=64)
    month: int | None = Field(default=None, ge=1, le=12)
    business_day_start: int | None = Field(default=None, ge=-31, le=31)
    business_day_end: int | None = Field(default=None, ge=-31, le=31)
    unit: str | None = Field(default=None, max_length=128)


# ---------------------------------------------------------------------------
# Derived fields (top-level)
# ---------------------------------------------------------------------------


class DerivedField(_StrictFrozenModel):
    """
    A named formula computed from other indicator IDs.

    The formula is a free-form string (e.g. a Fibonacci retracement
    expression). The resolver/compiler is responsible for parsing it.
    """

    id: str = Field(..., min_length=1, max_length=128)
    formula: str = Field(..., min_length=1)


# ---------------------------------------------------------------------------
# Ambiguities and defaults — modelled as a free-form dict, not a class
# ---------------------------------------------------------------------------
#
# The IR's ``ambiguities_and_defaults`` block is author-supplied
# documentation: keys vary per author (``reference_mean_choice``,
# ``trend_blocker_choice``, ``breakout_reference_rule``, etc.) and the
# engine never consumes it. Modelling it as a Pydantic class with
# ``extra='forbid'`` would force a schema bump every time an author adds
# a new explanatory key — defeating its purpose. Modelling it with
# ``extra='allow'`` would violate the project-wide strict-frozen rule.
#
# Resolution: treat it as a typed ``dict[str, Any]`` on the root model.
# Every value is preserved verbatim (string, list of strings, nested
# dict — whatever the author wrote) and the rest of the system reads it
# only for display.

# ---------------------------------------------------------------------------
# Root model
# ---------------------------------------------------------------------------


class StrategyIR(_StrictFrozenModel):
    """
    Root strategy IR model.

    Pins ``schema_version`` to the only currently-supported value
    (``"0.1-inferred"``) and ``artifact_type`` to ``"strategy_ir"``.
    Bumping either literal is a deliberate schema event — when we
    promote past 0.1-inferred we add the new value here and update
    every downstream consumer in the same change.

    Every section is required EXCEPT ``filters``, ``derived_fields``,
    and ``ambiguities_and_defaults`` — those vary across the production
    set and absence is legitimate.
    """

    schema_version: Literal["0.1-inferred"]
    artifact_type: Literal["strategy_ir"]
    metadata: Metadata
    universe: Universe
    data_requirements: DataRequirements
    indicators: list[Indicator] = Field(..., min_length=1)
    entry_logic: EntryLogic
    exit_logic: ExitLogic
    risk_model: RiskModel
    execution_model: ExecutionModel
    filters: list[Filter] | None = None
    derived_fields: list[DerivedField] | None = None
    ambiguities_and_defaults: dict[str, Any] | None = None


# Resolve forward references in :class:`ConditionTree` (self-referential).
ConditionTree.model_rebuild()
