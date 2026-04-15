/**
 * TradeBlotter — virtualized trade records table with filtering.
 *
 * Purpose:
 *   Renders the full trade history in a scrollable, virtualized table
 *   using TanStack Virtual. Supports filtering by symbol, side, fold,
 *   and regime.
 *
 * Responsibilities:
 *   - Render trade records in a virtual-scrolled table.
 *   - Provide filter controls for symbol, side, fold, and regime.
 *   - Display total trade count.
 *   - Provide a download button for the trade data.
 *   - Prevent horizontal overflow.
 *
 * Does NOT:
 *   - Fetch trade data from the API.
 *   - Perform the actual download (delegates to onDownload callback).
 *
 * Dependencies:
 *   - TradeBlotterProps from ../types.
 *   - @tanstack/react-virtual for row virtualization.
 */

import { useRef, useMemo, useCallback, memo } from "react";
import { useVirtualizer } from "@tanstack/react-virtual";
import type { TradeBlotterProps } from "../types";
import { DownloadDataButton } from "./DownloadDataButton";
import {
  TRADE_BLOTTER_ROW_HEIGHT,
  TRADE_BLOTTER_VIEWPORT_HEIGHT,
  TRADE_BLOTTER_OVERSCAN,
} from "../constants";

/**
 * Render the trade blotter table.
 *
 * Args:
 *   trades: Array of TradeRecord objects.
 *   tradesTruncated: Whether the backend truncated the list.
 *   totalTradeCount: Total number of trades before truncation.
 *   filters: Current filter state.
 *   onFiltersChange: Callback when filters are updated.
 *   onDownload: Callback to trigger data export.
 *
 * Returns:
 *   Virtualized trade table element.
 */
export const TradeBlotter = memo(function TradeBlotter({
  trades,
  tradesTruncated: _tradesTruncated,
  totalTradeCount,
  filters,
  onFiltersChange,
  onDownload,
  isDownloading = false,
}: TradeBlotterProps) {
  const parentRef = useRef<HTMLDivElement>(null);

  // Apply client-side filters
  const filteredTrades = useMemo(() => {
    return trades.filter((t) => {
      if (filters.symbol && t.symbol !== filters.symbol) return false;
      if (filters.side && t.side !== filters.side) return false;
      if (filters.fold_index !== null && t.fold_index !== filters.fold_index) return false;
      if (filters.regime && t.regime !== filters.regime) return false;
      return true;
    });
  }, [trades, filters]);

  const rowVirtualizer = useVirtualizer({
    count: filteredTrades.length,
    getScrollElement: () => parentRef.current,
    estimateSize: () => TRADE_BLOTTER_ROW_HEIGHT,
    overscan: TRADE_BLOTTER_OVERSCAN,
  });

  // Memoized filter handlers to prevent unnecessary re-renders in virtualized list.
  const handleSideFilterChange = useCallback(
    (e: React.ChangeEvent<HTMLSelectElement>) => {
      onFiltersChange({
        ...filters,
        side: (e.target.value || null) as "buy" | "sell" | null,
      });
    },
    [filters, onFiltersChange],
  );

  const handleSymbolFilterChange = useCallback(
    (e: React.ChangeEvent<HTMLSelectElement>) => {
      onFiltersChange({
        ...filters,
        symbol: e.target.value || null,
      });
    },
    [filters, onFiltersChange],
  );

  // Extract unique values for filter dropdowns
  const uniqueSymbols = useMemo(() => [...new Set(trades.map((t) => t.symbol))].sort(), [trades]);

  return (
    <div data-testid="trade-blotter" className="overflow-hidden rounded-lg border border-slate-200">
      {/* Header bar with filters and download */}
      <div className="flex flex-wrap items-center gap-3 border-b border-slate-200 bg-slate-50 px-4 py-2">
        <span className="text-sm font-medium text-slate-700">
          Trades: {totalTradeCount.toLocaleString()}
        </span>

        {/* Side filter */}
        <select
          data-testid="filter-side"
          aria-label="Filter by trade side"
          value={filters.side ?? ""}
          onChange={handleSideFilterChange}
          className="rounded border border-slate-300 px-2 py-1 text-xs"
        >
          <option value="">All Sides</option>
          <option value="buy">Buy</option>
          <option value="sell">Sell</option>
        </select>

        {/* Symbol filter */}
        <select
          data-testid="filter-symbol"
          aria-label="Filter by symbol"
          value={filters.symbol ?? ""}
          onChange={handleSymbolFilterChange}
          className="rounded border border-slate-300 px-2 py-1 text-xs"
        >
          <option value="">All Symbols</option>
          {uniqueSymbols.map((sym) => (
            <option key={sym} value={sym}>
              {sym}
            </option>
          ))}
        </select>

        <div className="ml-auto">
          <DownloadDataButton onDownload={onDownload} label="Download" isLoading={isDownloading} />
        </div>
      </div>

      {/* Column headers */}
      <div className="grid grid-cols-[80px_60px_60px_80px_80px_80px_80px] gap-1 border-b border-slate-200 bg-slate-100 px-4 py-2 text-xs font-semibold text-slate-600">
        <span>Symbol</span>
        <span>Side</span>
        <span>Qty</span>
        <span>Entry</span>
        <span>Exit</span>
        <span>PnL</span>
        <span>Regime</span>
      </div>

      {/* Virtualized rows */}
      <div
        ref={parentRef}
        className="overflow-auto"
        style={{ height: TRADE_BLOTTER_VIEWPORT_HEIGHT }}
      >
        <div
          style={{
            height: `${rowVirtualizer.getTotalSize()}px`,
            width: "100%",
            position: "relative",
          }}
        >
          {rowVirtualizer.getVirtualItems().map((virtualRow) => {
            const trade = filteredTrades[virtualRow.index];
            return (
              <div
                key={trade.id}
                data-testid={`trade-row-${trade.id}`}
                className="absolute left-0 top-0 grid w-full grid-cols-[80px_60px_60px_80px_80px_80px_80px] gap-1 border-b border-slate-100 px-4 text-xs"
                style={{
                  height: `${virtualRow.size}px`,
                  transform: `translateY(${virtualRow.start}px)`,
                }}
              >
                <span className="flex items-center truncate font-medium">{trade.symbol}</span>
                <span
                  className={`flex items-center ${trade.side === "buy" ? "text-emerald-600" : "text-red-600"}`}
                >
                  {trade.side}
                </span>
                <span className="flex items-center tabular-nums">{trade.quantity}</span>
                <span className="flex items-center tabular-nums">
                  {trade.entry_price.toFixed(2)}
                </span>
                <span className="flex items-center tabular-nums">
                  {trade.exit_price?.toFixed(2) ?? "—"}
                </span>
                <span
                  className={`flex items-center font-medium tabular-nums ${trade.pnl >= 0 ? "text-emerald-600" : "text-red-600"}`}
                >
                  {trade.pnl >= 0 ? "+" : ""}
                  {trade.pnl.toFixed(2)}
                </span>
                <span className="flex items-center truncate text-slate-500">
                  {trade.regime ?? "—"}
                </span>
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
});
