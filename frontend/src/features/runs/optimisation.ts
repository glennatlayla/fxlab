/**
 * Optimisation domain types and utility functions (FE-15).
 *
 * Purpose:
 * - Define TypeScript types for optimisation forms and parameters
 * - Provide trial estimation and severity classification utilities
 * - Mirror backend OptimizationConfig contract structure
 *
 * Responsibilities:
 * - Type definitions for optimisation metrics and parameter ranges
 * - Utility functions for trial count estimation
 * - Severity classification for UI color coding
 *
 * Does NOT:
 * - Contain validation logic (see optimisation.validation.ts)
 * - Import from service or repository layers
 * - Perform I/O or external communication
 *
 * Dependencies:
 * - None (pure domain types)
 *
 * Example:
 *   type OptimizationMetric = "sharpe_ratio" | ...
 *   const count = estimateTrialCount(parameters)
 *   const severity = getTrialCountSeverity(count)
 */

/**
 * Supported optimisation metrics.
 *
 * Maps to backend WalkForwardConfig.optimization_metric enum.
 * Each metric quantifies a different aspect of backtest performance
 * for parameter selection during walk-forward optimization.
 */
export type OptimizationMetric =
  | "sharpe_ratio"
  | "total_return"
  | "max_drawdown"
  | "win_rate"
  | "profit_factor";

/**
 * Definition of an optimization parameter range.
 *
 * Each parameter is a dimension in the search space, with a min, max,
 * and step size. The trial count for a parameter is
 * ceil((max - min) / step) + 1.
 *
 * Example:
 *   { name: "ma_fast", min: 5, max: 20, step: 5 }
 *   // Generates values: 5, 10, 15, 20 (4 combinations)
 */
export interface ParameterRange {
  /** Name of the parameter (e.g., "ma_fast", "threshold"). */
  name: string;
  /** Minimum value (inclusive). */
  min: number;
  /** Maximum value (inclusive). */
  max: number;
  /** Step size between values. */
  step: number;
}

/**
 * Backtest form values — shared between backtest and optimization forms.
 *
 * These fields are required for both backtest and optimization runs.
 */
export interface BacktestFormValues {
  /** ULID of the strategy build to execute. */
  strategy_build_id: string;
  /** Ticker symbols to include in the run (comma-separated or array). */
  symbols: string[];
  /** Start date in ISO format (YYYY-MM-DD). */
  start_date: string;
  /** End date in ISO format (YYYY-MM-DD). */
  end_date: string;
  /** Bar interval (e.g., "1m", "5m", "1h", "1d"). */
  interval: string;
  /** Starting equity in currency units. */
  initial_equity: number;
}

/**
 * Optimization form values — extends backtest with optimization-specific fields.
 *
 * These are the complete form values for an optimization run submission.
 * The form includes optional sections for walk-forward and monte carlo.
 */
export interface OptimizationFormValues extends BacktestFormValues {
  /** Which metric to optimize during parameter search. */
  optimization_metric: OptimizationMetric;
  /** Parameter ranges to search over. */
  parameters: ParameterRange[];
  /** Optional: number of rolling windows for walk-forward analysis (2-20). */
  walk_forward_windows?: number;
  /** Optional: percentage of data in training window (50-90). */
  walk_forward_train_pct?: number;
  /** Optional: number of monte carlo simulation runs (≥ 100). */
  monte_carlo_runs?: number;
}

/**
 * Calculate the total number of trial combinations for a parameter grid.
 *
 * For each parameter, the number of steps is ceil((max - min) / step) + 1.
 * Total combinations = product of all parameter step counts.
 *
 * Args:
 *   params: Array of parameter ranges
 *
 * Returns:
 *   Total number of trial combinations
 *
 * Example:
 *   estimateTrialCount([
 *     { name: 'ma_fast', min: 5, max: 20, step: 5 },      // 4 steps
 *     { name: 'ma_slow', min: 20, max: 50, step: 10 },    // 4 steps
 *   ])
 *   // = 4 * 4 = 16 combinations
 *
 *   estimateTrialCount([
 *     { name: 'threshold', min: 0.1, max: 0.9, step: 0.1 } // 9 steps
 *   ])
 *   // = 9 combinations
 */
export function estimateTrialCount(params: ParameterRange[]): number {
  return params.reduce((acc, p) => {
    const steps = Math.ceil((p.max - p.min) / p.step) + 1;
    return acc * steps;
  }, 1);
}

/**
 * Classify trial count severity for UI color coding.
 *
 * Used to visually indicate run duration expectations:
 * - "low" (< 100):    Green badge, expected to complete quickly
 * - "moderate" (100-1000): Amber badge, moderate duration
 * - "high" (1000-10000):   Orange badge, long duration
 * - "extreme" (> 10000):   Red badge, very long / may timeout
 *
 * Args:
 *   count: Total number of trials
 *
 * Returns:
 *   Severity level: 'low' | 'moderate' | 'high' | 'extreme'
 *
 * Example:
 *   getTrialCountSeverity(50) // 'low'
 *   getTrialCountSeverity(500) // 'moderate'
 *   getTrialCountSeverity(5000) // 'high'
 *   getTrialCountSeverity(50000) // 'extreme'
 */
export function getTrialCountSeverity(count: number): "low" | "moderate" | "high" | "extreme" {
  if (count < 100) return "low";
  if (count < 1000) return "moderate";
  if (count < 10000) return "high";
  return "extreme";
}

/**
 * Get human-readable label for trial count severity.
 *
 * Args:
 *   severity: Severity level from getTrialCountSeverity()
 *
 * Returns:
 *   Human-readable label
 *
 * Example:
 *   getSeverityLabel('low') // 'Fast'
 *   getSeverityLabel('extreme') // 'Very Long'
 */
export function getSeverityLabel(severity: "low" | "moderate" | "high" | "extreme"): string {
  switch (severity) {
    case "low":
      return "Fast";
    case "moderate":
      return "Moderate";
    case "high":
      return "Long";
    case "extreme":
      return "Very Long";
    default:
      return "Unknown";
  }
}

/**
 * Get Tailwind CSS class for severity badge background color.
 *
 * Args:
 *   severity: Severity level from getTrialCountSeverity()
 *
 * Returns:
 *   Tailwind CSS class name for background color
 *
 * Example:
 *   getSeverityBgClass('low') // 'bg-green-500'
 *   getSeverityBgClass('extreme') // 'bg-red-500'
 */
export function getSeverityBgClass(severity: "low" | "moderate" | "high" | "extreme"): string {
  switch (severity) {
    case "low":
      return "bg-green-500";
    case "moderate":
      return "bg-amber-500";
    case "high":
      return "bg-orange-500";
    case "extreme":
      return "bg-red-500";
    default:
      return "bg-gray-500";
  }
}
