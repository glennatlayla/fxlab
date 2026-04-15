/**
 * Backtest form types for FE-08 Mobile Backtest Setup.
 *
 * Purpose:
 *   Define TypeScript interfaces for backtest form values, configuration,
 *   and time interval constants. These types are shared across the backtest
 *   form component, validation schema, and API submission layer.
 *
 * Responsibilities:
 *   - Define BacktestFormValues interface for form data.
 *   - Define TimeInterval type and constants.
 *   - Export type-safe enums for UI pickers.
 *
 * Does NOT:
 *   - Contain validation logic (see validation.ts).
 *   - Contain rendering or component logic.
 *   - Depend on React or UI frameworks.
 *
 * Dependencies:
 *   - None (pure TypeScript types).
 */

/**
 * Time interval options for candlestick data.
 * Mirrors backend TimeInterval enum from research.py.
 */
export type TimeInterval = "1m" | "5m" | "15m" | "1h" | "4h" | "1d";

/**
 * Form values for the backtest creation form.
 *
 * All fields except optional ones are required for form submission.
 * Dates are stored as YYYY-MM-DD ISO strings for API submission.
 */
export interface BacktestFormValues {
  /** ULID of the selected strategy build. */
  strategy_build_id: string;
  /** Array of trading symbols (e.g., ["AAPL", "MSFT"]). */
  symbols: string[];
  /** Backtest start date as YYYY-MM-DD. */
  start_date: string;
  /** Backtest end date as YYYY-MM-DD. */
  end_date: string;
  /** Candlestick interval for OHLC data. */
  interval: TimeInterval;
  /** Initial equity in dollars. Minimum $100, maximum $10M. */
  initial_equity: number;
  /** Optional commission rate as decimal (0–0.1, default 0). */
  commission_rate?: number;
  /** Optional slippage in basis points (0–100, default 0). */
  slippage_bps?: number;
}

/**
 * Selectable time interval with display label.
 * Used to populate UI picker options.
 */
export interface TimeIntervalOption {
  value: TimeInterval;
  label: string;
}

/**
 * Standard time interval options for the segmented control.
 *
 * Order and labels match UI expectations for the time picker.
 */
export const TIME_INTERVALS: readonly TimeIntervalOption[] = [
  { value: "1m", label: "1m" },
  { value: "5m", label: "5m" },
  { value: "15m", label: "15m" },
  { value: "1h", label: "1h" },
  { value: "4h", label: "4h" },
  { value: "1d", label: "1d" },
] as const;

/**
 * Default backtest form values.
 *
 * Used to initialize form state and reset operations.
 */
export const DEFAULT_BACKTEST_FORM: Partial<BacktestFormValues> = {
  strategy_build_id: "",
  symbols: [],
  interval: "1d",
  initial_equity: 10_000,
  commission_rate: 0,
  slippage_bps: 0,
};

/**
 * Constraints and validation limits.
 *
 * Used in validation schema and form UI (e.g., min/max input hints).
 */
export const BACKTEST_CONSTRAINTS = {
  /** Minimum initial equity in dollars. */
  MIN_INITIAL_EQUITY: 100,
  /** Maximum initial equity in dollars. */
  MAX_INITIAL_EQUITY: 10_000_000,
  /** Maximum commission rate as decimal. */
  MAX_COMMISSION_RATE: 0.1,
  /** Maximum slippage in basis points. */
  MAX_SLIPPAGE_BPS: 100,
  /** Minimum number of symbols required. */
  MIN_SYMBOLS: 1,
} as const;
