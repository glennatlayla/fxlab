/**
 * RiskChangeDiff — Display and confirm risk settings changes.
 *
 * Purpose:
 *   Show a side-by-side comparison of current vs. proposed risk settings
 *   before applying changes. Highlight large changes (>50%) with visual
 *   warnings. Gate confirmation behind SlideToConfirm gesture.
 *
 * Responsibilities:
 *   - Display all changed fields with current and proposed values.
 *   - Show percentage change for each field.
 *   - Highlight large changes (>50%) with red background and warning.
 *   - Use SlideToConfirm with danger variant if any large changes exist.
 *   - Call onConfirm when user confirms changes.
 *   - Call onCancel when user dismisses.
 *   - Show loading state when isApplying=true.
 *
 * Does NOT:
 *   - Make API calls (parent is responsible).
 *   - Manage state (receives all via props).
 *   - Validate values (backend does this).
 *
 * Dependencies:
 *   - React (ReactNode)
 *   - RiskSettingsDiff type
 *   - SlideToConfirm component
 *   - lucide-react (AlertTriangle icon)
 *   - Tailwind CSS, clsx
 *
 * Error conditions:
 *   - None; gracefully handles empty diffs array.
 *
 * Example:
 *   const diffs = [
 *     { field: "max_position_size", label: "Max Position Size",
 *       current: 10000, proposed: 15000, changePercent: 50, isLargeChange: true }
 *   ];
 *   <RiskChangeDiff
 *     diffs={diffs}
 *     onConfirm={() => applyChanges()}
 *     onCancel={() => closeDiffReview()}
 *     isApplying={false}
 *   />
 */

import React from "react";
import { AlertTriangle } from "lucide-react";
import clsx from "clsx";
import { SlideToConfirm } from "@/components/mobile/SlideToConfirm";
import type { RiskSettingsDiff } from "../types";

export interface RiskChangeDiffProps {
  /** Array of RiskSettingsDiff objects representing changed fields. */
  diffs: RiskSettingsDiff[];
  /** Callback when user confirms changes. */
  onConfirm: () => void;
  /** Callback when user cancels. */
  onCancel: () => void;
  /** Whether changes are currently being applied (shows loading state). */
  isApplying?: boolean;
}

/**
 * RiskChangeDiff component.
 *
 * Renders a detailed review of all risk settings changes with visual
 * highlights for large changes. Uses SlideToConfirm for confirmation
 * to prevent accidental applies.
 *
 * Example:
 *   <RiskChangeDiff
 *     diffs={diffs}
 *     onConfirm={handleApply}
 *     onCancel={handleCancel}
 *     isApplying={isLoading}
 *   />
 */
export function RiskChangeDiff({
  diffs,
  onConfirm,
  onCancel,
  isApplying = false,
}: RiskChangeDiffProps): React.ReactElement {
  // Determine if any large changes exist (for variant selection).
  const hasLargeChanges = diffs.some((d) => d.isLargeChange);

  /**
   * Format a number as a string with comma separators for display.
   */
  const formatNumber = (n: number): string => n.toLocaleString("en-US");

  /**
   * Format percentage change with sign and one decimal place.
   */
  const formatPercent = (pct: number): string => {
    const sign = pct > 0 ? "+" : "";
    return `${sign}${pct.toFixed(1)}%`;
  };

  return (
    <div className="flex flex-col gap-6">
      {/* Header */}
      <div className="flex flex-col gap-2">
        <h2 className="text-lg font-semibold text-surface-900">Review Changes</h2>
        <p className="text-sm text-surface-600">
          Review the following changes before applying. Large changes (50% or greater) are
          highlighted in red.
        </p>
      </div>

      {/* Changes list */}
      <div className="space-y-3">
        {diffs.length === 0 ? (
          <p className="py-4 text-center text-sm text-surface-500">No changes to review.</p>
        ) : (
          diffs.map((diff) => (
            <div
              key={diff.field}
              data-testid={`diff-row-${diff.field}`}
              className={clsx(
                "rounded-lg p-4 transition-colors",
                diff.isLargeChange ? "border border-red-200 bg-red-50" : "bg-surface-50",
              )}
            >
              {/* Field label with large change badge */}
              <div className="mb-3 flex items-center justify-between gap-2">
                <h3 className="font-medium text-surface-900">{diff.label}</h3>
                {diff.isLargeChange && (
                  <div className="inline-flex items-center gap-1 rounded-full bg-red-100 px-2 py-1 text-xs font-semibold text-red-700">
                    <AlertTriangle className="h-3 w-3" />
                    Large change
                  </div>
                )}
              </div>

              {/* Current → Proposed with % change */}
              <div className="flex items-center justify-between gap-4">
                <div className="flex-1">
                  <div className="text-xs text-surface-500">Current</div>
                  <div className="text-lg font-semibold text-surface-900">
                    {formatNumber(diff.current)}
                  </div>
                </div>

                <div className="flex flex-col items-center gap-1">
                  <div className="text-xs font-medium text-surface-600">→</div>
                  <div
                    className={clsx(
                      "text-sm font-semibold",
                      diff.changePercent > 0 ? "text-red-600" : "text-green-600",
                    )}
                  >
                    {formatPercent(diff.changePercent)}
                  </div>
                </div>

                <div className="flex-1 text-right">
                  <div className="text-xs text-surface-500">Proposed</div>
                  <div className="text-lg font-semibold text-surface-900">
                    {formatNumber(diff.proposed)}
                  </div>
                </div>
              </div>
            </div>
          ))
        )}
      </div>

      {/* Confirmation actions */}
      <div className="flex flex-col gap-3">
        {/* Large change warning */}
        {hasLargeChanges && (
          <div className="flex gap-2 rounded-lg border border-red-200 bg-red-50 p-3">
            <AlertTriangle className="mt-0.5 h-5 w-5 flex-shrink-0 text-red-600" />
            <div>
              <p className="text-sm font-medium text-red-900">Large changes detected</p>
              <p className="mt-0.5 text-sm text-red-700">
                One or more settings are changing by more than 50% (larger increase). Please review
                carefully.
              </p>
            </div>
          </div>
        )}

        {/* Slide to confirm with danger variant if large changes */}
        <SlideToConfirm
          label={isApplying ? "Applying..." : "Slide to apply changes"}
          onConfirm={onConfirm}
          variant={hasLargeChanges ? "danger" : "default"}
          disabled={isApplying}
        />

        {/* Cancel button */}
        <button
          onClick={onCancel}
          disabled={isApplying}
          className={clsx(
            "w-full rounded-lg border border-surface-200 bg-white px-4 py-3 font-medium",
            "text-surface-900 transition-colors hover:bg-surface-50",
            "disabled:cursor-not-allowed disabled:opacity-50",
          )}
        >
          Cancel
        </button>

        {/* Loading indicator when applying */}
        {isApplying && (
          <div className="flex items-center justify-center gap-2 py-2">
            <div className="h-4 w-4 animate-spin rounded-full border-2 border-brand-500 border-t-transparent" />
            <span className="text-sm text-surface-600">Applying changes...</span>
          </div>
        )}
      </div>
    </div>
  );
}
