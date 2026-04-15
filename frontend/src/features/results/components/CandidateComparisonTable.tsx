/**
 * CandidateComparisonTable — virtualized side-by-side candidate metric comparison.
 *
 * Purpose:
 *   Displays selected candidate strategies in a comparison table for
 *   evaluation before deployment. Uses TanStack Virtual for efficient
 *   rendering of large candidate sets.
 *
 * Responsibilities:
 *   - Render candidate rows with key performance metrics via virtual scroll.
 *   - Provide a download button for candidate data with loading state.
 *   - Show empty state when no candidates exist.
 *
 * Does NOT:
 *   - Fetch candidate data from the API.
 *   - Rank or sort candidates (displays as provided).
 *
 * Dependencies:
 *   - CandidateComparisonTableProps from ../types.
 *   - @tanstack/react-virtual for row virtualization.
 *   - Constants from ../constants.
 */

import { useRef, memo } from "react";
import { useVirtualizer } from "@tanstack/react-virtual";
import type { CandidateComparisonTableProps } from "../types";
import { DownloadDataButton } from "./DownloadDataButton";
import {
  CANDIDATE_TABLE_ROW_HEIGHT,
  CANDIDATE_TABLE_VIEWPORT_HEIGHT,
  CANDIDATE_TABLE_OVERSCAN,
} from "../constants";

/**
 * Render the candidate comparison table.
 *
 * Args:
 *   candidates: Array of CandidateMetrics objects.
 *   onDownload: Callback to trigger data export.
 *   isDownloading: Whether a download is in progress.
 *
 * Returns:
 *   Table element or empty state.
 *
 * Example:
 *   <CandidateComparisonTable candidates={candidates} onDownload={fn} />
 */
export const CandidateComparisonTable = memo(function CandidateComparisonTable({
  candidates,
  onDownload,
  isDownloading = false,
}: CandidateComparisonTableProps) {
  const parentRef = useRef<HTMLDivElement>(null);

  const rowVirtualizer = useVirtualizer({
    count: candidates.length,
    getScrollElement: () => parentRef.current,
    estimateSize: () => CANDIDATE_TABLE_ROW_HEIGHT,
    overscan: CANDIDATE_TABLE_OVERSCAN,
  });

  if (candidates.length === 0) {
    return (
      <div
        data-testid="candidate-comparison-empty"
        className="flex h-32 items-center justify-center text-sm text-slate-400"
      >
        No candidate data available.
      </div>
    );
  }

  return (
    <div
      data-testid="candidate-comparison-table"
      className="overflow-hidden rounded-lg border border-slate-200"
    >
      {/* Header */}
      <div className="flex items-center justify-between border-b border-slate-200 bg-slate-50 px-4 py-2">
        <span className="text-sm font-medium text-slate-700">Candidates ({candidates.length})</span>
        <DownloadDataButton onDownload={onDownload} label="Download" isLoading={isDownloading} />
      </div>

      {/* Column headers */}
      <div
        role="row"
        aria-label="Candidate comparison column headers"
        className="grid grid-cols-[120px_80px_80px_80px_80px_80px_80px_60px] gap-1 border-b border-slate-200 bg-slate-100 px-4 py-2 text-xs font-semibold text-slate-600"
      >
        <span role="columnheader">Label</span>
        <span role="columnheader">Objective</span>
        <span role="columnheader">Sharpe</span>
        <span role="columnheader">Max DD</span>
        <span role="columnheader">Return</span>
        <span role="columnheader">Win Rate</span>
        <span role="columnheader">Profit Factor</span>
        <span role="columnheader">Trades</span>
      </div>

      {/* Virtualized rows */}
      <div
        ref={parentRef}
        className="overflow-auto"
        style={{ height: CANDIDATE_TABLE_VIEWPORT_HEIGHT }}
      >
        <div
          style={{
            height: `${rowVirtualizer.getTotalSize()}px`,
            width: "100%",
            position: "relative",
          }}
        >
          {rowVirtualizer.getVirtualItems().map((virtualRow) => {
            const c = candidates[virtualRow.index];
            return (
              <div
                key={c.candidate_id}
                data-testid={`candidate-row-${c.candidate_id}`}
                className="absolute left-0 top-0 grid w-full grid-cols-[120px_80px_80px_80px_80px_80px_80px_60px] gap-1 border-b border-slate-100 px-4 text-xs"
                style={{
                  height: `${virtualRow.size}px`,
                  transform: `translateY(${virtualRow.start}px)`,
                }}
              >
                <span className="flex items-center truncate font-medium">{c.label}</span>
                <span className="flex items-center tabular-nums">
                  {c.objective_value.toFixed(2)}
                </span>
                <span className="flex items-center tabular-nums">{c.sharpe_ratio.toFixed(2)}</span>
                <span className="flex items-center tabular-nums text-red-600">
                  {c.max_drawdown_pct.toFixed(1)}%
                </span>
                <span
                  className={`flex items-center tabular-nums ${c.total_return_pct >= 0 ? "text-emerald-600" : "text-red-600"}`}
                >
                  {c.total_return_pct >= 0 ? "+" : ""}
                  {c.total_return_pct.toFixed(1)}%
                </span>
                <span className="flex items-center tabular-nums">
                  {(c.win_rate * 100).toFixed(1)}%
                </span>
                <span className="flex items-center tabular-nums">{c.profit_factor.toFixed(2)}</span>
                <span className="flex items-center tabular-nums">{c.trade_count}</span>
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
});
