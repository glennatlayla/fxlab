/**
 * ScoringBreakdown — per-dimension sub-score cards with pass/fail.
 *
 * Purpose:
 *   Render scoring evidence for each of the six readiness dimensions
 *   as individual cards showing score, threshold, and pass/fail status.
 *
 * Responsibilities:
 *   - Render a card per dimension with score bar and pass/fail indicator.
 *   - Show dimension details when available.
 *   - Handle empty state gracefully.
 *
 * Does NOT:
 *   - Compute scores (backend-authoritative).
 *   - Fetch data.
 *
 * Dependencies:
 *   - ScoringBreakdownProps from ../types.
 *
 * Example:
 *   <ScoringBreakdown dimensions={payload.dimensions} />
 */

import { memo } from "react";
import type { ScoringBreakdownProps } from "../types";

/**
 * Render the scoring breakdown grid.
 *
 * Args:
 *   dimensions: Per-dimension scoring data.
 *
 * Returns:
 *   Grid of dimension cards or empty state.
 */
export const ScoringBreakdown = memo(function ScoringBreakdown({
  dimensions,
}: ScoringBreakdownProps) {
  if (dimensions.length === 0) {
    return (
      <div
        data-testid="scoring-breakdown-empty"
        className="flex h-32 items-center justify-center text-sm text-slate-400"
      >
        No scoring dimensions available.
      </div>
    );
  }

  return (
    <div data-testid="scoring-breakdown" className="space-y-3">
      <h3 className="text-sm font-semibold text-slate-700">Scoring Breakdown</h3>
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-2 lg:grid-cols-3">
        {dimensions.map((dim) => (
          <div
            key={dim.dimension}
            data-testid={`dimension-card-${dim.dimension}`}
            data-passed={String(dim.passed)}
            className={`rounded-lg border p-4 ${
              dim.passed ? "border-slate-200 bg-white" : "border-red-200 bg-red-50"
            }`}
          >
            <div className="flex items-center justify-between">
              <span className="text-sm font-medium text-slate-700">{dim.label}</span>
              <span
                className={`inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium ${
                  dim.passed ? "bg-emerald-100 text-emerald-700" : "bg-red-100 text-red-700"
                }`}
              >
                {dim.passed ? "Pass" : "Fail"}
              </span>
            </div>

            <div className="mt-2 flex items-baseline gap-1">
              <span className="text-2xl font-bold text-slate-900">{dim.score}</span>
              <span className="text-xs text-slate-400">/ 100</span>
            </div>

            {/* Progress bar */}
            <div
              className="mt-2 h-1.5 w-full rounded-full bg-slate-200"
              role="progressbar"
              aria-valuenow={dim.score}
              aria-valuemin={0}
              aria-valuemax={100}
              aria-label={`${dim.label} score`}
            >
              <div
                className={`h-1.5 rounded-full ${dim.passed ? "bg-emerald-500" : "bg-red-500"}`}
                style={{ width: `${Math.min(dim.score, 100)}%` }}
              />
            </div>

            {/* Threshold marker */}
            <div className="mt-1 text-xs text-slate-400">Threshold: {dim.threshold}</div>

            {dim.details && <p className="mt-2 text-xs text-slate-500">{dim.details}</p>}
          </div>
        ))}
      </div>
    </div>
  );
});
