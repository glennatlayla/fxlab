/**
 * HoldoutStatusCard — holdout evaluation pass/fail, dates, contamination flag.
 *
 * Purpose:
 *   Display the holdout evaluation status for a backtest run.
 *
 * Responsibilities:
 *   - Show pass/fail status with visual indicator.
 *   - Display holdout period dates.
 *   - Show contamination warning if detected.
 *   - Display Sharpe ratio.
 *   - Handle not-evaluated state.
 *
 * Does NOT:
 *   - Compute holdout results (backend-authoritative).
 *   - Fetch data.
 *
 * Dependencies:
 *   - HoldoutStatusCardProps from ../types.
 *
 * Example:
 *   <HoldoutStatusCard holdout={payload.holdout} />
 */

import { memo } from "react";
import type { HoldoutStatusCardProps } from "../types";

/**
 * Render the holdout status card.
 *
 * Args:
 *   holdout: Holdout evaluation data.
 *
 * Returns:
 *   Card element with holdout status details.
 */
export const HoldoutStatusCard = memo(function HoldoutStatusCard({
  holdout,
}: HoldoutStatusCardProps) {
  const formatDate = (dateStr: string | null): string => {
    if (!dateStr) return "—";
    return new Date(dateStr).toLocaleDateString();
  };

  return (
    <div
      data-testid="holdout-status-card"
      className={`rounded-lg border p-4 ${
        !holdout.evaluated
          ? "border-slate-200 bg-slate-50"
          : holdout.passed
            ? "border-emerald-200 bg-emerald-50"
            : "border-red-200 bg-red-50"
      }`}
    >
      <div className="flex items-center justify-between">
        <h4 className="text-sm font-semibold text-slate-700">Holdout Evaluation</h4>
        <span
          className={`inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium ${
            !holdout.evaluated
              ? "bg-slate-100 text-slate-600"
              : holdout.passed
                ? "bg-emerald-100 text-emerald-700"
                : "bg-red-100 text-red-700"
          }`}
        >
          {!holdout.evaluated ? "Not Evaluated" : holdout.passed ? "Pass" : "Fail"}
        </span>
      </div>

      <div className="mt-3 space-y-2 text-sm">
        <div data-testid="holdout-dates" className="flex justify-between text-slate-600">
          <span>Period:</span>
          <span>
            {formatDate(holdout.start_date)} — {formatDate(holdout.end_date)}
          </span>
        </div>

        {holdout.sharpe_ratio !== null && (
          <div className="flex justify-between text-slate-600">
            <span>Sharpe Ratio:</span>
            <span className="font-medium tabular-nums">{holdout.sharpe_ratio}</span>
          </div>
        )}

        {holdout.contamination_detected && (
          <div className="mt-2 rounded bg-amber-100 px-2 py-1 text-xs text-amber-800">
            Contamination detected — holdout period overlaps training data.
          </div>
        )}
      </div>
    </div>
  );
});
