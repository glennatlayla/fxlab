/**
 * RunResults — completed-run results viewer (M2.D4).
 *
 * Purpose:
 *   Top-level page for the route ``/runs/:runId/results``. Renders the
 *   summary metrics, equity-curve + drawdown chart pair, and a sortable /
 *   paginated trade blotter for any completed research run, sourced from
 *   the M2.C3 sub-resource endpoints.
 *
 * Responsibilities:
 *   - Read ``runId`` from the URL via useParams.
 *   - Fetch /runs/{runId}/results/{metrics,equity-curve,blotter} in parallel
 *     on mount, and re-fetch the blotter when the user paginates.
 *   - Render three sections in a vertical flow:
 *       1. Metrics tile grid (return, Sharpe, max DD, win rate, profit factor,
 *          trade count).
 *       2. Equity-curve + drawdown chart pair (recharts).
 *       3. Trade blotter — sortable, client-side paginated via the
 *          ``?page=N&page_size=100`` query param.
 *   - Surface error banners on 404 / 409 / 401 / 403 / network failure with
 *     the offending run_id surfaced for operator triage.
 *
 * Does NOT:
 *   - Compute metrics (the backend service owns this).
 *   - Mutate run state.
 *   - Manage auth (AuthGuard owns this; the page assumes a valid session).
 *
 * Dependencies:
 *   - useAuth from @/auth/useAuth (assert authenticated session).
 *   - getMetrics, getEquityCurve, getBlotter from @/api/run_results.
 *   - recharts (LineChart for equity, AreaChart for drawdown).
 *
 * Route: ``/runs/:runId/results`` (protected by ``exports:read`` scope via AuthGuard).
 */

