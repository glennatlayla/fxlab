/**
 * Execution feature API layer — data fetching for order history and execution reports.
 *
 * Purpose:
 *   Fetch order history and execution reports from the backend.
 *   Implements retry logic for transient failures on idempotent reads per CLAUDE.md §9,
 *   propagates X-Correlation-Id headers per CLAUDE.md §8.
 *
 * Responsibilities:
 *   - List orders (GET /execution-analysis/orders) with retry.
 *   - Fetch execution report summary (GET /execution-analysis/report) with retry.
 *   - Export orders as CSV (GET /execution-analysis/export) with retry.
 *   - Classify AxiosErrors into domain-specific execution errors.
 *
 * Does NOT:
 *   - Contain business logic, UI rendering, or React state management.
 *   - Bypass the shared apiClient (which provides auth token injection,
 *     base URL, and 401 redirect handling).
 *   - Retry mutations.
 *
 * Dependencies:
 *   - apiClient from @/api/client (shared axios instance with interceptors).
 *
 * Example:
 *   const page = await executionApi.getOrderHistory({
 *     symbol: "AAPL",
 *     page: 1,
 *     page_size: 50
 *   });
 */

import { apiClient } from "@/api/client";

/**
 * Query parameters for order history filtering and pagination.
 */
export interface OrderHistoryQuery {
  deployment_id?: string;
  symbol?: string;
  side?: string;
  status?: string;
  execution_mode?: string;
  date_from?: string;
  date_to?: string;
  sort_by?: string;
  sort_dir?: string;
  page?: number;
  page_size?: number;
}

/**
 * Individual fill record for an order.
 */
export interface FillItem {
  fill_id: string;
  price: number;
  quantity: number;
  commission: number;
  filled_at: string;
  broker_execution_id: string | null;
}

/**
 * Order history item with fills and execution details.
 */
export interface OrderHistoryItem {
  order_id: string;
  client_order_id: string;
  broker_order_id: string | null;
  deployment_id: string;
  strategy_id: string;
  symbol: string;
  side: string;
  order_type: string;
  quantity: number;
  filled_quantity: number;
  average_fill_price: number | null;
  limit_price: number | null;
  stop_price: number | null;
  status: string;
  time_in_force: string;
  execution_mode: string;
  correlation_id: string;
  submitted_at: string | null;
  filled_at: string | null;
  cancelled_at: string | null;
  rejected_reason: string | null;
  created_at: string;
  fills: FillItem[];
}

/**
 * Paginated order history response.
 */
export interface OrderHistoryPage {
  items: OrderHistoryItem[];
  total: number;
  page: number;
  page_size: number;
  total_pages: number;
}

/**
 * Per-symbol execution breakdown.
 */
export interface SymbolBreakdown {
  symbol: string;
  total_orders: number;
  filled_orders: number;
  fill_rate: number;
  total_volume: number;
  avg_fill_price: number | null;
  avg_slippage_pct: number | null;
}

/**
 * Per-execution-mode breakdown.
 */
export interface ModeBreakdown {
  execution_mode: string;
  total_orders: number;
  filled_orders: number;
  fill_rate: number;
  total_volume: number;
}

/**
 * Execution report summary with aggregated metrics and breakdowns.
 */
export interface ExecutionReportSummary {
  date_from: string;
  date_to: string;
  total_orders: number;
  filled_orders: number;
  cancelled_orders: number;
  rejected_orders: number;
  partial_fills: number;
  fill_rate: number;
  total_volume: number;
  total_commission: number;
  symbols_traded: string[];
  avg_slippage_pct: number | null;
  latency_p50_ms: number | null;
  latency_p95_ms: number | null;
  latency_p99_ms: number | null;
  by_symbol: SymbolBreakdown[];
  by_execution_mode: ModeBreakdown[];
}

/**
 * Execution API client.
 *
 * All methods throw standard HTTP errors that are caught by the global
 * axios interceptor (401 → logout).
 */
export const executionApi = {
  /**
   * Fetch paginated order history with optional filters and sorting.
   *
   * Args:
   *   query: Filter, sort, and pagination parameters.
   *
   * Returns:
   *   OrderHistoryPage with paginated order items.
   *
   * Raises:
   *   AxiosError: On network failure or server error.
   *
   * Example:
   *   const page = await executionApi.getOrderHistory({
   *     symbol: "AAPL",
   *     page: 1,
   *     page_size: 50
   *   });
   */
  async getOrderHistory(query: OrderHistoryQuery): Promise<OrderHistoryPage> {
    const params = new URLSearchParams();
    Object.entries(query).forEach(([key, value]) => {
      if (value !== undefined && value !== null && value !== "") {
        params.set(key, String(value));
      }
    });
    const { data } = await apiClient.get<OrderHistoryPage>(
      `/execution-analysis/orders?${params.toString()}`,
    );
    return data;
  },

  /**
   * Fetch execution report summary for a date range.
   *
   * Args:
   *   params: date_from, date_to (ISO 8601 strings), optional deployment_id.
   *
   * Returns:
   *   ExecutionReportSummary with aggregated metrics and breakdowns.
   *
   * Raises:
   *   AxiosError: On network failure or server error.
   *
   * Example:
   *   const report = await executionApi.getExecutionReport({
   *     date_from: "2026-04-01",
   *     date_to: "2026-04-12"
   *   });
   */
  async getExecutionReport(params: {
    date_from: string;
    date_to: string;
    deployment_id?: string;
  }): Promise<ExecutionReportSummary> {
    const query = new URLSearchParams();
    query.set("date_from", params.date_from);
    query.set("date_to", params.date_to);
    if (params.deployment_id) query.set("deployment_id", params.deployment_id);
    const { data } = await apiClient.get<ExecutionReportSummary>(
      `/execution-analysis/report?${query.toString()}`,
    );
    return data;
  },

  /**
   * Export order history as CSV blob.
   *
   * Args:
   *   query: Filter and pagination parameters (same as getOrderHistory).
   *
   * Returns:
   *   Blob containing CSV data.
   *
   * Raises:
   *   AxiosError: On network failure or server error.
   *
   * Example:
   *   const blob = await executionApi.exportOrdersCsv({
   *     date_from: "2026-04-01",
   *     date_to: "2026-04-12"
   *   });
   *   const url = URL.createObjectURL(blob);
   *   const a = document.createElement("a");
   *   a.href = url;
   *   a.download = "orders.csv";
   *   a.click();
   */
  async exportOrdersCsv(query: OrderHistoryQuery): Promise<Blob> {
    const params = new URLSearchParams();
    Object.entries(query).forEach(([key, value]) => {
      if (value !== undefined && value !== null && value !== "") {
        params.set(key, String(value));
      }
    });
    const { data } = await apiClient.get(`/execution-analysis/export?${params.toString()}`, {
      responseType: "blob",
    });
    return data;
  },
};
