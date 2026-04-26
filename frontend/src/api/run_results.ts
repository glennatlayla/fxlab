/**
 * API client for the M2.C3 run results sub-resource endpoints.
 *
 * Purpose:
 *   Fetch RunMetrics, EquityCurveResponse, and TradeBlotterPage from the
 *   M2.C3 backend endpoints introduced in this milestone:
 *     - GET /runs/{run_id}/results/metrics
 *     - GET /runs/{run_id}/results/equity-curve
 *     - GET /runs/{run_id}/results/blotter?page=N&page_size=M
 *
 * Responsibilities:
 *   - Wrap apiClient.get() with run_id-aware URL building.
 *   - Surface structured errors (RunResultsNotFoundError, RunResultsAuthError,
 *     RunResultsValidationError, RunResultsConflictError, RunResultsNetworkError)
 *     so the page can render targeted messaging.
 *   - Default the blotter page_size to DEFAULT_BLOTTER_PAGE_SIZE (100) and
 *     enforce the MAX_BLOTTER_PAGE_SIZE ceiling (1000) on the client side.
 *
 * Does NOT:
 *   - Contain UI / React state.
 *   - Bypass the shared apiClient (auth, base URL, correlation header,
 *     401 handler all live there).
 *   - Mutate state — these are read-only GETs.
 *
 * Dependencies:
 *   - axios for AxiosError typing.
 *   - apiClient from @/api/client (auth + correlation injection).
 *   - @/types/run_results for response shapes and pagination defaults.
 *
 * Error conditions:
 *   - 404 → RunResultsNotFoundError (run does not exist).
 *   - 409 → RunResultsConflictError (run not yet completed).
 *   - 401/403 → RunResultsAuthError.
 *   - 422 → RunResultsValidationError (bad ULID, page_size > max).
 *   - network / 5xx → RunResultsNetworkError.
 *
 * Example:
 *   const metrics = await getMetrics("01HRUN0000000000000000000A");
 *   const blotter = await getBlotter("01HRUN0000000000000000000A", 1, 100);
 */

import { AxiosError } from "axios";
import { apiClient } from "@/api/client";
import {
  DEFAULT_BLOTTER_PAGE_SIZE,
  MAX_BLOTTER_PAGE_SIZE,
  type EquityCurveResponse,
  type RunMetrics,
  type TradeBlotterPage,
} from "@/types/run_results";

// ---------------------------------------------------------------------------
// Error hierarchy — domain-specific run-results errors per CLAUDE.md §9
// ---------------------------------------------------------------------------

/** Base error for all run-results API failures. */
export class RunResultsApiError extends Error {
  constructor(
    message: string,
    public readonly statusCode?: number,
    public readonly cause?: unknown,
  ) {
    super(message);
    this.name = "RunResultsApiError";
  }
}

/** 404 — run does not exist. */
export class RunResultsNotFoundError extends RunResultsApiError {
  constructor(runId: string, cause?: unknown) {
    super(`Run not found: ${runId}`, 404, cause);
    this.name = "RunResultsNotFoundError";
  }
}

/** 409 — run exists but has not yet COMPLETED (no results available). */
export class RunResultsConflictError extends RunResultsApiError {
  constructor(runId: string, cause?: unknown) {
    super(`Run ${runId} has not completed; results are not yet available.`, 409, cause);
    this.name = "RunResultsConflictError";
  }
}

/** 401/403 — authentication or scope failure. */
export class RunResultsAuthError extends RunResultsApiError {
  constructor(statusCode: 401 | 403, cause?: unknown) {
    super(
      statusCode === 401 ? "Authentication required" : "Missing exports:read scope",
      statusCode,
      cause,
    );
    this.name = "RunResultsAuthError";
  }
}

/** 422 — validation failure (bad ULID, page_size > MAX_BLOTTER_PAGE_SIZE). */
export class RunResultsValidationError extends RunResultsApiError {
  constructor(detail: string, cause?: unknown) {
    super(`Validation error: ${detail}`, 422, cause);
    this.name = "RunResultsValidationError";
  }
}