import { useCallback, useEffect, useMemo, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import {
  Area,
  AreaChart,
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import { useAuth } from "@/auth/useAuth";
import {
  getBlotter,
  getEquityCurve,
  getMetrics,
  RunResultsAuthError,
  RunResultsConflictError,
  RunResultsNotFoundError,
  RunResultsValidationError,
} from "@/api/run_results";
import {
  DEFAULT_BLOTTER_PAGE_SIZE,
  type EquityCurveResponse,
  type RunMetrics,
  type TradeBlotterEntry,
  type TradeBlotterPage,
} from "@/types/run_results";

// ---------------------------------------------------------------------------
// Formatting helpers
// ---------------------------------------------------------------------------

/**
 * Format a Decimal-shaped number to fixed decimal places.
 *
 * Args:
 *   value: The numeric value, or null/undefined when the engine did not
 *     emit the metric.
 *   decimals: Number of decimals to render (default 2).
 *
 * Returns:
 *   Formatted string, or "—" when the input is null/undefined.
 */
function formatNumber(value: number | null | undefined, decimals: number = 2): string {
  if (value === null || value === undefined) return "—";
  if (Number.isNaN(value)) return "—";
  return value.toFixed(decimals);
}

/**
 * Format a percentage value (already in percent units, e.g. 15.5 → "15.50%").
 *
 * Args:
 *   value: Percent value or null/undefined.
 *
 * Returns:
 *   Formatted percentage string with two decimals, or "—" if absent.
 */
function formatPercent(value: number | null | undefined): string {
  if (value === null || value === undefined) return "—";
  if (Number.isNaN(value)) return "—";
  return `${value.toFixed(2)}%`;
}

/**
 * Format a unit-fraction win rate (0.0-1.0) as a percentage string.
 *
 * Args:
 *   value: Win rate as a fraction in [0, 1].
 *
 * Returns:
 *   Win rate as a percentage string with two decimals, or "—".
 */
function formatWinRate(value: number | null | undefined): string {
  if (value === null || value === undefined) return "—";
  if (Number.isNaN(value)) return "—";
  return `${(value * 100).toFixed(2)}%`;
}

/**
 * Format a currency-magnitude value with thousands separators and two
 * decimal places. The display has no currency symbol because the run
 * does not commit to a single currency in the wire format.
 *
 * Args:
 *   value: Numeric value or null/undefined.
 *
 * Returns:
 *   Formatted string, or "—" when absent.
 */
function formatCurrency(value: number | null | undefined): string {
  if (value === null || value === undefined) return "—";
  if (Number.isNaN(value)) return "—";
  return value.toLocaleString("en-US", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });
}

/**
 * Format an ISO-8601 timestamp string for compact display.
 *
 * Args:
 *   timestamp: ISO-8601 timestamp.
 *
 * Returns:
 *   ``YYYY-MM-DD HH:MM:SS`` UTC string.
 */
function formatTimestamp(timestamp: string): string {
  const date = new Date(timestamp);
  if (Number.isNaN(date.getTime())) return timestamp;
  const iso = date.toISOString();
  return `${iso.slice(0, 10)} ${iso.slice(11, 19)}`;
}

// ---------------------------------------------------------------------------
// Sortable blotter helpers
// ---------------------------------------------------------------------------

type BlotterSortKey = "trade_id" | "timestamp" | "symbol" | "side" | "quantity" | "price";
type SortDirection = "asc" | "desc";

interface SortState {
  key: BlotterSortKey;
  direction: SortDirection;
}

/**
 * Sort the trade rows on the current page.
 *
 * Sorting is purely client-side over the rows already fetched for the
 * current page; pagination from the backend remains the canonical order.
 */
function sortRows(rows: TradeBlotterEntry[], sort: SortState): TradeBlotterEntry[] {
  const sign = sort.direction === "asc" ? 1 : -1;
  const sorted = [...rows];
  sorted.sort((a, b) => {
    const av = a[sort.key];
    const bv = b[sort.key];
    if (typeof av === "number" && typeof bv === "number") {
      return (av - bv) * sign;
    }
    return String(av).localeCompare(String(bv)) * sign;
  });
  return sorted;
}

// ---------------------------------------------------------------------------
// Sub-components
// ---------------------------------------------------------------------------

/**
 * Single metric tile in the metrics grid.
 *
 * Props:
 *   label: Human-readable metric name.
 *   value: Pre-formatted display value.
 *   testId: data-testid attribute for assertions.
 */
function MetricTile({ label, value, testId }: { label: string; value: string; testId: string }) {
  return (
    <div
      className="rounded-lg border border-surface-200 bg-white p-4 shadow-sm"
      data-testid={testId}
    >
      <p className="text-sm font-medium text-surface-500">{label}</p>
      <p className="mt-1 text-2xl font-semibold text-surface-900">{value}</p>
    </div>
  );
}

/**
 * Six-up grid of headline run metrics.
 *
 * Renders return, Sharpe, max drawdown, win rate, profit factor, trade
 * count. Missing metrics render as "—" via the formatting helpers.
 */
function MetricsGrid({ metrics }: { metrics: RunMetrics }) {
  return (
    <div
      className="grid grid-cols-2 gap-4 sm:grid-cols-3 lg:grid-cols-6"
      data-testid="metrics-grid"
    >
      <MetricTile
        label="Total Return"
        value={formatPercent(metrics.total_return_pct)}
        testId="metric-total-return"
      />
      <MetricTile
        label="Sharpe Ratio"
        value={formatNumber(metrics.sharpe_ratio)}
        testId="metric-sharpe"
      />
      <MetricTile
        label="Max Drawdown"
        value={formatPercent(metrics.max_drawdown_pct)}
        testId="metric-max-drawdown"
      />
      <MetricTile
        label="Win Rate"
        value={formatWinRate(metrics.win_rate)}
        testId="metric-win-rate"
      />
      <MetricTile
        label="Profit Factor"
        value={formatNumber(metrics.profit_factor)}
        testId="metric-profit-factor"
      />
      <MetricTile
        label="Trade Count"
        value={String(metrics.total_trades)}
        testId="metric-trade-count"
      />
    </div>
  );
}

/**
 * Equity curve + drawdown chart pair.
 *
 * Renders two recharts charts stacked vertically:
 *   1. LineChart of cumulative equity over time.
 *   2. AreaChart of running drawdown derived from the same series.
 */
function EquityAndDrawdownCharts({ data }: { data: EquityCurveResponse }) {
  // Compute drawdown from the equity curve: dd_t = equity_t / max(equity_0..t) - 1
  const series = useMemo(() => {
    let runningPeak = -Infinity;
    return data.points.map((point) => {
      runningPeak = Math.max(runningPeak, point.equity);
      const drawdown = runningPeak > 0 ? (point.equity / runningPeak - 1) * 100 : 0;
      return {
        timestamp: point.timestamp,
        equity: point.equity,
        drawdown,
      };
    });
  }, [data.points]);

  if (series.length === 0) {
    return (
      <div
        className="flex h-64 items-center justify-center text-surface-400"
        data-testid="equity-empty"
      >
        No equity-curve points returned for this run.
      </div>
    );
  }

  return (
    <div className="space-y-4">
      <div data-testid="equity-curve" className="h-72">
        <ResponsiveContainer width="100%" height="100%">
          <LineChart data={series} margin={{ top: 10, right: 30, left: 10, bottom: 0 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="#e5e7eb" />
            <XAxis
              dataKey="timestamp"
              tick={{ fontSize: 12 }}
              tickFormatter={(ts: string) => ts.slice(0, 10)}
            />
            <YAxis
              tick={{ fontSize: 12 }}
              tickFormatter={(v: number) => v.toLocaleString()}
              domain={["auto", "auto"]}
            />
            <Tooltip
              formatter={(value: number) => [
                value.toLocaleString("en-US", { minimumFractionDigits: 2 }),
                "Equity",
              ]}
              labelFormatter={(ts: string) => `Time: ${formatTimestamp(ts)}`}
            />
            <Line type="monotone" dataKey="equity" stroke="#2563eb" strokeWidth={2} dot={false} />
          </LineChart>
        </ResponsiveContainer>
      </div>

      <div data-testid="drawdown-curve" className="h-56">
        <ResponsiveContainer width="100%" height="100%">
          <AreaChart data={series} margin={{ top: 10, right: 30, left: 10, bottom: 0 }}>
            <CartesianGrid strokeDasharray="3 3" stroke="#e5e7eb" />
            <XAxis
              dataKey="timestamp"
              tick={{ fontSize: 12 }}
              tickFormatter={(ts: string) => ts.slice(0, 10)}
            />
            <YAxis
              tick={{ fontSize: 12 }}
              tickFormatter={(v: number) => `${v.toFixed(1)}%`}
              domain={["auto", 0]}
            />
            <Tooltip
              formatter={(value: number) => [`${value.toFixed(2)}%`, "Drawdown"]}
              labelFormatter={(ts: string) => `Time: ${formatTimestamp(ts)}`}
            />
            <Area
              type="monotone"
              dataKey="drawdown"
              stroke="#dc2626"
              fill="#fecaca"
              strokeWidth={1}
            />
          </AreaChart>
        </ResponsiveContainer>
      </div>
    </div>
  );
}

/**
 * Sortable + paginated trade blotter table.
 *
 * Sorting is purely client-side over the rows on the current page; the
 * page itself is fetched from the backend whenever ``page`` changes.
 * "Out of range" pages render a friendly empty state without errors per
 * the M2.C3 contract (the backend returns an empty trades list when
 * page > total_pages).
 */
function TradeBlotterTable({
  data,
  page,
  totalPages,
  onPageChange,
  isFetching,
}: {
  data: TradeBlotterPage;
  page: number;
  totalPages: number;
  onPageChange: (next: number) => void;
  isFetching: boolean;
}) {
  const [sort, setSort] = useState<SortState>({ key: "timestamp", direction: "asc" });

  const sorted = useMemo(() => sortRows(data.trades, sort), [data.trades, sort]);

  const toggleSort = useCallback((key: BlotterSortKey) => {
    setSort((prev) =>
      prev.key === key
        ? { key, direction: prev.direction === "asc" ? "desc" : "asc" }
        : { key, direction: "asc" },
    );
  }, []);

  const headerButton = (label: string, key: BlotterSortKey) => {
    const active = sort.key === key;
    const arrow = active ? (sort.direction === "asc" ? "▲" : "▼") : "";
    return (
      <button
        type="button"
        onClick={() => toggleSort(key)}
        className="text-left text-xs font-medium uppercase tracking-wider text-surface-500 hover:text-surface-700"
        data-testid={`blotter-sort-${key}`}
      >
        {label} {arrow}
      </button>
    );
  };

  return (
    <div className="overflow-x-auto" data-testid="trade-blotter">
      <table className="min-w-full divide-y divide-surface-200">
        <thead className="bg-surface-50">
          <tr>
            <th className="px-4 py-3">{headerButton("Trade ID", "trade_id")}</th>
            <th className="px-4 py-3">{headerButton("Timestamp", "timestamp")}</th>
            <th className="px-4 py-3">{headerButton("Symbol", "symbol")}</th>
            <th className="px-4 py-3">{headerButton("Side", "side")}</th>
            <th className="px-4 py-3 text-right">{headerButton("Quantity", "quantity")}</th>
            <th className="px-4 py-3 text-right">{headerButton("Price", "price")}</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-surface-100 bg-white">
          {sorted.length === 0 ? (
            <tr data-testid="blotter-empty-row">
              <td colSpan={6} className="px-4 py-6 text-center text-sm text-surface-500">
                {data.total_count === 0 || page > totalPages
                  ? "No trades on this page"
                  : "No trades returned for this page."}
              </td>
            </tr>
          ) : (
            sorted.map((row) => (
              <tr key={row.trade_id} data-testid={`blotter-row-${row.trade_id}`}>
                <td className="whitespace-nowrap px-4 py-2 font-mono text-xs text-surface-700">
                  {row.trade_id}
                </td>
                <td className="whitespace-nowrap px-4 py-2 text-sm text-surface-700">
                  {formatTimestamp(row.timestamp)}
                </td>
                <td className="whitespace-nowrap px-4 py-2 text-sm font-medium text-surface-900">
                  {row.symbol}
                </td>
                <td
                  className={`whitespace-nowrap px-4 py-2 text-sm font-medium ${
                    row.side === "buy" ? "text-green-600" : "text-red-600"
                  }`}
                >
                  {row.side}
                </td>
                <td className="whitespace-nowrap px-4 py-2 text-right text-sm text-surface-700">
                  {formatNumber(row.quantity, 4)}
                </td>
                <td className="whitespace-nowrap px-4 py-2 text-right text-sm text-surface-700">
                  {formatCurrency(row.price)}
                </td>
              </tr>
            ))
          )}
        </tbody>
      </table>

      <div
        className="mt-3 flex items-center justify-between border-t border-surface-200 px-2 py-2 text-sm text-surface-600"
        data-testid="blotter-pagination"
      >
        <div>
          Page <span data-testid="blotter-page">{page}</span> of{" "}
          <span data-testid="blotter-total-pages">{Math.max(totalPages, 1)}</span> ·{" "}
          <span data-testid="blotter-total-count">{data.total_count}</span> trades total
        </div>
        <div className="space-x-2">
          <button
            type="button"
            onClick={() => onPageChange(page - 1)}
            disabled={page <= 1 || isFetching}
            className="rounded-md border border-surface-300 px-3 py-1 text-sm hover:bg-surface-50 disabled:cursor-not-allowed disabled:opacity-50"
            data-testid="blotter-prev"
          >
            Previous
          </button>
          <button
            type="button"
            onClick={() => onPageChange(page + 1)}
            disabled={isFetching}
            className="rounded-md border border-surface-300 px-3 py-1 text-sm hover:bg-surface-50 disabled:cursor-not-allowed disabled:opacity-50"
            data-testid="blotter-next"
          >
            Next
          </button>
        </div>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Compare-with modal
// ---------------------------------------------------------------------------

/**
 * 26-character Crockford Base32 ULID. Mirrors the backend regex in
 * :data:`services.api.routes.runs.ULID_PATTERN` so we reject obviously
 * bogus inputs client-side before a 422 round-trip on the compare page.
 */
const COMPARE_ULID_REGEX = /^[0-9A-HJKMNP-TV-Z]{26}$/i;

/**
 * Lightweight modal that prompts the operator for a second run ULID
 * and navigates to ``/runs/compare?a={currentRunId}&b={inputId}`` on
 * submit. Cancel closes the modal and leaves the page state intact.
 *
 * Validation:
 *   - Trimmed input must be non-empty.
 *   - Trimmed input must match the ULID character set + length.
 *   Failing either check renders an inline error and disables submit.
 */
function CompareWithModal({
  currentRunId,
  isOpen,
  onClose,
  onSubmit,
}: {
  currentRunId: string;
  isOpen: boolean;
  onClose: () => void;
  onSubmit: (otherRunId: string) => void;
}) {
  const [value, setValue] = useState<string>("");
  const [submitted, setSubmitted] = useState<boolean>(false);

  // Reset internal state every time the modal is reopened so a stale
  // value from a previous interaction does not leak into the next one.
  useEffect(() => {
    if (isOpen) {
      setValue("");
      setSubmitted(false);
    }
  }, [isOpen]);

  if (!isOpen) return null;

  const trimmed = value.trim();
  const isEmpty = trimmed.length === 0;
  const isUlidShape = COMPARE_ULID_REGEX.test(trimmed);
  const isSelf = trimmed === currentRunId;
  const validationError = submitted
    ? isEmpty
      ? "Run ID is required."
      : !isUlidShape
        ? "Run ID must be a 26-character ULID."
        : isSelf
          ? "Choose a different run to compare against."
          : null
    : null;

  const handleSubmit = (event: React.FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setSubmitted(true);
    if (isEmpty || !isUlidShape || isSelf) return;
    onSubmit(trimmed);
  };

  return (
    <div
      className="fixed inset-0 z-40 flex items-center justify-center bg-surface-900/40 p-4"
      data-testid="compare-with-modal"
      role="dialog"
      aria-modal="true"
      aria-labelledby="compare-with-modal-title"
    >
      <div className="w-full max-w-md rounded-lg border border-surface-200 bg-white p-5 shadow-lg">
        <h2 id="compare-with-modal-title" className="text-lg font-semibold text-surface-900">
          Compare with another run
        </h2>
        <p className="mt-1 text-sm text-surface-500">
          Enter the ULID of the run to compare against. You will be sent to a side-by-side
          comparison page.
        </p>

        <form className="mt-4 space-y-3" onSubmit={handleSubmit} noValidate>
          <label className="block text-sm font-medium text-surface-700" htmlFor="compare-other-id">
            Run ID to compare against
          </label>
          <input
            id="compare-other-id"
            type="text"
            value={value}
            onChange={(e) => setValue(e.target.value)}
            placeholder="01H..."
            className="w-full rounded-md border border-surface-300 px-3 py-2 font-mono text-sm focus:border-blue-500 focus:outline-none focus:ring-1 focus:ring-blue-500"
            data-testid="compare-with-modal-input"
            autoFocus
          />
          {validationError ? (
            <p className="text-sm text-red-600" role="alert" data-testid="compare-with-modal-error">
              {validationError}
            </p>
          ) : null}

          <div className="flex justify-end gap-2 pt-2">
            <button
              type="button"
              onClick={onClose}
              className="rounded-md border border-surface-300 px-3 py-1.5 text-sm font-medium text-surface-700 hover:bg-surface-50"
              data-testid="compare-with-modal-cancel"
            >
              Cancel
            </button>
            <button
              type="submit"
              className="rounded-md bg-blue-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-blue-700"
              data-testid="compare-with-modal-submit"
            >
              Compare
            </button>
          </div>
        </form>
      </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Main page
// ---------------------------------------------------------------------------

/**
 * Translate any error thrown by the run-results API layer into a
 * user-facing message that surfaces the offending run_id.
 */
function getErrorMessage(err: unknown, runId: string): string {
  if (err instanceof RunResultsNotFoundError) {
    return `Run ${runId} was not found. It may have been deleted or the ID is incorrect.`;
  }
  if (err instanceof RunResultsConflictError) {
    return `Run ${runId} has not completed yet. Results will be available once the run finishes.`;
  }
  if (err instanceof RunResultsAuthError) {
    return err.statusCode === 401
      ? `Your session has expired while loading run ${runId}. Please log in again.`
      : `You do not have permission to view results for run ${runId}.`;
  }
  if (err instanceof RunResultsValidationError) {
    return `Invalid request for run ${runId}: ${err.message}`;
  }
  if (err instanceof Error) {
    return `Failed to load run ${runId}: ${err.message}`;
  }
  return `Failed to load run ${runId}.`;
}

export default function RunResults() {
  const { runId } = useParams<{ runId: string }>();
  const navigate = useNavigate();
  // useAuth assertion: the AuthGuard wrapper has already verified the
  // session and the exports:read scope; calling useAuth here keeps the
  // hook semantics consistent with sibling pages and ensures the page
  // re-renders on logout.
  useAuth();

  const [metrics, setMetrics] = useState<RunMetrics | null>(null);
  const [equityCurve, setEquityCurve] = useState<EquityCurveResponse | null>(null);
  const [blotter, setBlotter] = useState<TradeBlotterPage | null>(null);
  const [page, setPage] = useState<number>(1);

  const [isLoadingInitial, setIsLoadingInitial] = useState<boolean>(true);
  const [isFetchingBlotter, setIsFetchingBlotter] = useState<boolean>(false);
  const [error, setError] = useState<string | null>(null);
  const [isCompareModalOpen, setIsCompareModalOpen] = useState<boolean>(false);

  // Initial fetch — metrics + equity curve + page 1 of blotter in parallel.
  useEffect(() => {
    if (!runId) return;

    const controller = new AbortController();
    let cancelled = false;

    async function loadAll(currentRunId: string) {
      setIsLoadingInitial(true);
      setError(null);
      try {
        const [metricsResp, equityResp, blotterResp] = await Promise.all([
          getMetrics(currentRunId, controller.signal),
          getEquityCurve(currentRunId, controller.signal),
          getBlotter(currentRunId, 1, DEFAULT_BLOTTER_PAGE_SIZE, controller.signal),
        ]);
        if (cancelled) return;
        setMetrics(metricsResp);
        setEquityCurve(equityResp);
        setBlotter(blotterResp);
        setPage(blotterResp.page);
      } catch (err) {
        if (cancelled) return;
        if (err instanceof DOMException && err.name === "AbortError") return;
        setError(getErrorMessage(err, currentRunId));
      } finally {
        if (!cancelled) setIsLoadingInitial(false);
      }
    }

    loadAll(runId);

    return () => {
      cancelled = true;
      controller.abort();
    };
  }, [runId]);

  // Re-fetch the blotter when the user paginates (after the initial load).
  const handlePageChange = useCallback(
    async (nextPage: number) => {
      if (!runId) return;
      if (nextPage < 1) return;

      setIsFetchingBlotter(true);
      try {
        const resp = await getBlotter(runId, nextPage, DEFAULT_BLOTTER_PAGE_SIZE);
        setBlotter(resp);
        setPage(nextPage);
      } catch (err) {
        setError(getErrorMessage(err, runId));
      } finally {
        setIsFetchingBlotter(false);
      }
    },
    [runId],
  );

  if (!runId) {
    return (
      <div className="p-6" data-testid="run-results-no-run-id">
        <p className="text-red-600">No run ID specified in the URL.</p>
      </div>
    );
  }

  return (
    <div className="space-y-6 p-6" data-testid="run-results-page">
      <header className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <h1 className="text-2xl font-bold text-surface-900" data-testid="run-results-title">
            Run Results
          </h1>
          <p className="mt-1 text-sm text-surface-500">
            Run: <span className="font-mono">{runId}</span>
            <button
              type="button"
              onClick={() => setIsCompareModalOpen(true)}
              className="ml-3 rounded-md border border-surface-300 bg-white px-2 py-0.5 text-xs font-medium text-surface-700 hover:bg-surface-50"
              data-testid="compare-with-button"
            >
              Compare with…
            </button>
            {metrics?.completed_at ? (
              <span className="ml-2 text-surface-400">
                · completed {formatTimestamp(metrics.completed_at)}
              </span>
            ) : null}
          </p>
        </div>
      </header>

      <CompareWithModal
        currentRunId={runId}
        isOpen={isCompareModalOpen}
        onClose={() => setIsCompareModalOpen(false)}
        onSubmit={(otherRunId) => {
          setIsCompareModalOpen(false);
          navigate(`/runs/compare?a=${runId}&b=${otherRunId}`);
        }}
      />

      {isLoadingInitial && (
        <div className="flex h-64 items-center justify-center" data-testid="run-results-loading">
          <div className="text-center">
            <div className="mx-auto h-8 w-8 animate-spin rounded-full border-4 border-blue-600 border-t-transparent" />
            <p className="mt-2 text-sm text-surface-500">Loading run results...</p>
          </div>
        </div>
      )}

      {error && !isLoadingInitial && (
        <div
          className="rounded-lg border border-red-200 bg-red-50 p-4"
          data-testid="run-results-error"
          role="alert"
        >
          <p className="text-sm text-red-700">{error}</p>
        </div>
      )}

      {!isLoadingInitial && !error && metrics && (
        <section aria-label="Performance Metrics">
          <h2 className="mb-3 text-lg font-semibold text-surface-900">Performance Summary</h2>
          <MetricsGrid metrics={metrics} />
        </section>
      )}

      {!isLoadingInitial && !error && equityCurve && (
        <section
          aria-label="Equity and Drawdown"
          className="rounded-lg border border-surface-200 bg-white p-4"
        >
          <h2 className="mb-3 text-lg font-semibold text-surface-900">Equity & Drawdown</h2>
          <EquityAndDrawdownCharts data={equityCurve} />
        </section>
      )}

      {!isLoadingInitial && !error && blotter && (
        <section
          aria-label="Trade Blotter"
          className="rounded-lg border border-surface-200 bg-white p-4"
        >
          <h2 className="mb-3 text-lg font-semibold text-surface-900">Trade Blotter</h2>
          <TradeBlotterTable
            data={blotter}
            page={page}
            totalPages={blotter.total_pages}
            onPageChange={handlePageChange}
            isFetching={isFetchingBlotter}
          />
        </section>
      )}
    </div>
  );
}
