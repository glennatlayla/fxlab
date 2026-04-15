/**
 * ExecutionReport page — aggregated execution metrics and breakdown tables.
 *
 * Purpose:
 *   Display execution analysis summary with metrics cards, per-symbol breakdown,
 *   and per-execution-mode breakdown. Support date range selection with presets.
 *
 * Responsibilities:
 *   - Fetch execution report via executionApi.
 *   - Manage date range state and preset buttons.
 *   - Render summary cards with key metrics.
 *   - Display per-symbol and per-mode breakdown tables.
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
 *   <ExecutionReport />
 */

import { useState, useEffect } from "react";
import { useAuth } from "@/auth/useAuth";
import { executionApi, type ExecutionReportSummary } from "@/features/execution/api";

/**
 * Get today's date in YYYY-MM-DD format.
 */
function getToday(): string {
  const now = new Date();
  now.setHours(0, 0, 0, 0);
  return now.toISOString().split("T")[0];
}

/**
 * Get a date N days ago in YYYY-MM-DD format.
 */
function getDaysAgo(n: number): string {
  const now = new Date();
  now.setHours(0, 0, 0, 0);
  now.setDate(now.getDate() - n);
  return now.toISOString().split("T")[0];
}

/**
 * Get the start of the current week (Monday) in YYYY-MM-DD format.
 */
function getWeekStart(): string {
  const now = new Date();
  now.setHours(0, 0, 0, 0);
  const day = now.getDay();
  const diff = now.getDate() - day + (day === 0 ? -6 : 1);
  now.setDate(diff);
  return now.toISOString().split("T")[0];
}

/**
 * Get the start of the current month in YYYY-MM-DD format.
 */
function getMonthStart(): string {
  const now = new Date();
  now.setHours(0, 0, 0, 0);
  now.setDate(1);
  return now.toISOString().split("T")[0];
}

/**
 * ExecutionReport page component.
 *
 * Renders execution report summary with metrics cards and breakdowns.
 *
 * Returns:
 *   JSX element containing the execution report page.
 */
