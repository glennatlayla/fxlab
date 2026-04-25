/**
 * TypeScript types mirroring `libs/contracts/strategy_ir.py` (the Pydantic
 * schema for the FXLab Strategy IR). These types are read-only structural
 * shapes for UI rendering; they are NOT runtime validators.
 *
 * Responsibilities:
 *   - Provide a typed surface for the IR detail view and any other frontend
 *     component that consumes parsed IR data.
 *   - Mirror the discriminated unions used by the Pydantic schema
 *     (`Indicator`, `ExitStop`) so TypeScript narrows correctly when the
 *     UI branches on a `type` literal.
 *
 * Does NOT:
 *   - Perform validation (the backend Pydantic model is the source of truth).
 *   - Carry behaviour or default-fill logic.
 *
 * Synchronisation rule:
 *   - When `libs/contracts/strategy_ir.py` adds a new model, indicator
 *     variant, or exit-stop wrapper, this file must be updated in the same
 *     change. Failing to keep them aligned will surface as a `tsc --noEmit`
 *     error wherever the new field is referenced in the UI.
 */

// ---------------------------------------------------------------------------
// Common scalar types
// ---------------------------------------------------------------------------

/** A right-hand side may be a numeric literal OR an identifier/expression. */
export type RhsValue = number | string;

// ---------------------------------------------------------------------------
// Metadata
// ---------------------------------------------------------------------------

export interface IrMetadata {
  strategy_name: string;
  strategy_version: string;
  author: string;
  created_utc: string;
  objective: string;
  status: string;
  /** Polymorphic in production: single string, list of strings, or absent. */
  notes?: string | string[] | null;
}

// ---------------------------------------------------------------------------
// Universe
// ---------------------------------------------------------------------------

export interface IrUniverse {
  asset_class: string;
  symbols: string[];
  selection_mode?: string | null;
  direction: string;
}

// ---------------------------------------------------------------------------
// Data requirements
// ---------------------------------------------------------------------------

export interface IrBlockedEntryWindow {
  day: string;
  start_time: string;
  end_time: string;
}

export interface IrSessionRules {
  allowed_entry_days: string[];
  blocked_entry_windows: IrBlockedEntryWindow[];
}

export interface IrDataRequirements {
  primary_timeframe: string;
  confirmation_timeframes: string[];
  required_fields: string[];
  timezone: string;
  session_rules: IrSessionRules;
  warmup_bars: number;
  missing_bar_policy: string;
  calendar_dependencies?: string[] | null;
}

// ---------------------------------------------------------------------------
// Indicators (discriminated union)
// ---------------------------------------------------------------------------

interface IrIndicatorBase {
  id: string;
  timeframe: string;
}

export interface IrEmaIndicator extends IrIndicatorBase {
  type: "ema";
  source: string;
  length: number;
}

export interface IrSmaIndicator extends IrIndicatorBase {
  type: "sma";
  source: string;
  length: number;
}

export interface IrRsiIndicator extends IrIndicatorBase {
  type: "rsi";
  source: string;
  length: number;
}

export interface IrAtrIndicator extends IrIndicatorBase {
  type: "atr";
  length: number;
}

export interface IrAdxIndicator extends IrIndicatorBase {
  type: "adx";
  length: number;
}

export interface IrBollingerUpperIndicator extends IrIndicatorBase {
  type: "bollinger_upper";
  source: string;
  length: number;
  stddev: number;
}

export interface IrBollingerLowerIndicator extends IrIndicatorBase {
  type: "bollinger_lower";
  source: string;
  length: number;
  stddev: number;
}

export interface IrRollingStddevIndicator extends IrIndicatorBase {
  type: "rolling_stddev";
  source: string;
  length_bars: number;
}

export interface IrRollingHighIndicator extends IrIndicatorBase {
  type: "rolling_high";
  source: string;
  length_bars: number;
}

export interface IrRollingLowIndicator extends IrIndicatorBase {
  type: "rolling_low";
  source: string;
  length_bars: number;
}

export interface IrRollingMaxIndicator extends IrIndicatorBase {
  type: "rolling_max";
  source: string;
  length: number;
}

