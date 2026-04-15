/**
 * Readiness feature constants — centralized values for grades, colors, and dimensions.
 *
 * Purpose:
 *   Single source of truth for grade-to-color mapping, dimension labels,
 *   thresholds, and layout values used across the Readiness feature.
 *
 * Does NOT:
 *   - Contain logic, components, or rendering code.
 *   - Import external dependencies.
 *
 * Dependencies:
 *   - None (pure constants).
 */

import type { ReadinessGrade } from "@/types/readiness";

// ---------------------------------------------------------------------------
// Grade badge color mapping — Phase 2 §8.4
// ---------------------------------------------------------------------------

/**
 * Tailwind class sets for each readiness grade badge.
 *
 * Grade A: green (proceed with confidence)
 * Grade B: blue (proceed with monitoring)
 * Grade C: yellow (address weakest dimension)
 * Grade D: orange (significant concerns)
 * Grade F: red (do not proceed)
 */
export const GRADE_BADGE_CLASSES: Record<ReadinessGrade, string> = {
  A: "bg-emerald-100 text-emerald-800 ring-emerald-600/20",
  B: "bg-blue-100 text-blue-800 ring-blue-600/20",
  C: "bg-yellow-100 text-yellow-800 ring-yellow-600/20",
  D: "bg-orange-100 text-orange-800 ring-orange-600/20",
  F: "bg-red-100 text-red-800 ring-red-600/20",
};

/** Grade interpretation text per Phase 2 §8.4. */
export const GRADE_INTERPRETATION: Record<ReadinessGrade, string> = {
  A: "Proceed to paper trading with confidence",
  B: "Proceed to paper trading with monitoring",
  C: "Address weakest dimension before paper trading",
  D: "Significant concerns — do not paper without remediation",
  F: "Do not proceed — blockers must be resolved",
};

/** Grade minimum sub-score thresholds per Phase 2 §8.4. */
export const GRADE_THRESHOLDS: Record<ReadinessGrade, number> = {
  A: 80,
  B: 65,
  C: 50,
  D: 35,
  F: 0,
};

// ---------------------------------------------------------------------------
// Scoring dimension labels and Grade-F thresholds
// ---------------------------------------------------------------------------

/** Dimension display labels and failure criteria per Phase 2 §8.4. */
export const DIMENSION_CONFIG: Record<string, { label: string; failDescription: string }> = {
  oos_stability: {
    label: "OOS Stability",
    failDescription: "OOS/IS Sharpe ratio < 0.3",
  },
  drawdown: {
    label: "Max Drawdown",
    failDescription: "Max drawdown > 40% of initial capital",
  },
  trade_count: {
    label: "Trade Count",
    failDescription: "Fewer than 30 total OOS trades",
  },
  holdout_pass: {
    label: "Holdout Evaluation",
    failDescription: "Holdout Sharpe <= 0 or not evaluated",
  },
  regime_consistency: {
    label: "Regime Consistency",
    failDescription: "Fewer than 2/3 regimes with positive Sharpe",
  },
  parameter_stability: {
    label: "Parameter Stability",
    failDescription: "Perturbed median Sharpe < 0.5x baseline",
  },
};

// ---------------------------------------------------------------------------
// Override watermark styling
// ---------------------------------------------------------------------------

/** Tailwind classes for the override watermark badge (amber per spec). */
export const OVERRIDE_WATERMARK_CLASSES = "bg-amber-50 text-amber-800 ring-amber-600/20";

// ---------------------------------------------------------------------------
// API & retry
// ---------------------------------------------------------------------------

/** Maximum retry attempts for readiness API calls. */
export const READINESS_API_MAX_RETRIES = 3;

/** Base delay in ms for exponential backoff. */
export const READINESS_API_RETRY_BASE_DELAY_MS = 1000;

/** Jitter factor for retry backoff. */
export const READINESS_API_JITTER_FACTOR = 0.25;

// ---------------------------------------------------------------------------
// Blocker severity colors
// ---------------------------------------------------------------------------

/** Tailwind class sets for blocker severity indicators. */
export const BLOCKER_SEVERITY_CLASSES: Record<string, string> = {
  critical: "bg-red-100 text-red-800",
  high: "bg-orange-100 text-orange-800",
  medium: "bg-yellow-100 text-yellow-800",
  low: "bg-slate-100 text-slate-600",
};

// ---------------------------------------------------------------------------
// Logging operation names
// ---------------------------------------------------------------------------

export const OP_FETCH_READINESS = "readiness.fetch_report";
export const OP_GENERATE_READINESS = "readiness.generate_report";
export const OP_SUBMIT_PROMOTION = "readiness.submit_promotion";
export const OP_RENDER_PAGE = "readiness.render_page";