export default function ExecutionReport() {
  useAuth(); // Ensure authenticated

  // Date range state
  const today = getToday();
  const [dateFrom, setDateFrom] = useState(getDaysAgo(7)); // Default to past week
  const [dateTo, setDateTo] = useState(today);

  // Data and loading state
  const [data, setData] = useState<ExecutionReportSummary | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  /**
   * Fetch execution report when date range changes.
   */
  useEffect(() => {
    const fetchReport = async () => {
      if (!dateFrom || !dateTo) return;

      setLoading(true);
      setError(null);
      try {
        const result = await executionApi.getExecutionReport({
          date_from: dateFrom,
          date_to: dateTo,
        });
        setData(result);
      } catch (err) {
        const msg = err instanceof Error ? err.message : String(err);
        setError(`Failed to fetch report: ${msg}`);
      } finally {
        setLoading(false);
      }
    };

    fetchReport();
  }, [dateFrom, dateTo]);

  /**
   * Handle preset button click.
   */
  const handlePreset = (from: string, to: string) => {
    setDateFrom(from);
    setDateTo(to);
  };

  return (
    <div className="space-y-6" data-testid="execution-report">
      <div>
        <h1 className="text-2xl font-bold text-surface-900">Execution Report</h1>
        <p className="mt-1 text-sm text-surface-500">Aggregated execution metrics and analysis</p>
      </div>

      {/* Date Range Controls */}
      <div className="card space-y-4">
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          <div>
            <label className="block text-sm font-medium text-surface-700">From</label>
            <input
              type="date"
              value={dateFrom}
              onChange={(e) => setDateFrom(e.target.value)}
              data-testid="date-from"
              className="mt-1 w-full rounded border border-surface-300 px-3 py-2 text-sm"
            />
          </div>

          <div>
            <label className="block text-sm font-medium text-surface-700">To</label>
            <input
              type="date"
              value={dateTo}
              onChange={(e) => setDateTo(e.target.value)}
              data-testid="date-to"
              className="mt-1 w-full rounded border border-surface-300 px-3 py-2 text-sm"
            />
          </div>
        </div>

        <div className="flex gap-2">
          <button
            onClick={() => handlePreset(getToday(), getToday())}
            data-testid="preset-today"
            className="rounded border border-surface-300 px-3 py-1 text-sm font-medium text-surface-700 hover:bg-surface-50"
          >
            Today
          </button>
          <button
            onClick={() => handlePreset(getWeekStart(), getToday())}
            data-testid="preset-week"
            className="rounded border border-surface-300 px-3 py-1 text-sm font-medium text-surface-700 hover:bg-surface-50"
          >
            This Week
          </button>
          <button
            onClick={() => handlePreset(getMonthStart(), getToday())}
            data-testid="preset-month"
            className="rounded border border-surface-300 px-3 py-1 text-sm font-medium text-surface-700 hover:bg-surface-50"
          >
            This Month
          </button>
        </div>

        {error && <div className="rounded bg-red-50 p-3 text-sm text-red-700">{error}</div>}
      </div>

      {/* Summary Cards */}
      {loading ? (
        <div
          data-testid="loading-state"
          className="rounded border border-surface-200 bg-surface-50 p-8 text-center text-surface-600"
        >
          Loading report...
        </div>
      ) : !data ? (
        <div
          data-testid="empty-state"
          className="rounded border border-surface-200 bg-surface-50 p-8 text-center text-surface-600"
        >
          No data available for this date range
        </div>
      ) : (
        <>
          <div
            data-testid="summary-cards"
            className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4"
          >
            <div className="card" data-testid="card-total-orders">
              <p className="text-sm text-surface-500">Total Orders</p>
              <p className="mt-2 text-3xl font-bold text-surface-900">{data.total_orders}</p>
            </div>

            <div className="card" data-testid="card-fill-rate">
              <p className="text-sm text-surface-500">Fill Rate</p>
              <p className="mt-2 text-3xl font-bold text-surface-900">
                {(data.fill_rate * 100).toFixed(1)}%
              </p>
            </div>

            <div className="card" data-testid="card-total-volume">
              <p className="text-sm text-surface-500">Total Volume</p>
              <p className="mt-2 text-3xl font-bold text-surface-900">
                {data.total_volume.toLocaleString()}
              </p>
            </div>

            <div className="card" data-testid="card-total-commission">
              <p className="text-sm text-surface-500">Total Commission</p>
              <p className="mt-2 text-3xl font-bold text-surface-900">
                ${data.total_commission.toFixed(2)}
              </p>
            </div>
          </div>

          {/* Additional Metrics */}
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
            <div className="card">
              <p className="text-sm text-surface-500">Filled Orders</p>
              <p className="mt-2 text-2xl font-bold text-green-600">{data.filled_orders}</p>
            </div>

            <div className="card">
              <p className="text-sm text-surface-500">Cancelled Orders</p>
              <p className="mt-2 text-2xl font-bold text-yellow-600">{data.cancelled_orders}</p>
            </div>

            <div className="card">
              <p className="text-sm text-surface-500">Rejected Orders</p>
              <p className="mt-2 text-2xl font-bold text-red-600">{data.rejected_orders}</p>
            </div>
          </div>

          {/* Latency Percentiles */}
          {(data.latency_p50_ms || data.latency_p95_ms || data.latency_p99_ms) && (
            <div className="card">
              <p className="mb-4 text-sm font-semibold text-surface-900">Latency Percentiles</p>
              <div className="grid grid-cols-3 gap-4">
                {data.latency_p50_ms !== null && (
                  <div>
                    <p className="text-xs text-surface-500">p50</p>
                    <p className="mt-1 text-lg font-semibold text-surface-900">
                      {data.latency_p50_ms.toFixed(0)}ms
                    </p>
                  </div>
                )}
                {data.latency_p95_ms !== null && (
                  <div>
                    <p className="text-xs text-surface-500">p95</p>
                    <p className="mt-1 text-lg font-semibold text-surface-900">
                      {data.latency_p95_ms.toFixed(0)}ms
                    </p>
                  </div>
                )}
                {data.latency_p99_ms !== null && (
                  <div>
                    <p className="text-xs text-surface-500">p99</p>
                    <p className="mt-1 text-lg font-semibold text-surface-900">
                      {data.latency_p99_ms.toFixed(0)}ms
                    </p>
                  </div>
                )}
              </div>
            </div>
          )}

          {/* Symbol Breakdown */}
          {data.by_symbol.length > 0 && (
            <div className="card">
              <p className="mb-4 text-sm font-semibold text-surface-900">By Symbol</p>
              <div className="overflow-x-auto">
                <table data-testid="symbol-table" className="w-full text-sm">
                  <thead className="border-b border-surface-200">
                    <tr>
                      <th className="px-4 py-2 text-left text-xs font-semibold uppercase text-surface-700">
                        Symbol
                      </th>
                      <th className="px-4 py-2 text-right text-xs font-semibold uppercase text-surface-700">
                        Orders
                      </th>
                      <th className="px-4 py-2 text-right text-xs font-semibold uppercase text-surface-700">
                        Filled
                      </th>
                      <th className="px-4 py-2 text-right text-xs font-semibold uppercase text-surface-700">
                        Fill Rate
                      </th>
                      <th className="px-4 py-2 text-right text-xs font-semibold uppercase text-surface-700">
                        Volume
                      </th>
                      <th className="px-4 py-2 text-right text-xs font-semibold uppercase text-surface-700">
                        Avg Fill Price
                      </th>
                      {data.by_symbol.some((s) => s.avg_slippage_pct !== null) && (
                        <th className="px-4 py-2 text-right text-xs font-semibold uppercase text-surface-700">
                          Avg Slippage
                        </th>
                      )}
                    </tr>
                  </thead>
                  <tbody>
                    {data.by_symbol.map((symbol) => (
                      <tr
                        key={symbol.symbol}
                        data-testid={`symbol-row-${symbol.symbol}`}
                        className="border-b border-surface-100 hover:bg-surface-50"
                      >
                        <td className="px-4 py-2 font-semibold text-surface-900">
                          {symbol.symbol}
                        </td>
                        <td className="px-4 py-2 text-right text-surface-700">
                          {symbol.total_orders}
                        </td>
                        <td className="px-4 py-2 text-right text-surface-700">
                          {symbol.filled_orders}
                        </td>
                        <td className="px-4 py-2 text-right text-surface-700">
                          {(symbol.fill_rate * 100).toFixed(1)}%
                        </td>
                        <td className="px-4 py-2 text-right text-surface-700">
                          {symbol.total_volume.toLocaleString()}
                        </td>
                        <td className="px-4 py-2 text-right text-surface-700">
                          {symbol.avg_fill_price ? `$${symbol.avg_fill_price.toFixed(2)}` : "—"}
                        </td>
                        {data.by_symbol.some((s) => s.avg_slippage_pct !== null) && (
                          <td className="px-4 py-2 text-right text-surface-700">
                            {symbol.avg_slippage_pct
                              ? `${(symbol.avg_slippage_pct * 100).toFixed(2)}%`
                              : "—"}
                          </td>
                        )}
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}

          {/* Mode Breakdown */}
          {data.by_execution_mode.length > 0 && (
            <div className="card">
              <p className="mb-4 text-sm font-semibold text-surface-900">By Execution Mode</p>
              <div className="overflow-x-auto">
                <table data-testid="mode-table" className="w-full text-sm">
                  <thead className="border-b border-surface-200">
                    <tr>
                      <th className="px-4 py-2 text-left text-xs font-semibold uppercase text-surface-700">
                        Mode
                      </th>
                      <th className="px-4 py-2 text-right text-xs font-semibold uppercase text-surface-700">
                        Orders
                      </th>
                      <th className="px-4 py-2 text-right text-xs font-semibold uppercase text-surface-700">
                        Filled
                      </th>
                      <th className="px-4 py-2 text-right text-xs font-semibold uppercase text-surface-700">
                        Fill Rate
                      </th>
                      <th className="px-4 py-2 text-right text-xs font-semibold uppercase text-surface-700">
                        Volume
                      </th>
                    </tr>
                  </thead>
                  <tbody>
                    {data.by_execution_mode.map((mode) => (
                      <tr
                        key={mode.execution_mode}
                        data-testid={`mode-row-${mode.execution_mode}`}
                        className="border-b border-surface-100 hover:bg-surface-50"
                      >
                        <td className="px-4 py-2 font-semibold text-surface-900">
                          {mode.execution_mode}
                        </td>
                        <td className="px-4 py-2 text-right text-surface-700">
                          {mode.total_orders}
                        </td>
                        <td className="px-4 py-2 text-right text-surface-700">
                          {mode.filled_orders}
                        </td>
                        <td className="px-4 py-2 text-right text-surface-700">
                          {(mode.fill_rate * 100).toFixed(1)}%
                        </td>
                        <td className="px-4 py-2 text-right text-surface-700">
                          {mode.total_volume.toLocaleString()}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </div>
          )}
        </>
      )}
    </div>
  );
}