export interface IrRollingMinIndicator extends IrIndicatorBase {
  type: "rolling_min";
  source: string;
  length: number;
}

export interface IrZscoreIndicator extends IrIndicatorBase {
  type: "zscore";
  source: string;
  mean_source: string;
  std_source: string;
}

export interface IrCalendarBusinessDayIndexIndicator extends IrIndicatorBase {
  type: "calendar_business_day_index";
}

export interface IrCalendarDaysToMonthEndIndicator extends IrIndicatorBase {
  type: "calendar_days_to_month_end";
}

export type IrIndicator =
  | IrEmaIndicator
  | IrSmaIndicator
  | IrRsiIndicator
  | IrAtrIndicator
  | IrAdxIndicator
  | IrBollingerUpperIndicator
  | IrBollingerLowerIndicator
  | IrRollingStddevIndicator
  | IrRollingHighIndicator
  | IrRollingLowIndicator
  | IrRollingMaxIndicator
  | IrRollingMinIndicator
  | IrZscoreIndicator
  | IrCalendarBusinessDayIndexIndicator
  | IrCalendarDaysToMonthEndIndicator;

// ---------------------------------------------------------------------------
// Conditions and condition trees
// ---------------------------------------------------------------------------

export interface IrLeafCondition {
  lhs: string;
  operator: string;
  rhs: RhsValue;
  units?: string | null;
}

export interface IrConditionTree {
  op: string;
  conditions: Array<IrConditionTree | IrLeafCondition>;
}

/** Discriminator used at render time to tell a leaf from a nested tree. */
export function isLeafCondition(node: IrConditionTree | IrLeafCondition): node is IrLeafCondition {
  return (node as IrLeafCondition).lhs !== undefined;
}

// ---------------------------------------------------------------------------
// Entry logic
// ---------------------------------------------------------------------------

export interface IrDirectionalEntry {
  logic: IrConditionTree;
  order_type: string;
}

export interface IrBasketLeg {
  symbol: string;
  side: string;
  weight: number;
}

export interface IrBasketTemplate {
  id: string;
  active_when: IrLeafCondition;
  legs: IrBasketLeg[];
}

export interface IrEntryLogic {
  evaluation_timing: string;
  execution_timing: string;
  long?: IrDirectionalEntry | null;
  short?: IrDirectionalEntry | null;
  basket_templates?: IrBasketTemplate[] | null;
  entry_filters?: IrConditionTree | null;
  signal_expiration_bars?: number | null;
}

// ---------------------------------------------------------------------------
// Exit logic — discriminated union per stop wrapper
// ---------------------------------------------------------------------------

export interface IrAtrMultipleStop {
  type: "atr_multiple";
  indicator: string;
  multiple: number;
}

export interface IrBasketAtrMultipleStop {
  type: "basket_atr_multiple";
  indicator: string;
  multiple: number;
}

export interface IrRiskRewardMultipleStop {
  type: "risk_reward_multiple";
  multiple: number;
}

export interface IrOppositeInnerBandTouchStop {
  type: "opposite_inner_band_touch";
}

export interface IrMiddleBandCloseViolationStop {
  type: "middle_band_close_violation";
}

export interface IrChannelExitStop {
  type: "channel_exit";
  long_condition: IrLeafCondition;
  short_condition: IrLeafCondition;
}

export interface IrMeanReversionToMidStop {
  type: "mean_reversion_to_mid";
  long_condition: IrLeafCondition;
  short_condition: IrLeafCondition;
}

export interface IrCalendarExitStop {
  type: "calendar_exit";
  condition: IrLeafCondition;
}

export interface IrBasketOpenLossPctStop {
  type: "basket_open_loss_pct";
  threshold_pct: number;
}

export interface IrZscoreStop {
  type: "zscore_stop";
  condition: IrLeafCondition;
}

export type IrExitStop =
  | IrAtrMultipleStop
  | IrBasketAtrMultipleStop
  | IrRiskRewardMultipleStop
  | IrOppositeInnerBandTouchStop
  | IrMiddleBandCloseViolationStop
  | IrChannelExitStop
  | IrMeanReversionToMidStop
  | IrCalendarExitStop
  | IrBasketOpenLossPctStop
  | IrZscoreStop;

