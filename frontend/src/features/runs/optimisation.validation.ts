/**
 * Zod validation schema for optimisation forms (FE-15).
 *
 * Purpose:
 * - Define runtime validation for optimisation form values
 * - Provide clear error messages for form fields
 * - Enforce constraints per spec (trial count limits, parameter ranges, etc.)
 * - Support progressive validation (field-level and form-level)
 *
 * Responsibilities:
 * - Zod schema definitions for all form types
 * - Custom validation rules (trial count, date ranges, etc.)
 * - Error message formatting
 *
 * Does NOT:
 * - Contain business logic
 * - Perform I/O or API calls
 * - Know about React Hook Form internals
 *
 * Dependencies:
 * - zod for schema definition
 * - optimisation.ts for domain types
 *
 * Example:
 *   const formValues = { ... };
 *   const result = optimizationFormSchema.safeParse(formValues);
 *   if (!result.success) {
 *     console.log(result.error.flatten().fieldErrors);
 *   }
 */

import { z } from "zod";
import { estimateTrialCount } from "./optimisation";
import type { OptimizationMetric } from "./optimisation";

/**
 * Maximum allowed trial count (hard limit).
 *
 * Set conservatively to prevent runaway optimization searches
 * that could timeout or exhaust resources.
 */
export const MAX_TRIAL_COUNT = 100000;

/**
 * Hard limit on parameter count per form.
 *
 * Prevents UI performance issues with very large parameter grids.
 */
export const MAX_PARAMETERS = 10;

/**
 * Valid bar intervals for backtest.
 *
 * Must match backend BacktestInterval enum.
 */
export const VALID_INTERVALS = ["1m", "5m", "15m", "30m", "1h", "4h", "1d", "1w", "1mo"] as const;

export type ValidInterval = (typeof VALID_INTERVALS)[number];

/**
 * Valid optimization metrics.
 *
 * Must match backend WalkForwardConfig.optimization_metric enum.
 */
export const VALID_METRICS = [
  "sharpe_ratio",
  "total_return",
  "max_drawdown",
  "win_rate",
  "profit_factor",
] as const;

export type ValidMetric = (typeof VALID_METRICS)[number];

/**
 * Schema for a single parameter range entry.
 *
 * Validates:
 * - name is non-empty string
 * - min and max are positive numbers
 * - min < max
 * - step > 0
 */
const parameterRangeSchema = z.object({
  name: z.string().min(1, "Parameter name required"),
  min: z.number().finite("Min must be a valid number"),
  max: z.number().finite("Max must be a valid number"),
  step: z.number().gt(0, "Step must be greater than zero"),
});

/**
 * Schema for backtest form values (shared between backtest and optimization).
 *
 * Validates:
 * - strategy_build_id is non-empty ULID-like string
 * - symbols is non-empty array of uppercase ticker symbols
 * - start_date and end_date are valid ISO dates with start < end
 * - interval is one of the valid backtest intervals
 * - initial_equity is positive number
 */
const backtestFormSchema = z.object({
  strategy_build_id: z.string().min(1, "Strategy required"),
  symbols: z
    .array(z.string().min(1))
    .min(1, "At least one symbol required")
    .transform((symbols) => symbols.map((s) => s.trim().toUpperCase()).filter(Boolean)),
  start_date: z.string().date("Start date must be YYYY-MM-DD"),
  end_date: z.string().date("End date must be YYYY-MM-DD"),
  interval: z.enum(VALID_INTERVALS as readonly [ValidInterval, ...ValidInterval[]], {
    message: `Interval must be one of: ${VALID_INTERVALS.join(", ")}`,
  }),
  initial_equity: z.number().gt(0, "Initial equity must be greater than zero"),
});

/**
 * Refine backtest schema to validate date constraints.
 *
 * Ensures start_date < end_date after both are parsed.
 */
const backtestWithDateConstraints = backtestFormSchema.refine(
  (data) => data.start_date < data.end_date,
  {
    message: "Start date must be before end date",
    path: ["start_date"],
  },
);

/**
 * Schema for optimization form values.
 *
 * Extends backtest schema with:
 * - optimization_metric selection
 * - parameters array (at least one, at most MAX_PARAMETERS)
 * - optional walk-forward settings
 * - optional monte carlo settings
 * - trial count validation (< MAX_TRIAL_COUNT)
 */
