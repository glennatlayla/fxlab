/**
 * P&L feature API layer — data fetching for P&L attribution and performance tracking.
 *
 * Purpose:
 *   Fetch P&L summaries, timeseries, per-symbol attribution, strategy comparisons,
 *   and trigger daily snapshots from the shared backend HTTP client.
 *   Implements CLAUDE.md §9 retry on transient errors for idempotent reads,
 *   propagates X-Correlation-Id headers per §8, and supports AbortSignal
 *   cancellation for in-flight teardown.
 *
 * Responsibilities:
 *   - GET /pnl/{deployment_id}/summary       — aggregate P&L metrics.
 *   - GET /pnl/{deployment_id}/timeseries    — equity curve data points.
 *   - GET /pnl/{deployment_id}/attribution   — per-symbol breakdown.
 *   - GET /pnl/comparison                    — multi-strategy comparison.
 *   - POST /pnl/{deployment_id}/snapshot     — persist daily snapshot.
 *   - Classify AxiosErrors into domain-specific P&L errors.
 *   - Retry transient GET failures with exponential backoff.
 *
 * Does NOT:
 *   - Contain business logic, UI rendering, or React state management.
 *   - Bypass the shared apiClient (auth, base URL, 401 handling).
 *
 * Dependencies:
 *   - apiClient from @/api/client.
 *
 * Example:
 *   const summary = await pnlApi.getSummary("01HDEPLOY001");
 *   const series = await pnlApi.getTimeseries("01HDEPLOY001", "2026-04-01", "2026-04-12");
 */

import { AxiosError, type AxiosRequestConfig } from "axios";
import { apiClient } from "@/api/client";

// ---------------------------------------------------------------------------
// Types — response shapes from the backend
// ---------------------------------------------------------------------------

/** Aggregate P&L summary for a single deployment. */
export interface PnlSummary {
  deployment_id: string;
  total_realized_pnl: string;
  total_unrealized_pnl: string;
  total_commission: string;
  total_fees: string;
  net_pnl: string;
  positions_count: number;
  total_trades: number;
  winning_trades: number;
  losing_trades: number;
  win_rate: string;
  sharpe_ratio: string;
  max_drawdown_pct: string;
  avg_win: string;
  avg_loss: string;
  profit_factor: string;
  date_from: string;
  date_to: string;
}

/** Single data point for equity curve / timeseries chart. */
export interface PnlTimeseriesPoint {
  snapshot_date: string;
  realized_pnl: string;
  unrealized_pnl: string;
  net_pnl: string;
  cumulative_pnl: string;
  daily_pnl: string;
  commission: string;
  fees: string;
  positions_count: number;
  drawdown_pct: string;
}

/** Per-symbol P&L attribution entry. */
export interface SymbolAttribution {
  symbol: string;
  realized_pnl: string;
  unrealized_pnl: string;
  net_pnl: string;
  contribution_pct: string;
  total_trades: number;
  winning_trades: number;
  win_rate: string;
  total_volume: string;
  commission: string;
}

/** Full attribution report for a deployment. */
export interface PnlAttributionReport {
  deployment_id: string;
  date_from: string | null;
  date_to: string | null;
  total_net_pnl: string;
  by_symbol: SymbolAttribution[];
}

/** Single entry in a multi-deployment comparison. */
export interface StrategyComparisonEntry {
  deployment_id: string;
  strategy_name: string | null;
  net_pnl: string;
  total_realized_pnl: string;
  total_unrealized_pnl: string;
  total_commission: string;
  win_rate: string;
  sharpe_ratio: string;
  max_drawdown_pct: string;
  total_trades: number;
}

/** Multi-deployment comparison report. */
export interface PnlComparisonReport {
  date_from: string | null;
  date_to: string | null;
  entries: StrategyComparisonEntry[];
}

/** Persisted snapshot result. */
export interface PnlSnapshot {
  id: string;
  deployment_id: string;
  snapshot_date: string;
  realized_pnl: string;
  unrealized_pnl: string;
  commission: string;
  fees: string;
  positions_count: number;
  created_at: string;
  updated_at: string;
}

