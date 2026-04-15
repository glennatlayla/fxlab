/**
 * SegmentedPerformanceBar — per-fold and per-regime performance chart.
 *
 * Purpose:
 *   Renders a grouped bar chart comparing return_pct across walk-forward
 *   folds and market regimes, providing at-a-glance segment performance.
 *
 * Responsibilities:
 *   - Render fold performance as bar segments.
 *   - Render regime performance as bar segments.
 *   - Show empty state when both arrays are empty.
 *
 * Does NOT:
 *   - Fetch or compute performance data.
 *   - Handle equity or trade rendering.
 *
 * Dependencies:
 *   - SegmentedPerformanceBarProps from ../types.
 */

import { memo } from "react";
import type { SegmentedPerformanceBarProps } from "../types";
import type { SegmentPerformance } from "@/types/results";

/**
 * Render a horizontal bar for a single performance segment.
 *
 * Args:
 *   segment: Performance data for the segment.
 *   maxAbsReturn: Maximum absolute return across all segments (for scaling).
 *
 * Returns:
 *   A labeled bar element.
 */
function PerformanceSegmentBar({
  segment,
  maxAbsReturn,
}: {
  segment: SegmentPerformance;
  maxAbsReturn: number;
}) {
  const widthPct = maxAbsReturn > 0 ? Math.abs(segment.return_pct / maxAbsReturn) * 100 : 0;
  const isPositive = segment.return_pct >= 0;

  return (
    <div className="flex items-center gap-3 py-1">
      <span className="w-20 truncate text-xs text-slate-600">{segment.label}</span>
      <div className="flex-1">
        <div
          className={`h-5 rounded ${isPositive ? "bg-emerald-400" : "bg-red-400"}`}
          style={{ width: `${Math.max(widthPct, 2)}%` }}
        />
      </div>
      <span className="w-16 text-right text-xs font-medium tabular-nums">
        {segment.return_pct >= 0 ? "+" : ""}
        {segment.return_pct.toFixed(1)}%
      </span>
    </div>
  );
}

/**
 * Render the segmented performance bar chart.
 *
 * Args:
 *   foldPerformance: Per-fold segment data.
 *   regimePerformance: Per-regime segment data.
 *
 * Returns:
 *   Bar chart element or empty state.
 */
export const SegmentedPerformanceBar = memo(function SegmentedPerformanceBar({
  foldPerformance,
  regimePerformance,
}: SegmentedPerformanceBarProps) {
  if (foldPerformance.length === 0 && regimePerformance.length === 0) {
    return (
      <div
        data-testid="segmented-performance-empty"
        className="flex h-32 items-center justify-center text-sm text-slate-400"
      >
        No segment performance data available.
      </div>
    );
  }

  const allSegments = [...foldPerformance, ...regimePerformance];
  const maxAbsReturn = Math.max(...allSegments.map((s) => Math.abs(s.return_pct)), 1);

  return (
    <div data-testid="segmented-performance-bar" className="space-y-4">
      {foldPerformance.length > 0 && (
        <div>
          <h4 className="mb-2 text-xs font-semibold uppercase tracking-wide text-slate-500">
            Fold Performance
          </h4>
          {foldPerformance.map((seg) => (
            <PerformanceSegmentBar
              key={`fold-${seg.label}`}
              segment={seg}
              maxAbsReturn={maxAbsReturn}
            />
          ))}
        </div>
      )}
      {regimePerformance.length > 0 && (
        <div>
          <h4 className="mb-2 text-xs font-semibold uppercase tracking-wide text-slate-500">
            Regime Performance
          </h4>
          {regimePerformance.map((seg) => (
            <PerformanceSegmentBar
              key={`regime-${seg.label}`}
              segment={seg}
              maxAbsReturn={maxAbsReturn}
            />
          ))}
        </div>
      )}
    </div>
  );
});
