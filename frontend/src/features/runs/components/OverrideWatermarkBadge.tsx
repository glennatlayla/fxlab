/**
 * OverrideWatermarkBadge — amber warning badge per spec §8.2.
 *
 * Purpose:
 *   Render a visible warning when a run is executing under an active
 *   governance override. Per spec §8.2, badge must be ≥16px, amber/warning
 *   colour, and visible on run cards.
 *
 * Responsibilities:
 *   - Display override approval metadata.
 *   - Use amber/warning colours for visibility.
 *   - Show revocation status if applicable.
 *
 * Does NOT:
 *   - Handle override request/approval flow.
 *   - Navigate to override details (parent handles).
 */

import type { OverrideWatermarkBadgeProps } from "../types";

/**
 * Render an override watermark badge.
 *
 * Args:
 *   watermark: Override watermark metadata.
 *   className: Optional additional CSS class names.
 */
export function OverrideWatermarkBadge({ watermark, className = "" }: OverrideWatermarkBadgeProps) {
  const isRevoked = watermark.revoked;

  return (
    <div
      className={`flex items-center gap-2 rounded-md border ${
        isRevoked
          ? "border-gray-600 bg-gray-800 text-gray-400"
          : "border-amber-600 bg-amber-900/30 text-amber-300"
      } px-3 py-2 text-sm ${className}`.trim()}
      data-testid="override-watermark-badge"
      style={{ minHeight: "16px" }}
      role="alert"
      aria-label={isRevoked ? "Override revoked" : "Active override"}
    >
      <svg
        className="h-4 w-4 flex-shrink-0"
        fill="currentColor"
        viewBox="0 0 20 20"
        aria-hidden="true"
      >
        <path
          fillRule="evenodd"
          d="M10 1a4.5 4.5 0 00-4.5 4.5V9H5a2 2 0 00-2 2v6a2 2 0 002 2h10a2 2 0 002-2v-6a2 2 0 00-2-2h-.5V5.5A4.5 4.5 0 0010 1zm3 8V5.5a3 3 0 10-6 0V9h6z"
          clipRule="evenodd"
        />
      </svg>
      <div className="min-w-0 flex-1">
        <div className="font-medium">{isRevoked ? "Override Revoked" : "Override Active"}</div>
        <div className="truncate text-xs opacity-80">
          Approved by {watermark.approved_by} — {watermark.reason}
        </div>
      </div>
    </div>
  );
}
