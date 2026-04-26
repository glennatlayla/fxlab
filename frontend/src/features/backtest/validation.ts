/**
 * Zod validation schemas for backtest form (FE-08).
 *
 * Purpose:
 *   Provide runtime validation of backtest form values.
 *   Used by forms, API clients, and tests to ensure all data
 *   conforms to backend contract expectations.
 *
 * Responsibilities:
 *   - Define backtestFormSchema for form submissions.
 *   - Validate required fields (strategy, symbols, dates, interval, equity).
 *   - Validate field ranges (equity min/max, commission rate, slippage).
 *   - Cross-field validation (end date > start date).
 *   - Provide detailed error messages per field.
 *
 * Does NOT:
 *   - Contain business logic or UI rendering.
 *   - Manage form state.
 *   - Make API calls.
 *
 * Dependencies:
 *   - zod (validation framework).
 *   - ./types for BACKTEST_CONSTRAINTS and TimeInterval.
 *
 * Example:
 *   const result = backtestFormSchema.safeParse(formValues);
 *   if (!result.success) {
 *     console.error(result.error.flatten());
 *   }
 */

import { z } from "zod";
import { BACKTEST_CONSTRAINTS } from "./types";

/**
 * Zod schema for the complete backtest form.
 *
 * Validates all required and optional fields, including:
 * - Required fields with non-empty constraints.
 * - Numeric ranges for equity, commission, slippage.
 * - Date format and cross-field validation (end > start).
 * - Enum validation for time interval.
 */
export const backtestFormSchema = z
  .object({
    strategy_build_id: z
      .string()
      .min(1, "Strategy selection is required")
      .describe("ULID of selected strategy build"),

    symbols: z
      .array(z.string().trim().toUpperCase())
      .min(
        BACKTEST_CONSTRAINTS.MIN_SYMBOLS,
        `At least ${BACKTEST_CONSTRAINTS.MIN_SYMBOLS} symbol is required`,
      )
      .describe("Array of trading symbols (e.g., AAPL, MSFT)"),

    start_date: z
      .string()
      .regex(/^\d{4}-\d{2}-\d{2}$/, "Start date must be in YYYY-MM-DD format")
      .describe("Backtest start date (inclusive)"),

    end_date: z
      .string()
      .regex(/^\d{4}-\d{2}-\d{2}$/, "End date must be in YYYY-MM-DD format")
      .describe("Backtest end date (inclusive)"),

    interval: z
      .enum(["1m", "5m", "15m", "1h", "4h", "1d"] as const)
      .describe("OHLC candlestick interval"),

    initial_equity: z
      .number()
      .int("Initial equity must be a whole number")
      .min(
        BACKTEST_CONSTRAINTS.MIN_INITIAL_EQUITY,
        `Minimum equity is $${BACKTEST_CONSTRAINTS.MIN_INITIAL_EQUITY}`,
      )
      .max(
        BACKTEST_CONSTRAINTS.MAX_INITIAL_EQUITY,
        `Maximum equity is $${BACKTEST_CONSTRAINTS.MAX_INITIAL_EQUITY.toLocaleString()}`,
      )
      .describe("Starting portfolio value in USD"),

    commission_rate: z
      .number()
      .min(0, "Commission rate must be non-negative")
      .max(
        BACKTEST_CONSTRAINTS.MAX_COMMISSION_RATE,
        `Maximum commission rate is ${(BACKTEST_CONSTRAINTS.MAX_COMMISSION_RATE * 100).toFixed(1)}%`,
      )
      .optional()
      .describe("Optional commission as decimal (0–0.1)"),

    slippage_bps: z
      .number()
      .int("Slippage must be whole basis points")
      .min(0, "Slippage must be non-negative")
      .max(
        BACKTEST_CONSTRAINTS.MAX_SLIPPAGE_BPS,
        `Maximum slippage is ${BACKTEST_CONSTRAINTS.MAX_SLIPPAGE_BPS} bps`,
      )
      .optional()
      .describe("Optional slippage in basis points (0–100)"),
  })
  // Cross-field validation: end_date must be after start_date.
  .refine(
    (data) => {
      const start = new Date(data.start_date);
      const end = new Date(data.end_date);
      return end > start;
    },
    {
      message: "End date must be after start date",
      path: ["end_date"],
    },
  );

/**
 * Inferred TypeScript type from the schema.
 * Used by components and API clients for type safety.
 */
export type BacktestFormData = z.infer<typeof backtestFormSchema>;

/**
 * Helper to validate form values and return structured errors.
 *
 * Args:
 *   values: Form values to validate.
 *
 * Returns:
 *   { success: true, data } on success.
 *   { success: false, errors } on failure (errors flattened by field).
 *
 * Example:
 *   const result = validateBacktestForm(formValues);
 *   if (result.success) {
 *     await submitBacktest(result.data);
 *   } else {
 *     console.error(result.errors); // { strategy_build_id: [...], ... }
 *   }
 */
export function validateBacktestForm(values: unknown) {
  const result = backtestFormSchema.safeParse(values);

  if (result.success) {
    return {
      success: true as const,
      data: result.data,
    };
  }

  return {
    success: false as const,
    errors: result.error.flatten().fieldErrors,
  };
}
