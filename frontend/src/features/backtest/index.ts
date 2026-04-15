/**
 * Public exports for the backtest feature (FE-08).
 *
 * Purpose:
 *   Provide a clean public API for importing backtest components,
 *   types, and utilities from other parts of the application.
 *
 * Responsibilities:
 *   - Export BacktestForm component.
 *   - Export type definitions and validation functions.
 *   - Export API client.
 *
 * Does NOT:
 *   - Contain implementation logic (re-exports only).
 */

// Components
export { BacktestForm } from "./components/BacktestForm";
export type { BacktestFormProps } from "./components/BacktestForm";

// Types
export type {
  BacktestFormValues,
  TimeInterval,
  TimeIntervalOption,
} from "./types";
export {
  TIME_INTERVALS,
  DEFAULT_BACKTEST_FORM,
  BACKTEST_CONSTRAINTS,
} from "./types";

// Validation
export { backtestFormSchema, validateBacktestForm } from "./validation";
export type { BacktestFormData } from "./validation";

// API
export { backtestApi } from "./api";
