/**
 * TrialSummaryTable — virtualized, sortable trial results table with top-N highlighting.
 *
 * Purpose:
 *   Displays all optimization trial results in a virtualized table,
 *   highlighting the top-N trials by objective value for quick identification.
 *   Uses TanStack Virtual for efficient rendering of large trial sets.
 *
 * Responsibilities:
 *   - Render trial summary rows with key metrics via virtual scroll.
 *   - Highlight top-N trials with a visual indicator.
 *   - Handle row click callbacks with keyboard support.
 *   - Provide a download button for trial data with loading state.
 *   - Show empty state when no trials exist.
 *
 * Does NOT:
 *   - Fetch trial data from the API.
 *   - Perform the actual download.
 *
 * Dependencies:
 *   - TrialSummaryTableProps from ../types.
 *   - @tanstack/react-virtual for row virtualization.
 *   - Constants from ../constants.
 */

import { useMemo, useRef, useCallback, memo } from "react";
import { useVirtualizer } from "@tanstack/react-virtual";
import type { TrialSummaryTableProps } from "../types";
import { DownloadDataButton } from "./DownloadDataButton";
import {
  TRIAL_TABLE_ROW_HEIGHT,
  TRIAL_TABLE_VIEWPORT_HEIGHT,
  TRIAL_TABLE_OVERSCAN,
} from "../constants";

/**
 * Render the trial summary table.
 *
 * Args:
 *   trials: Array of TrialSummary objects.
 *   topN: Number of top trials to highlight.
 *   onTrialClick: Callback when a trial row is clicked.
 *   onDownload: Callback to trigger data export.
 *   isDownloading: Whether a download is in progress.
 *
 * Returns:
 *   Table element or empty state.
 *
 * Example:
 *   <TrialSummaryTable trials={trials} topN={5} onTrialClick={fn} onDownload={fn} />
 */
export const TrialSummaryTable = memo(function TrialSummaryTable({
  trials,
  topN,
  onTrialClick,
  onDownload,
  isDownloading = false,
}: TrialSummaryTableProps) {
  const parentRef = useRef<HTMLDivElement>(null);

  // Determine the top-N trial IDs by objective value (descending).
  // Must be called before any early return to satisfy rules-of-hooks.
  const topTrialIds = useMemo(() => {
    const sorted = [...trials].sort((a, b) => b.objective_value - a.objective_value);
    return new Set(sorted.slice(0, topN).map((t) => t.trial_id));
  }, [trials, topN]);

  // Memoized row click handler — avoids creating new functions per virtual row.
  const handleRowClick = useCallback(
    (trialId: string) => {
      onTrialClick(trialId);
    },
    [onTrialClick],
  );

  // Memoized keyboard handler for row activation (Enter/Space).
  const handleRowKeyDown = useCallback(
    (e: React.KeyboardEvent, trialId: string) => {
      if (e.key === "Enter" || e.key === " ") {
        e.preventDefault();
        onTrialClick(trialId);
      }
    },
    [onTrialClick],
  );

  const rowVirtualizer = useVirtualizer({
    count: trials.length,
    getScrollElement: () => parentRef.current,
    estimateSize: () => TRIAL_TABLE_ROW_HEIGHT,
    overscan: TRIAL_TABLE_OVERSCAN,
  });

  if (trials.length === 0) {
    return (
      <div
        data-testid="trial-summary-empty"
        className="flex h-32 items-center justify-center text-sm text-slate-400"
      >
        No trial data available.
      </div>
    );
  }

  return (
    <div
      data-testid="trial-summary-table"
      className="overflow-hidden rounded-lg border border-slate-200"
    >
      {/* Header */}
      <div className="flex items-center justify-between border-b border-slate-200 bg-slate-50 px-4 py-2">
        <span className="text-sm font-medium text-slate-700">Trials ({trials.length})</span>
        <DownloadDataButton onDownload={onDownload} label="Download" isLoading={isDownloading} />
      </div>

      {/* Column headers */}
      <div
        role="row"
        aria-label="Trial summary column headers"
        className="grid grid-cols-[60px_80px_80px_80px_80px_60px_80px] gap-1 border-b border-slate-200 bg-slate-100 px-4 py-2 text-xs font-semibold text-slate-600"
      >
        <span role="columnheader">#</span>
        <span role="columnheader">Objective</span>
        <span role="columnheader">Sharpe</span>
        <span role="columnheader">Max DD</span>
        <span role="columnheader">Return</span>
        <span role="columnheader">Trades</span>
        <span role="columnheader">Status</span>
      </div>

      {/* Virtualized rows */}
      <div
        ref={parentRef}
        className="overflow-auto"
        style={{ height: TRIAL_TABLE_VIEWPORT_HEIGHT }}
      >
        <div
          style={{
            height: `${rowVirtualizer.getTotalSize()}px`,
            width: "100%",
            position: "relative",
          }}
        >
          {rowVirtualizer.getVirtualItems().map((virtualRow) => {
            const trial = trials[virtualRow.index];
            const isTop = topTrialIds.has(trial.trial_id);
            return (
              <div
                key={trial.trial_id}
                data-testid={`trial-row-${trial.trial_id}`}
                data-top={isTop ? "true" : "false"}
                onClick={() => handleRowClick(trial.trial_id)}
                role="button"
                tabIndex={0}
                aria-label={`Trial ${trial.trial_index}: objective ${trial.objective_value.toFixed(2)}, Sharpe ${trial.sharpe_ratio.toFixed(2)}`}
                onKeyDown={(e) => handleRowKeyDown(e, trial.trial_id)}
                className={`absolute left-0 top-0 grid w-full cursor-pointer grid-cols-[60px_80px_80px_80px_80px_60px_80px] gap-1 border-b border-slate-100 px-4 text-xs hover:bg-slate-50 focus:outline-none focus:ring-2 focus:ring-inset focus:ring-blue-500 ${
                  isTop ? "bg-amber-50 font-medium" : ""
                }`}
                style={{
                  height: `${virtualRow.size}px`,
                  transform: `translateY(${virtualRow.start}px)`,
                }}
              >
                <span className="flex items-center tabular-nums">{trial.trial_index}</span>
                <span className="flex items-center tabular-nums">
                  {trial.objective_value.toFixed(2)}
                </span>
                <span className="flex items-center tabular-nums">
                  {trial.sharpe_ratio.toFixed(2)}
                </span>
                <span className="flex items-center tabular-nums text-red-600">
                  {trial.max_drawdown_pct.toFixed(1)}%
                </span>
                <span
                  className={`flex items-center tabular-nums ${trial.total_return_pct >= 0 ? "text-emerald-600" : "text-red-600"}`}
                >
                  {trial.total_return_pct >= 0 ? "+" : ""}
                  {trial.total_return_pct.toFixed(1)}%
                </span>
                <span className="flex items-center tabular-nums">{trial.trade_count}</span>
                <span className="flex items-center capitalize">{trial.status}</span>
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
});