/** Network / transient error (timeout, 5xx, connectivity). */
export class RunResultsNetworkError extends RunResultsApiError {
  constructor(statusCode?: number, cause?: unknown) {
    super(`Run results network error (status: ${statusCode ?? "unknown"})`, statusCode, cause);
    this.name = "RunResultsNetworkError";
  }
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/**
 * Classify an AxiosError into a domain-specific run-results error.
 *
 * Per CLAUDE.md §9 the mapping mirrors the M2.C3 backend HTTP behaviour:
 *   - 404 → RunResultsNotFoundError.
 *   - 409 → RunResultsConflictError.
 *   - 401/403 → RunResultsAuthError.
 *   - 422 → RunResultsValidationError.
 *   - everything else → RunResultsNetworkError.
 *
 * Args:
 *   err: The underlying AxiosError thrown by apiClient.
 *   runId: The run ULID for inclusion in error messages.
 *
 * Returns:
 *   A RunResultsApiError subclass appropriate for the HTTP status.
 */
function classifyAxiosError(err: AxiosError, runId: string): RunResultsApiError {
  const status = err.response?.status;
  const detail =
    typeof err.response?.data === "object" && err.response?.data !== null
      ? (err.response.data as Record<string, unknown>).detail
      : undefined;

  if (status === 404) return new RunResultsNotFoundError(runId, err);
  if (status === 409) return new RunResultsConflictError(runId, err);
  if (status === 401) return new RunResultsAuthError(401, err);
  if (status === 403) return new RunResultsAuthError(403, err);
  if (status === 422) {
    return new RunResultsValidationError(String(detail ?? "Invalid request"), err);
  }
  return new RunResultsNetworkError(status, err);
}

/**
 * Normalize any thrown value into a typed Error.
 *
 * Preserves AbortError for cancellation paths; classifies AxiosError;
 * passes through other Error subclasses; wraps anything else in
 * RunResultsNetworkError.
 *
 * Args:
 *   err: The thrown value.
 *   runId: The run ULID for inclusion in error messages.
 *
 * Returns:
 *   An Error subclass safe to throw from the API layer.
 */
function normalizeError(err: unknown, runId: string): Error {
  if (err instanceof DOMException && err.name === "AbortError") return err;
  if (err instanceof AxiosError) return classifyAxiosError(err, runId);
  if (err instanceof Error) return err;
  return new RunResultsNetworkError(undefined, err);
}

// ---------------------------------------------------------------------------
// Public API
// ---------------------------------------------------------------------------

/**
 * Fetch the headline summary metrics for a completed run.
 *
 * Args:
 *   runId: ULID of the run to query.
 *   signal: Optional AbortSignal for request cancellation.
 *
 * Returns:
 *   RunMetrics with total return, Sharpe, drawdown, win rate, etc.
 *
 * Raises:
 *   RunResultsNotFoundError, RunResultsConflictError, RunResultsAuthError,
 *   RunResultsValidationError, RunResultsNetworkError.
 *
 * Example:
 *   const metrics = await getMetrics("01HRUN0000000000000000000A");
 */
export async function getMetrics(runId: string, signal?: AbortSignal): Promise<RunMetrics> {
  try {
    const resp = await apiClient.get<RunMetrics>(`/runs/${runId}/results/metrics`, { signal });
    return resp.data;
  } catch (err) {
    throw normalizeError(err, runId);
  }
}

/**
 * Fetch the equity curve samples for a completed run.
 *
 * Args:
 *   runId: ULID of the run to query.
 *   signal: Optional AbortSignal for request cancellation.
 *
 * Returns:
 *   EquityCurveResponse with samples ordered ascending by timestamp.
 *
 * Raises:
 *   RunResultsNotFoundError, RunResultsConflictError, RunResultsAuthError,
 *   RunResultsValidationError, RunResultsNetworkError.
 */
export async function getEquityCurve(
  runId: string,
  signal?: AbortSignal,
): Promise<EquityCurveResponse> {
  try {
    const resp = await apiClient.get<EquityCurveResponse>(`/runs/${runId}/results/equity-curve`, {
      signal,
    });
    return resp.data;
  } catch (err) {
    throw normalizeError(err, runId);
  }
}

/**
 * Fetch one page of the trade blotter for a completed run.
 *
 * Args:
 *   runId: ULID of the run to query.
 *   page: 1-based page index (must be >= 1).
 *   pageSize: Optional trades-per-page; defaults to DEFAULT_BLOTTER_PAGE_SIZE
 *     (100), capped at MAX_BLOTTER_PAGE_SIZE (1000). Values above the cap
 *     are clamped client-side to avoid an avoidable 422 round-trip.
 *   signal: Optional AbortSignal for request cancellation.
 *
 * Returns:
 *   TradeBlotterPage with the page contents plus pagination metadata.
 *
 * Raises:
 *   RunResultsNotFoundError, RunResultsConflictError, RunResultsAuthError,
 *   RunResultsValidationError, RunResultsNetworkError.
 *
 * Example:
 *   const page1 = await getBlotter("01HRUN…", 1);          // page_size=100
 *   const page2 = await getBlotter("01HRUN…", 2, 50);      // page_size=50
 */
export async function getBlotter(
  runId: string,
  page: number,
  pageSize: number = DEFAULT_BLOTTER_PAGE_SIZE,
  signal?: AbortSignal,
): Promise<TradeBlotterPage> {
  const effectivePageSize = Math.min(Math.max(pageSize, 1), MAX_BLOTTER_PAGE_SIZE);
  try {
    const resp = await apiClient.get<TradeBlotterPage>(`/runs/${runId}/results/blotter`, {
      params: { page, page_size: effectivePageSize },
      signal,
    });
    return resp.data;
  } catch (err) {
    throw normalizeError(err, runId);
  }
}

/**
 * Download the round-trip trade blotter for a completed run as a CSV blob.
 *
 * The backend streams ``text/csv`` bytes via ``StreamingResponse``; here we
 * request ``responseType: "blob"`` so axios exposes the body as a Blob the
 * caller can hand to ``URL.createObjectURL`` for a browser download. The
 * shared ``apiClient`` adds the auth header and X-Correlation-Id automatically.
 *
 * Args:
 *   runId: ULID of the run to export.
 *   signal: Optional AbortSignal for request cancellation.
 *
 * Returns:
 *   A Blob containing the CSV body; the MIME type is preserved from the
 *   server response (``text/csv``).
 *
 * Raises:
 *   RunResultsNotFoundError, RunResultsConflictError, RunResultsAuthError,
 *   RunResultsValidationError, RunResultsNetworkError — same hierarchy as
 *   the JSON results helpers so the page can re-use its error formatter.
 *
 * Example:
 *   const blob = await exportBlotterCsv("01HRUN0000000000000000000A");
 *   const url = URL.createObjectURL(blob);
 *   const anchor = document.createElement("a");
 *   anchor.href = url;
 *   anchor.download = "run-01HRUN…-blotter.csv";
 *   anchor.click();
 *   URL.revokeObjectURL(url);
 */
export async function exportBlotterCsv(runId: string, signal?: AbortSignal): Promise<Blob> {
  try {
    const resp = await apiClient.get<Blob>(`/runs/${runId}/exports/blotter.csv`, {
      responseType: "blob",
      signal,
    });
    return resp.data;
  } catch (err) {
    throw normalizeError(err, runId);
  }
}
