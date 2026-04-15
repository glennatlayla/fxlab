/**
 * OrderHistory page — searchable, filterable, and paginated order history table.
 *
 * Purpose:
 *   Display execution history with filtering by symbol, side, status, execution mode,
 *   and date range. Support sorting, pagination, row expansion to show fills,
 *   and CSV export.
 *
 * Responsibilities:
 *   - Fetch and display order history via executionApi.
 *   - Manage filter state and pagination state.
 *   - Handle sorting by column headers.
 *   - Show order details and nested fills on row expansion.
 *   - Provide CSV export functionality.
 *   - Show loading and empty states.
 *   - Use useAuth to verify the user is authenticated.
 *
 * Does NOT:
 *   - Perform business logic or calculations.
 *   - Store persistent state outside React.
 *
 * Dependencies:
 *   - executionApi from @/features/execution/api.
 *   - useAuth from @/auth/useAuth.
 *
 * Example:
 *   <OrderHistory />
 */

import { useState, useEffect } from "react";
import { useAuth } from "@/auth/useAuth";
import {
  executionApi,
  type OrderHistoryQuery,
  type OrderHistoryPage,
} from "@/features/execution/api";

/**
 * Default page size for order history table.
 */
const DEFAULT_PAGE_SIZE = 50;

/**
 * Status color mapping for badges.
 */
const STATUS_COLORS: Record<string, string> = {
  filled: "bg-green-100 text-green-800",
  cancelled: "bg-red-100 text-red-800",
  rejected: "bg-red-100 text-red-800",
  pending: "bg-yellow-100 text-yellow-800",
  submitted: "bg-blue-100 text-blue-800",
};

/**
 * OrderHistory page component.
 *
 * Renders a filterable, sortable, paginated table of order history.
 * Supports row expansion to view fills and CSV export.
 *
 * Returns:
 *   JSX element containing the order history page.
 */
