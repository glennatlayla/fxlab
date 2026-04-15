/**
 * TradesTruncatedBanner — warning banner for truncated trade lists.
 *
 * Purpose:
 *   Notifies the user when the trade blotter shows a subset of total
 *   trades (backend caps at 5,000) and offers a download option for
 *   the full dataset.
 *
 * Responsibilities:
 *   - Render an alert banner when trades_truncated is true.
 *   - Display the total trade count.
 *   - Provide a download button for the full dataset.
 *   - Hide completely when trades were not truncated.
 *
 * Does NOT:
 *   - Perform the actual download (delegates to onDownload callback).
 *   - Filter or paginate trades.
 *
 * Dependencies:
 *   - TradesTruncatedBannerProps from ../types.
 */

import type { TradesTruncatedBannerProps } from "../types";

/**
 * Render a trades truncation warning with download option.
 *
 * Args:
 *   tradesTruncated: Whether trades were truncated by the backend.
 *   totalTradeCount: Total number of trades before truncation.
 *   onDownload: Callback to trigger full dataset download.
 *
 * Returns:
 *   Alert banner element, or null if trades were not truncated.
 */
export function TradesTruncatedBanner({
  tradesTruncated,
  totalTradeCount,
  onDownload,
}: TradesTruncatedBannerProps) {
  if (!tradesTruncated) {
    return null;
  }

  return (
    <div
      data-testid="trades-truncated-banner"
      role="alert"
      className="flex items-center justify-between gap-2 rounded-md border border-orange-200 bg-orange-50 px-4 py-3 text-sm text-orange-800"
    >
      <span>Showing first 5,000 of {totalTradeCount.toLocaleString()} total trades.</span>
      <button
        type="button"
        onClick={onDownload}
        className="rounded bg-orange-600 px-3 py-1 text-xs font-medium text-white hover:bg-orange-700 focus:outline-none focus:ring-2 focus:ring-orange-500 focus:ring-offset-1"
      >
        Download All
      </button>
    </div>
  );
}