export interface IrBreakEvenRule {
  enabled: boolean;
  trigger_r_multiple: number;
  offset_pips: number;
}

export interface IrTimeExitRule {
  enabled: boolean;
  max_bars_in_trade: number;
}

export interface IrTrailingStopRule {
  enabled: boolean;
  type: string;
}

export interface IrFridayCloseExitRule {
  enabled: boolean;
  close_time: string;
  timezone: string;
}

export interface IrSessionCloseExitRule {
  enabled: boolean;
  friday_close_time: string;
  timezone: string;
}

export interface IrExitLogic {
  primary_exit?: IrExitStop | null;
  initial_stop?: IrExitStop | null;
  take_profit?: IrExitStop | null;
  trailing_exit?: IrExitStop | null;
  catastrophic_zscore_stop?: IrExitStop | null;
  scheduled_exit?: IrExitStop | null;
  equity_stop?: IrExitStop | null;
  trailing_stop?: IrTrailingStopRule | null;
  break_even?: IrBreakEvenRule | null;
  time_exit?: IrTimeExitRule | null;
  max_bars_in_trade?: number | null;
  friday_close_exit?: IrFridayCloseExitRule | null;
  session_close_exit?: IrSessionCloseExitRule | null;
  same_bar_priority: string[];
}

// ---------------------------------------------------------------------------
// Risk model
// ---------------------------------------------------------------------------

export interface IrPositionSizing {
  method: string;
  risk_pct_of_equity: number;
  stop_distance_source?: string | null;
  allocation_mode?: string | null;
}

export interface IrRiskModel {
  position_sizing: IrPositionSizing;
  max_open_positions?: number | null;
  max_positions_per_symbol?: number | null;
  max_open_baskets?: number | null;
  gross_exposure_cap_pct_of_equity?: number | null;
  daily_loss_limit_pct: number;
  max_drawdown_halt_pct: number;
  pyramiding: boolean;
}

// ---------------------------------------------------------------------------
// Execution model
// ---------------------------------------------------------------------------

export interface IrExecutionModel {
  fill_model: string;
  slippage_model_ref: string;
  spread_model_ref: string;
  commission_model_ref: string;
  swap_model_ref: string;
  partial_fill_policy: string;
  reject_policy: string;
}

// ---------------------------------------------------------------------------
// Filters
// ---------------------------------------------------------------------------

export interface IrFilter {
  id: string;
  type?: string | null;
  lhs?: string | null;
  operator?: string | null;
  rhs?: RhsValue | null;
  units?: string | null;
  day?: string | null;
  time?: string | null;
  timezone?: string | null;
  month?: number | null;
  business_day_start?: number | null;
  business_day_end?: number | null;
  unit?: string | null;
}

// ---------------------------------------------------------------------------
// Derived fields
// ---------------------------------------------------------------------------

export interface IrDerivedField {
  id: string;
  formula: string;
}

// ---------------------------------------------------------------------------
// Ambiguities and defaults — author-supplied free-form documentation.
// Justified `unknown` rather than `any`: keys vary per author and the UI
// only displays values; treating values as `unknown` forces the renderer to
// stringify defensively rather than silently misuse a typed shape.
// ---------------------------------------------------------------------------

export type IrAmbiguitiesAndDefaults = Record<string, unknown>;

// ---------------------------------------------------------------------------
// Root model
// ---------------------------------------------------------------------------

export interface StrategyIR {
  schema_version: "0.1-inferred";
  artifact_type: "strategy_ir";
  metadata: IrMetadata;
  universe: IrUniverse;
  data_requirements: IrDataRequirements;
  indicators: IrIndicator[];
  entry_logic: IrEntryLogic;
  exit_logic: IrExitLogic;
  risk_model: IrRiskModel;
  execution_model: IrExecutionModel;
  filters?: IrFilter[] | null;
  derived_fields?: IrDerivedField[] | null;
  ambiguities_and_defaults?: IrAmbiguitiesAndDefaults | null;
}
