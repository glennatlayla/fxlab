/**
 * SamplingBanner — informational banner for LTTB downsampled equity curves.
 *
 * Purpose:
 *   Notifies the user when the equity curve has been downsampled server-side
 *   using the Largest-Triangle-Three-Buckets (LTTB) algorithm.
 *
 * Responsibilities:
 *   - Render an alert banner when sampling_applied is true.
 *   - Display the original and displayed point counts.
 *   - Hide completely when no sampling was applied.
 *
 * Does NOT:
 *   - Trigger re-fetching of full data.
 *   - Control chart rendering behavior.
 *
 * Dependencies:
 *   - SamplingBannerProps from ../types.
 */

import type { SamplingBannerProps } from "../types";

/**
 * Render an LTTB downsampling notification banner.
 *
 * Args:
 *   samplingApplied: Whether server-side LTTB sampling was applied.
 *   rawPointCount: Original data point count before downsampling.
 *   displayedPointCount: Number of points currently displayed.
 *
 * Returns:
 *   Alert banner element, or null if sampling was not applied.
 */
export function SamplingBanner({
  samplingApplied,
  rawPointCount,
  displayedPointCount,
}: SamplingBannerProps) {
  if (!samplingApplied) {
    return null;
  }

  return (
    <div
      data-testid="sampling-banner"
      role="alert"
      className="flex items-center gap-2 rounded-md border border-amber-200 bg-amber-50 px-4 py-3 text-sm text-amber-800"
    >
      <svg
        className="h-4 w-4 flex-shrink-0"
        fill="currentColor"
        viewBox="0 0 20 20"
        aria-hidden="true"
      >
        <path
          fillRule="evenodd"
          d="M8.485 2.495c.673-1.167 2.357-1.167 3.03 0l6.28 10.875c.673 1.167-.168 2.625-1.516 2.625H3.72c-1.347 0-2.189-1.458-1.515-2.625L8.485 2.495zM10 5a.75.75 0 01.75.75v3.5a.75.75 0 01-1.5 0v-3.5A.75.75 0 0110 5zm0 8a1 1 0 100-2 1 1 0 000 2z"
          clipRule="evenodd"
        />
      </svg>
      <span>
        LTTB downsampling applied: showing {displayedPointCount.toLocaleString()} of{" "}
        {rawPointCount.toLocaleString()} equity points.
      </span>
    </div>
  );
}