export default function OrderHistory() {
  useAuth(); // Ensure authenticated

  // Filter state
  const [symbol, setSymbol] = useState("");
  const [side, setSide] = useState("");
  const [status, setStatus] = useState("");
  const [mode, setMode] = useState("");
  const [dateFrom, setDateFrom] = useState("");
  const [dateTo, setDateTo] = useState("");

  // Sorting state
  const [sortBy, setSortBy] = useState<string | null>(null);
  const [sortDir, setSortDir] = useState<"asc" | "desc">("asc");

  // Pagination state
  const [page, setPage] = useState(1);

  // Data and loading state
  const [data, setData] = useState<OrderHistoryPage | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Expanded rows for fill details
  const [expandedRows, setExpandedRows] = useState<Set<string>>(new Set());

  /**
   * Fetch order history when filters, sort, or page changes.
   */
  useEffect(() => {
    const fetchOrders = async () => {
      setLoading(true);
      setError(null);
      try {
        const query: OrderHistoryQuery = {
          page,
          page_size: DEFAULT_PAGE_SIZE,
        };
        if (symbol) query.symbol = symbol;
        if (side) query.side = side;
        if (status) query.status = status;
        if (mode) query.execution_mode = mode;
        if (dateFrom) query.date_from = dateFrom;
        if (dateTo) query.date_to = dateTo;
        if (sortBy) {
          query.sort_by = sortBy;
          query.sort_dir = sortDir;
        }

        const result = await executionApi.getOrderHistory(query);
        setData(result);
      } catch (err) {
        const msg = err instanceof Error ? err.message : String(err);
        setError(`Failed to fetch orders: ${msg}`);
      } finally {
        setLoading(false);
      }
    };

    fetchOrders();
  }, [symbol, side, status, mode, dateFrom, dateTo, sortBy, sortDir, page]);

  /**
   * Handle column header click to toggle sort.
   */
  const handleSort = (field: string) => {
    if (sortBy === field) {
      setSortDir(sortDir === "asc" ? "desc" : "asc");
    } else {
      setSortBy(field);
      setSortDir("asc");
    }
    setPage(1); // Reset to first page on sort change
  };

  /**
   * Handle search/filter button click.
   */
  const handleSearch = () => {
    setPage(1); // Reset to first page on filter change
  };

  /**
   * Handle CSV export.
   */
  const handleExport = async () => {
    try {
      const query: OrderHistoryQuery = {};
      if (symbol) query.symbol = symbol;
      if (side) query.side = side;
      if (status) query.status = status;
      if (mode) query.execution_mode = mode;
      if (dateFrom) query.date_from = dateFrom;
      if (dateTo) query.date_to = dateTo;

      const blob = await executionApi.exportOrdersCsv(query);
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = `orders-${new Date().toISOString().split("T")[0]}.csv`;
      a.click();
      URL.revokeObjectURL(url);
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err);
      setError(`Export failed: ${msg}`);
    }
  };

  /**
   * Toggle row expansion.
   */
  const toggleRowExpanded = (orderId: string) => {
    const newExpanded = new Set(expandedRows);
    if (newExpanded.has(orderId)) {
      newExpanded.delete(orderId);
    } else {
      newExpanded.add(orderId);
    }
    setExpandedRows(newExpanded);
  };

  /**
   * Get status badge color.
   */
  const getStatusColor = (orderStatus: string): string => {
    return STATUS_COLORS[orderStatus.toLowerCase()] || "bg-gray-100 text-gray-800";
  };

  return (
    <div className="space-y-6" data-testid="order-history">
      <div>
        <h1 className="text-2xl font-bold text-surface-900">Order History</h1>
        <p className="mt-1 text-sm text-surface-500">Search and filter your execution history</p>
      </div>

      {/* Filters */}
      <div className="card space-y-4">
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
          <div>
            <label className="block text-sm font-medium text-surface-700">Symbol</label>
            <input
              type="text"
              placeholder="e.g., AAPL"
              value={symbol}
              onChange={(e) => setSymbol(e.target.value.toUpperCase())}
              data-testid="filter-symbol"
              className="mt-1 w-full rounded border border-surface-300 px-3 py-2 text-sm"
            />
          </div>

          <div>
            <label className="block text-sm font-medium text-surface-700">Side</label>
            <select
              value={side}
              onChange={(e) => setSide(e.target.value)}
              data-testid="filter-side"
              className="mt-1 w-full rounded border border-surface-300 px-3 py-2 text-sm"
            >
              <option value="">All sides</option>
              <option value="BUY">Buy</option>
              <option value="SELL">Sell</option>
            </select>
          </div>

          <div>
            <label className="block text-sm font-medium text-surface-700">Status</label>
            <select
              value={status}
              onChange={(e) => setStatus(e.target.value)}
              data-testid="filter-status"
              className="mt-1 w-full rounded border border-surface-300 px-3 py-2 text-sm"
            >
              <option value="">All statuses</option>
              <option value="filled">Filled</option>
              <option value="cancelled">Cancelled</option>
              <option value="rejected">Rejected</option>
              <option value="pending">Pending</option>
              <option value="submitted">Submitted</option>
            </select>
          </div>

          <div>
            <label className="block text-sm font-medium text-surface-700">Execution Mode</label>
            <select
              value={mode}
              onChange={(e) => setMode(e.target.value)}
              data-testid="filter-mode"
              className="mt-1 w-full rounded border border-surface-300 px-3 py-2 text-sm"
            >
              <option value="">All modes</option>
              <option value="LIVE">Live</option>
              <option value="PAPER">Paper</option>
              <option value="BACKTEST">Backtest</option>
            </select>
          </div>
        </div>

        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          <div>
            <label className="block text-sm font-medium text-surface-700">From</label>
            <input
              type="date"
              value={dateFrom}
              onChange={(e) => setDateFrom(e.target.value)}
              data-testid="filter-date-from"
              className="mt-1 w-full rounded border border-surface-300 px-3 py-2 text-sm"
            />
          </div>

          <div>
            <label className="block text-sm font-medium text-surface-700">To</label>
            <input
              type="date"
              value={dateTo}
              onChange={(e) => setDateTo(e.target.value)}
              data-testid="filter-date-to"
              className="mt-1 w-full rounded border border-surface-300 px-3 py-2 text-sm"
            />
          </div>
        </div>

        <div className="flex gap-2">
          <button
            onClick={handleSearch}
            data-testid="search-button"
            className="rounded bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700"
          >
            Search
          </button>
          <button
            onClick={handleExport}
            data-testid="export-csv-button"
            className="rounded border border-surface-300 px-4 py-2 text-sm font-medium text-surface-700 hover:bg-surface-50"
          >
            Export CSV
          </button>
        </div>

        {error && <div className="rounded bg-red-50 p-3 text-sm text-red-700">{error}</div>}
      </div>

      {/* Table */}
      {loading ? (
        <div
          data-testid="loading-state"
          className="rounded border border-surface-200 bg-surface-50 p-8 text-center text-surface-600"
        >
          Loading orders...
        </div>
      ) : !data || data.items.length === 0 ? (
        <div
          data-testid="empty-state"
          className="rounded border border-surface-200 bg-surface-50 p-8 text-center text-surface-600"
        >
          No orders found
        </div>
      ) : (
        <div className="overflow-x-auto">
          <table
            data-testid="order-table"
            className="w-full border-collapse border border-surface-200 bg-white"
          >
            <thead className="bg-surface-100">
              <tr>
                <th className="border border-surface-200 px-4 py-2 text-left text-xs font-semibold uppercase text-surface-700">
                  <button
                    onClick={() => handleSort("symbol")}
                    data-testid="sort-header-symbol"
                    className="w-full text-left hover:underline"
                  >
                    Symbol {sortBy === "symbol" && (sortDir === "asc" ? "↑" : "↓")}
                  </button>
                </th>
                <th className="border border-surface-200 px-4 py-2 text-left text-xs font-semibold uppercase text-surface-700">
                  <button
                    onClick={() => handleSort("side")}
                    data-testid="sort-header-side"
                    className="w-full text-left hover:underline"
                  >
                    Side {sortBy === "side" && (sortDir === "asc" ? "↑" : "↓")}
                  </button>
                </th>
                <th className="border border-surface-200 px-4 py-2 text-left text-xs font-semibold uppercase text-surface-700">
                  <button
                    onClick={() => handleSort("order_type")}
                    data-testid="sort-header-order_type"
                    className="w-full text-left hover:underline"
                  >
                    Type {sortBy === "order_type" && (sortDir === "asc" ? "↑" : "↓")}
                  </button>
                </th>
                <th className="border border-surface-200 px-4 py-2 text-right text-xs font-semibold uppercase text-surface-700">
                  <button
                    onClick={() => handleSort("quantity")}
                    data-testid="sort-header-quantity"
                    className="w-full text-right hover:underline"
                  >
                    Qty {sortBy === "quantity" && (sortDir === "asc" ? "↑" : "↓")}
                  </button>
                </th>
                <th className="border border-surface-200 px-4 py-2 text-right text-xs font-semibold uppercase text-surface-700">
                  <button
                    onClick={() => handleSort("filled_quantity")}
                    data-testid="sort-header-filled_quantity"
                    className="w-full text-right hover:underline"
                  >
                    Filled {sortBy === "filled_quantity" && (sortDir === "asc" ? "↑" : "↓")}
                  </button>
                </th>
                <th className="border border-surface-200 px-4 py-2 text-right text-xs font-semibold uppercase text-surface-700">
                  Price
                </th>
                <th className="border border-surface-200 px-4 py-2 text-left text-xs font-semibold uppercase text-surface-700">
                  Status
                </th>
                <th className="border border-surface-200 px-4 py-2 text-left text-xs font-semibold uppercase text-surface-700">
                  Mode
                </th>
                <th className="border border-surface-200 px-4 py-2 text-left text-xs font-semibold uppercase text-surface-700">
                  Submitted At
                </th>
                <th className="border border-surface-200 px-4 py-2 text-center text-xs font-semibold uppercase text-surface-700">
                  Expand
                </th>
              </tr>
            </thead>
            <tbody>
              {data.items.map((order) => {
                const isExpanded = expandedRows.has(order.order_id);
                return (
                  <tr key={order.order_id} data-testid={`order-row-${order.order_id}`}>
                    <td className="border border-surface-200 px-4 py-2 font-semibold text-surface-900">
                      {order.symbol}
                    </td>
                    <td className="border border-surface-200 px-4 py-2 text-surface-700">
                      {order.side}
                    </td>
                    <td className="border border-surface-200 px-4 py-2 text-sm text-surface-600">
                      {order.order_type}
                    </td>
                    <td className="border border-surface-200 px-4 py-2 text-right text-surface-700">
                      {order.quantity}
                    </td>
                    <td className="border border-surface-200 px-4 py-2 text-right text-surface-700">
                      {order.filled_quantity}
                    </td>
                    <td className="border border-surface-200 px-4 py-2 text-right text-surface-700">
                      {order.average_fill_price ? `$${order.average_fill_price.toFixed(2)}` : "—"}
                    </td>
                    <td className="border border-surface-200 px-4 py-2">
                      <span
                        className={`inline-block rounded px-2 py-1 text-xs font-semibold ${getStatusColor(order.status)}`}
                      >
                        {order.status}
                      </span>
                    </td>
                    <td className="border border-surface-200 px-4 py-2 text-sm text-surface-600">
                      {order.execution_mode}
                    </td>
                    <td className="border border-surface-200 px-4 py-2 text-sm text-surface-600">
                      {order.submitted_at ? new Date(order.submitted_at).toLocaleString() : "—"}
                    </td>
                    <td className="border border-surface-200 px-4 py-2 text-center">
                      <button
                        onClick={() => toggleRowExpanded(order.order_id)}
                        className="text-blue-600 hover:underline"
                      >
                        {isExpanded ? "▼" : "▶"}
                      </button>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>

          {/* Expanded rows for fills */}
          {data.items.map((order) => {
            const isExpanded = expandedRows.has(order.order_id);
            if (!isExpanded) return null;

            return (
              <div
                key={`expanded-${order.order_id}`}
                className="border border-surface-200 bg-surface-50 p-4"
              >
                <p className="mb-2 text-sm font-semibold text-surface-900">Fills:</p>
                {order.fills.length === 0 ? (
                  <p className="text-sm text-surface-600">No fills</p>
                ) : (
                  <table className="w-full text-sm">
                    <thead>
                      <tr className="border-b border-surface-200">
                        <th className="px-2 py-1 text-left text-xs font-semibold uppercase text-surface-700">
                          Fill ID
                        </th>
                        <th className="px-2 py-1 text-right text-xs font-semibold uppercase text-surface-700">
                          Price
                        </th>
                        <th className="px-2 py-1 text-right text-xs font-semibold uppercase text-surface-700">
                          Quantity
                        </th>
                        <th className="px-2 py-1 text-right text-xs font-semibold uppercase text-surface-700">
                          Commission
                        </th>
                        <th className="px-2 py-1 text-left text-xs font-semibold uppercase text-surface-700">
                          Filled At
                        </th>
                      </tr>
                    </thead>
                    <tbody>
                      {order.fills.map((fill) => (
                        <tr key={fill.fill_id} className="border-b border-surface-200">
                          <td className="px-2 py-1 font-mono text-xs text-surface-600">
                            {fill.fill_id.substring(0, 8)}...
                          </td>
                          <td className="px-2 py-1 text-right text-surface-700">
                            ${fill.price.toFixed(2)}
                          </td>
                          <td className="px-2 py-1 text-right text-surface-700">{fill.quantity}</td>
                          <td className="px-2 py-1 text-right text-surface-700">
                            ${fill.commission.toFixed(2)}
                          </td>
                          <td className="px-2 py-1 text-surface-600">
                            {new Date(fill.filled_at).toLocaleString()}
                          </td>
                        </tr>
                      ))}
                    </tbody>
                  </table>
                )}
              </div>
            );
          })}
        </div>
      )}

      {/* Pagination */}
      {data && data.total_pages > 1 && (
        <div
          data-testid="pagination"
          className="flex items-center justify-between rounded border border-surface-200 bg-white p-4"
        >
          <button
            onClick={() => setPage(Math.max(1, page - 1))}
            disabled={page === 1}
            data-testid="prev-page"
            className="rounded border border-surface-300 px-3 py-1 text-sm disabled:opacity-50"
          >
            Previous
          </button>

          <span data-testid="page-info" className="text-sm text-surface-600">
            Page {page} of {data.total_pages} ({data.total} total)
          </span>

          <button
            onClick={() => setPage(Math.min(data.total_pages, page + 1))}
            disabled={page === data.total_pages}
            data-testid="next-page"
            className="rounded border border-surface-300 px-3 py-1 text-sm disabled:opacity-50"
          >
            Next
          </button>
        </div>
      )}
    </div>
  );
}
