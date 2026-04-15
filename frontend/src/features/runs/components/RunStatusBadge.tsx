/**
 * RunStatusBadge — displays run lifecycle status as a coloured pill.
 *
 * Purpose:
 *   Render the current run status with appropriate colour coding for
 *   quick visual identification of run state.
 *
 * Responsibilities:
 *   - Map RunStatus values to semantic colours.
 *   - Render a compact badge suitable for table cells and headers.
 *
 * Does NOT:
 *   - Contain business logic or polling.
 *   - Handle click events or navigation.
 */

import type { RunStatus } from "@/types/run";
import { RUN_STATUS } from "@/types/run";
import type { RunStatusBadgeProps } from "../types";

/** Map each status to Tailwind-compatible colour classes. */
const STATUS_STYLES: Record<RunStatus, string> = {
  pending: "bg-yellow-100 text-yellow-800",
  running: "bg-blue-100 text-blue-800",
  complete: "bg-green-100 text-green-800",
  failed: "bg-red-100 text-red-800",
  cancelled: "bg-gray-100 text-gray-800",
};

/** Human-readable display labels for each status. */
const STATUS_LABELS: Record<RunStatus, string> = {
  pending: "Pending",
  running: "Running",
  complete: "Complete",
  failed: "Failed",
  cancelled: "Cancelled",
};

/**
 * Render a run status badge.
 *
 * Args:
 *   status: Current run lifecycle status.
 *   className: Optional additional CSS class names.
 */
export function RunStatusBadge({ status, className = "" }: RunStatusBadgeProps) {
  const colorClasses = STATUS_STYLES[status] ?? "bg-gray-100 text-gray-800";
  const label = STATUS_LABELS[status] ?? status;

  return (
    <span
      className={`inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-medium ${colorClasses} ${className}`.trim()}
      data-testid="run-status-badge"
      role="status"
      aria-label={`Run status: ${label}`}
    >
      {status === RUN_STATUS.RUNNING && (
        <span
          className="mr-1.5 h-2 w-2 animate-pulse rounded-full bg-blue-500"
          aria-hidden="true"
        />
      )}
      {label}
    </span>
  );
}