const optimizationBaseSchema = backtestWithDateConstraints.extend({
  optimization_metric: z.enum(VALID_METRICS as readonly [ValidMetric, ...ValidMetric[]], {
    message: "Invalid optimization metric",
  }),
  parameters: z
    .array(parameterRangeSchema)
    .min(1, "At least one parameter required")
    .max(MAX_PARAMETERS, `Maximum ${MAX_PARAMETERS} parameters allowed`),
  walk_forward_windows: z
    .number()
    .int("Windows must be an integer")
    .min(2, "Windows must be at least 2")
    .max(20, "Windows must be at most 20")
    .optional(),
  walk_forward_train_pct: z
    .number()
    .min(50, "Train percentage must be at least 50%")
    .max(90, "Train percentage must be at most 90%")
    .optional(),
  monte_carlo_runs: z
    .number()
    .int("Monte Carlo runs must be an integer")
    .min(100, "Monte Carlo runs must be at least 100")
    .optional(),
});

/**
 * Refine optimization schema to validate parameter constraints.
 *
 * Validates:
 * - All parameters satisfy min < max constraint
 * - Total trial count < MAX_TRIAL_COUNT
 * - If walk-forward is enabled, both windows and train_pct must be set
 */
export const optimizationFormSchema = optimizationBaseSchema
  .refine(
    (data) => {
      // Validate each parameter's min < max
      return data.parameters.every((p) => p.min < p.max);
    },
    {
      message: "Min must be less than max for all parameters",
      path: ["parameters"],
    },
  )
  .refine(
    (data) => {
      // Validate trial count limit
      const count = estimateTrialCount(data.parameters);
      return count < MAX_TRIAL_COUNT;
    },
    // @ts-expect-error Zod refine callback typing doesn't support function-based error returns in v3
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    (data: any) => ({
      message: `Trial count (${estimateTrialCount(data.parameters)}) exceeds maximum (${MAX_TRIAL_COUNT}). Reduce parameter ranges or step sizes.`,
      path: ["parameters"],
    }),
  );

export const optimizationWithConstraints = optimizationFormSchema;

export type OptimizationFormData = z.infer<typeof optimizationFormSchema>;

/**
 * Parse and validate optimization form data.
 *
 * Args:
 *   data: Candidate form values
 *
 * Returns:
 *   Zod SafeParseResult with validated data or errors
 *
 * Example:
 *   const result = optimizationFormSchema.safeParse(formValues);
 *   if (result.success) {
 *     // Submit result.data to API
 *   } else {
 *     // Display result.error.flatten().fieldErrors
 *   }
 */
export function validateOptimizationForm(data: unknown) {
  return optimizationWithConstraints.safeParse(data);
}

/**
 * Validate a single parameter range.
 *
 * Used for field-level validation in the parameter range editor.
 *
 * Args:
 *   param: Parameter range to validate
 *
 * Returns:
 *   Zod SafeParseResult
 */
export function validateParameterRange(param: unknown) {
  return parameterRangeSchema.safeParse(param);
}

/**
 * Validate a single optimization metric.
 *
 * Args:
 *   metric: Metric value to validate
 *
 * Returns:
 *   true if valid, false otherwise
 */
export function isValidMetric(metric: unknown): metric is OptimizationMetric {
  return VALID_METRICS.includes(metric as OptimizationMetric);
}

/**
 * Check if trial count exceeds soft warning threshold.
 *
 * Soft threshold (10,000 trials) is used to warn users but not block submission.
 *
 * Args:
 *   count: Number of trials
 *
 * Returns:
 *   true if count exceeds soft threshold
 */
export function exceedsSoftTrialCountLimit(count: number): boolean {
  return count > 10000;
}

/**
 * Check if trial count exceeds hard limit.
 *
 * Hard limit (100,000 trials) blocks form submission.
 *
 * Args:
 *   count: Number of trials
 *
 * Returns:
 *   true if count exceeds hard limit
 */
export function exceedsHardTrialCountLimit(count: number): boolean {
  return count >= MAX_TRIAL_COUNT;
}
