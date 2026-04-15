/**
 * ReportHistory — reverse-chronological list of prior readiness reports.
 *
 * Purpose:
 *   Display historical readiness reports for comparison and audit trail.
 *
 * Responsibilities:
 *   - Render each historical report entry with grade, score, and timestamp.
 *   - Handle empty state.
 *
 * Does NOT:
 *   - Fetch data.
 *   - Navigate to historical report details.
 *
 * Dependencies:
 *   - ReportHistoryProps from ../types.
 *   - GradeBadge component.
 *
 * Example:
 *   <ReportHistory entries={payload.report_history} />
 */

import { memo } from "react";
import type { ReportHistoryProps } from "../types";
import { GradeBadge } from "./GradeBadge";

/**
 * Render the report history list.
 *
 * Args:
 *   entries: Historical report entries (already in reverse chronological order).
 *
 * Returns:
 *   List of report entries or empty state.
 */
export const ReportHistory = memo(function ReportHistory({ entries }: ReportHistoryProps) {
  if (entries.length === 0) {
    return (
      <div
        data-testid="report-history-empty"
        className="flex h-20 items-center justify-center text-sm text-slate-400"
      >
        No previous reports.
      </div>
    );
  }

  return (
    <div data-testid="report-history" className="space-y-2">
      <h4 className="text-sm font-semibold text-slate-700">Report History</h4>
      <div className="divide-y divide-slate-100 rounded-lg border border-slate-200">
        {entries.map((entry) => (
          <div
            key={entry.report_id}
            data-testid={`report-history-entry-${entry.report_id}`}
            className="flex items-center gap-4 px-4 py-3"
          >
            <GradeBadge grade={entry.grade} size="sm" />
            <div className="flex-1">
              <div className="flex items-baseline gap-2">
                <span className="text-sm font-medium text-slate-700">{entry.score}</span>
                <span className="text-xs text-slate-400">/ 100</span>
              </div>
              <div className="text-xs text-slate-500">
                Policy v{entry.policy_version} · {entry.assessor}
              </div>
            </div>
            <span className="text-xs text-slate-400">
              {new Date(entry.assessed_at).toLocaleDateString()}
            </span>
          </div>
        ))}
      </div>
    </div>
  );
});
