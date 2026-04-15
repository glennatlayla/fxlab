/**
 * StaleDataIndicator — "data stale as of X" warning per spec §8.1.
 *
 * Purpose:
 *   Render a visible warning when poll data is stale due to failed
 *   polling requests exceeding STALE_INDICATOR_THRESHOLD_MS.
 *
 * Responsibilities:
 *   - Show timestamp of last successful poll.
 *   - Provide visual warning using amber/warning colour.
 *   - Use safeParseDateMs for consistent, safe date formatting.
 *
 * Does NOT:
 *   - Determine staleness (parent decides via isStale flag).
 *   - Trigger refresh (parent provides onRefresh).
 */

import type { StaleDataIndicatorProps } from "../types";
import { safeParseDateMs } from "../services/RunMonitorService";

/**
 * Render a stale data warning.
 *
 * Args:
 *   lastUpdatedAt: ISO-8601 timestamp of the last successful poll.
 *   className: Optional additional CSS class names.
 */
export function StaleDataIndicator({ lastUpdatedAt, className = "" }: StaleDataIndicatorProps) {
  const ms = safeParseDateMs(lastUpdatedAt);
  const formattedTime = ms !== null ? new Date(ms).toLocaleTimeString() : lastUpdatedAt;

  return (
    <div
      className={`flex items-center gap-2 rounded-md border border-yellow-600 bg-yellow-900/30 px-3 py-2 text-sm text-yellow-300 ${className}`.trim()}
      data-testid="stale-data-indicator"
      role="alert"
      aria-live="polite"
    >
      <svg
        className="h-4 w-4 flex-shrink-0"
        fill="currentColor"
        viewBox="0 0 20 20"
        aria-hidden="true"
      >
        <path
          fillRule="evenodd"
          d="M8.485 2.495c.673-1.167 2.357-1.167 3.03 0l6.28 10.875c.673 1.167-.168 2.625-1.516 2.625H3.72c-1.347 0-2.189-1.458-1.515-2.625L8.485 2.495zM10 5a.75.75 0 01.75.75v3.5a.75.75 0 01-1.5 0v-3.5A.75.75 0 0110 5zm0 9a1 1 0 100-2 1 1 0 000 2z"
          clipRule="evenodd"
        />
      </svg>
      <span>Data stale as of {formattedTime}</span>
    </div>
  );
}
