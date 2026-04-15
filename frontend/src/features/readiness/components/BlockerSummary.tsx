/**
 * BlockerSummary — blocker cards for grade-F runs with owner and next-step.
 *
 * Purpose:
 *   Render actionable blocker cards when a run has readiness grade F.
 *   Each card shows the blocker owner and a concrete next-step action.
 *
 * Responsibilities:
 *   - Render a card per blocker with severity, message, owner, and next-step.
 *   - Show empty state when no blockers exist.
 *
 * Does NOT:
 *   - Resolve blockers (backend-authoritative).
 *   - Gate rendering on grade (parent decides when to mount).
 *
 * Dependencies:
 *   - BlockerSummaryProps from ../types.
 *   - BLOCKER_SEVERITY_CLASSES from ../constants.
 *
 * Example:
 *   <BlockerSummary blockers={payload.blockers} />
 */

import { memo } from "react";
import type { BlockerSummaryProps } from "../types";
import { BLOCKER_SEVERITY_CLASSES } from "../constants";

/**
 * Render the blocker summary.
 *
 * Args:
 *   blockers: List of ReadinessBlocker objects.
 *
 * Returns:
 *   Blocker cards or empty state.
 */
export const BlockerSummary = memo(function BlockerSummary({ blockers }: BlockerSummaryProps) {
  if (blockers.length === 0) {
    return (
      <div
        data-testid="blocker-summary-empty"
        className="flex h-20 items-center justify-center text-sm text-slate-400"
      >
        No blockers found.
      </div>
    );
  }

  return (
    <div data-testid="blocker-summary" className="space-y-3">
      <h3 className="text-sm font-semibold text-red-700">Blockers ({blockers.length})</h3>
      <div className="space-y-2">
        {blockers.map((blocker) => (
          <div
            key={blocker.code}
            data-testid={`blocker-card-${blocker.code}`}
            data-severity={blocker.severity}
            className="rounded-lg border border-red-200 bg-white p-4"
          >
            <div className="flex items-center justify-between">
              <span className="font-mono text-xs font-medium text-slate-600">{blocker.code}</span>
              <span
                className={`inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium ${
                  BLOCKER_SEVERITY_CLASSES[blocker.severity] ?? BLOCKER_SEVERITY_CLASSES.high
                }`}
                aria-label={`Severity: ${blocker.severity}`}
              >
                {blocker.severity}
              </span>
            </div>

            <p className="mt-2 text-sm text-slate-700">{blocker.message}</p>

            <div className="mt-3 flex items-center gap-2 text-xs">
              <span className="font-medium text-slate-500">Owner:</span>
              <span className="text-slate-700">{blocker.blocker_owner}</span>
            </div>

            <div className="mt-1 flex items-start gap-2 text-xs">
              <span className="font-medium text-slate-500">Next step:</span>
              <span className="text-slate-700">{blocker.next_step}</span>
            </div>
          </div>
        ))}
      </div>
    </div>
  );
});