// ---------------------------------------------------------------------------
// Error hierarchy — domain-specific P&L errors per CLAUDE.md §9
// ---------------------------------------------------------------------------

/** Base error for all P&L API failures. */
export class PnlApiError extends Error {
  constructor(
    message: string,
    public readonly statusCode?: number,
    public readonly cause?: unknown,
  ) {
    super(message);
    this.name = "PnlApiError";
  }
}

/** 404 — deployment or resource not found. */
export class PnlNotFoundError extends PnlApiError {
  constructor(entityId: string, cause?: unknown) {
    super(`P&L resource not found: ${entityId}`, 404, cause);
    this.name = "PnlNotFoundError";
  }
}

/** 401/403 — authentication or authorization failure. */
export class PnlAuthError extends PnlApiError {
  constructor(statusCode: 401 | 403, cause?: unknown) {
    super(
      statusCode === 401 ? "Authentication required" : "Insufficient permissions",
      statusCode,
      cause,
    );
    this.name = "PnlAuthError";
  }
}

/** 422 — validation error (bad dates, empty IDs). */
export class PnlValidationError extends PnlApiError {
  constructor(detail: string, cause?: unknown) {
    super(`Validation error: ${detail}`, 422, cause);
    this.name = "PnlValidationError";
  }
}

/** Network / transient error (timeout, 5xx, connectivity). */
export class PnlNetworkError extends PnlApiError {
  constructor(statusCode?: number, cause?: unknown) {
    super(`P&L network error (status: ${statusCode ?? "unknown"})`, statusCode, cause);
    this.name = "PnlNetworkError";
  }
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

const CORRELATION_HEADER = "X-Correlation-Id";

/** Maximum retry attempts for idempotent GET requests. */
const MAX_RETRIES = 3;

/** Base delay in milliseconds for exponential backoff. */
const BASE_DELAY_MS = 1000;

/**
 * Build per-request axios config with correlation header and abort signal.
 *
 * The header is omitted when no correlationId is supplied so the shared
 * apiClient interceptor injects a fallback UUID.
 */
function buildConfig(
  correlationId?: string,
  signal?: AbortSignal,
  extra?: Partial<AxiosRequestConfig>,
): AxiosRequestConfig {
  const headers: Record<string, string> = {};
  if (correlationId) {
    headers[CORRELATION_HEADER] = correlationId;
  }
  return { headers, signal, ...extra };
}

/**
 * Classify an AxiosError into a domain-specific P&L error.
 *
 * Per CLAUDE.md §9:
 *   - 404 → PnlNotFoundError (no retry).
 *   - 401/403 → PnlAuthError (no retry).
 *   - 422 → PnlValidationError (no retry).
 *   - 5xx / timeout / network → PnlNetworkError (retriable).
 */
function classifyError(err: AxiosError, entityId: string): PnlApiError {
  const status = err.response?.status;
  const detail =
    typeof err.response?.data === "object" && err.response?.data !== null
      ? (err.response.data as Record<string, unknown>).detail
      : undefined;

  if (status === 404) return new PnlNotFoundError(entityId, err);
  if (status === 401) return new PnlAuthError(401, err);
  if (status === 403) return new PnlAuthError(403, err);
  if (status === 422) return new PnlValidationError(String(detail ?? "Invalid request"), err);
  return new PnlNetworkError(status, err);
}

/**
 * Determine whether an error is transient and should be retried.
 *
 * Retries on: network errors, timeouts, 429 rate limit, 5xx server errors.
 * Does NOT retry on: 400, 401, 403, 404, 422 — these are permanent.
 */
function isTransient(err: unknown): boolean {
  if (err instanceof AxiosError) {
    if (!err.response) return true; // Network error / timeout
    const status = err.response.status;
    return status === 429 || status >= 500;
  }
  return false;
}

/**
 * Retry an async operation with exponential backoff and jitter.
 *
 * Only retries when isTransient returns true. Permanent errors are thrown
 * immediately without consuming retry budget.
 *
 * Args:
 *   fn: The async operation to attempt.
 *   signal: Optional AbortSignal for cancellation.
 *
 * Returns:
 *   The result of fn on success.
 *
 * Raises:
 *   The last error after all retries exhausted, or a permanent error immediately.
 */
async function retryWithBackoff<T>(fn: () => Promise<T>, signal?: AbortSignal): Promise<T> {
  let lastError: unknown;

  for (let attempt = 0; attempt <= MAX_RETRIES; attempt++) {
    if (signal?.aborted) {
      throw new DOMException("Request aborted", "AbortError");
    }

    try {
      return await fn();
    } catch (err) {
      lastError = err;

      // Abort errors are never retried
      if (err instanceof DOMException && err.name === "AbortError") throw err;

      // Permanent errors are not retried
      if (!isTransient(err)) throw err;

      // If we've exhausted retries, throw
      if (attempt === MAX_RETRIES) break;

      // Exponential backoff with jitter: delay = base * 2^attempt * (0.5..1.5)
      const jitter = 0.5 + Math.random();
      const delay = BASE_DELAY_MS * Math.pow(2, attempt) * jitter;
      await new Promise((resolve) => setTimeout(resolve, delay));
    }
  }

  throw lastError;
}

/**
 * Normalize an unknown thrown value into a typed Error.
 *
 * - DOMException("AbortError") → rethrown as-is for cancellation.
 * - AxiosError → classified into domain P&L error.
 * - Existing Error → rethrown as-is.
 * - Anything else → wrapped in PnlNetworkError.
 */
function normalizeError(err: unknown, entityId: string): Error {
  if (err instanceof DOMException && err.name === "AbortError") return err;
  if (err instanceof AxiosError) return classifyError(err, entityId);
  if (err instanceof Error) return err;
  return new PnlNetworkError(undefined, err);
}

// ---------------------------------------------------------------------------
// API client
// ---------------------------------------------------------------------------

/**
 * P&L Attribution API client.
 *
 * All methods throw domain-specific errors from the hierarchy above.
 * Idempotent GET methods are wrapped in retryWithBackoff per CLAUDE.md §9.
 * POST methods (snapshot) are NOT retried to avoid duplicate side effects.
 *
 * Example:
 *   const summary = await pnlApi.getSummary("01HDEPLOY001", "corr-1");
 */
export const pnlApi = {
  /**
   * Fetch aggregate P&L summary for a deployment.
   *
   * Args:
   *   deploymentId: The deployment ULID to query.
   *   correlationId: Optional trace ID for distributed tracing.
   *   signal: Optional AbortSignal for request cancellation.
   *
   * Returns:
   *   PnlSummary with realized/unrealized P&L, win rate, Sharpe, drawdown.
   *
   * Raises:
   *   PnlNotFoundError: Deployment does not exist.
   *   PnlAuthError: Missing or insufficient credentials.
   *   PnlNetworkError: Transient network failure (after retries exhausted).
   */
  async getSummary(
    deploymentId: string,
    correlationId?: string,
    signal?: AbortSignal,
  ): Promise<PnlSummary> {
    const config = buildConfig(correlationId, signal);
    try {
      return await retryWithBackoff(async () => {
        const resp = await apiClient.get<PnlSummary>(`/pnl/${deploymentId}/summary`, config);
        return resp.data;
      }, signal);
    } catch (err) {
      throw normalizeError(err, deploymentId);
    }
  },

  /**
   * Fetch P&L timeseries data for equity curve rendering.
   *
   * Args:
   *   deploymentId: The deployment ULID.
   *   dateFrom: Start date (YYYY-MM-DD, inclusive).
   *   dateTo: End date (YYYY-MM-DD, inclusive).
   *   granularity: Aggregation level — "daily", "weekly", or "monthly".
   *   correlationId: Optional trace ID.
   *   signal: Optional AbortSignal.
   *
   * Returns:
   *   Array of PnlTimeseriesPoint sorted chronologically.
   *
   * Raises:
   *   PnlNotFoundError, PnlValidationError, PnlAuthError, PnlNetworkError.
   */
  async getTimeseries(
    deploymentId: string,
    dateFrom: string,
    dateTo: string,
    granularity: string = "daily",
    correlationId?: string,
    signal?: AbortSignal,
  ): Promise<PnlTimeseriesPoint[]> {
    const config = buildConfig(correlationId, signal, {
      params: { date_from: dateFrom, date_to: dateTo, granularity },
    });
    try {
      return await retryWithBackoff(async () => {
        const resp = await apiClient.get<PnlTimeseriesPoint[]>(
          `/pnl/${deploymentId}/timeseries`,
          config,
        );
        return resp.data;
      }, signal);
    } catch (err) {
      throw normalizeError(err, deploymentId);
    }
  },

  /**
   * Fetch per-symbol P&L attribution for a deployment.
   *
   * Args:
   *   deploymentId: The deployment ULID.
   *   dateFrom: Optional start date filter (YYYY-MM-DD).
   *   dateTo: Optional end date filter (YYYY-MM-DD).
   *   correlationId: Optional trace ID.
   *   signal: Optional AbortSignal.
   *
   * Returns:
   *   PnlAttributionReport with symbol-level breakdown.
   *
   * Raises:
   *   PnlNotFoundError, PnlAuthError, PnlNetworkError.
   */
  async getAttribution(
    deploymentId: string,
    dateFrom?: string,
    dateTo?: string,
    correlationId?: string,
    signal?: AbortSignal,
  ): Promise<PnlAttributionReport> {
    const params: Record<string, string> = {};
    if (dateFrom) params.date_from = dateFrom;
    if (dateTo) params.date_to = dateTo;

    const config = buildConfig(correlationId, signal, { params });
    try {
      return await retryWithBackoff(async () => {
        const resp = await apiClient.get<PnlAttributionReport>(
          `/pnl/${deploymentId}/attribution`,
          config,
        );
        return resp.data;
      }, signal);
    } catch (err) {
      throw normalizeError(err, deploymentId);
    }
  },

  /**
   * Compare P&L metrics across multiple deployments.
   *
   * Args:
   *   deploymentIds: Array of deployment ULIDs to compare.
   *   dateFrom: Optional start date filter (YYYY-MM-DD).
   *   dateTo: Optional end date filter (YYYY-MM-DD).
   *   correlationId: Optional trace ID.
   *   signal: Optional AbortSignal.
   *
   * Returns:
   *   PnlComparisonReport with one entry per deployment.
   *
   * Raises:
   *   PnlValidationError: Empty deployment list.
   *   PnlAuthError, PnlNetworkError.
   */
  async getComparison(
    deploymentIds: string[],
    dateFrom?: string,
    dateTo?: string,
    correlationId?: string,
    signal?: AbortSignal,
  ): Promise<PnlComparisonReport> {
    const params: Record<string, string> = {
      deployment_ids: deploymentIds.join(","),
    };
    if (dateFrom) params.date_from = dateFrom;
    if (dateTo) params.date_to = dateTo;

    const config = buildConfig(correlationId, signal, { params });
    try {
      return await retryWithBackoff(async () => {
        const resp = await apiClient.get<PnlComparisonReport>(`/pnl/comparison`, config);
        return resp.data;
      }, signal);
    } catch (err) {
      throw normalizeError(err, "comparison");
    }
  },

  /**
   * Persist a daily P&L snapshot for a deployment.
   *
   * Uses upsert semantics — calling twice for the same date updates the
   * existing record. This is NOT retried because it is a write operation.
   *
   * Args:
   *   deploymentId: The deployment ULID.
   *   snapshotDate: The date to snapshot (YYYY-MM-DD).
   *   correlationId: Optional trace ID.
   *
   * Returns:
   *   PnlSnapshot with persisted record details.
   *
   * Raises:
   *   PnlNotFoundError: Deployment does not exist.
   *   PnlValidationError: Invalid date format.
   *   PnlAuthError, PnlNetworkError.
   */
  async takeSnapshot(
    deploymentId: string,
    snapshotDate: string,
    correlationId?: string,
  ): Promise<PnlSnapshot> {
    const config = buildConfig(correlationId, undefined, {
      params: { snapshot_date: snapshotDate },
    });
    try {
      // POST — not retried (write operation with side effects)
      const resp = await apiClient.post<PnlSnapshot>(`/pnl/${deploymentId}/snapshot`, null, config);
      return resp.data;
    } catch (err) {
      throw normalizeError(err, deploymentId);
    }
  },
};
