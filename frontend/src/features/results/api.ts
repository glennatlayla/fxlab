/**
 * Results Explorer API service — HTTP calls with retry, logging, and error classification.
 *
 * Purpose:
 *   Centralise all results/chart-related API calls behind typed functions.
 *   Implements CLAUDE.md §9 retry policy with exponential backoff for transient
 *   failures and fail-fast for permanent errors. All operations are instrumented
 *   with structured logging per §8.
 *
 * Responsibilities:
 *   - Fetch run chart data via GET /runs/{run_id}/charts with retry.
 *   - Trigger zip bundle export via GET /runs/{run_id}/export with abort support.
 *   - Validate all API responses at runtime with Zod schemas.
 *   - Validate download blob MIME type before returning.
 *   - Classify errors (transient vs permanent, auth vs network) for retry decisions.
 *   - Log all operations with structured fields including correlation ID.
 *
 * Does NOT:
 *   - Contain business logic or chart rendering.
 *   - Manage state (that's the hooks' and components' job).
 *   - Handle auth (apiClient interceptors handle Bearer tokens).
 *
 * Dependencies:
 *   - @/api/client (axios instance with auth + correlation ID injection).
 *   - @/types/results for typed response shapes.
 *   - @/types/results.schemas for Zod runtime validation.
 *   - ./errors for domain error types.
 *   - ./logger for structured logging.
 *   - ./constants for retry and timeout configuration.
 *
 * Error conditions:
 *   - ResultsNotFoundError: 404 — run does not exist.
 *   - ResultsAuthError: 401/403 — authentication or authorisation failure.
 *   - ResultsValidationError: Zod schema mismatch.
 *   - ResultsNetworkError: transient (5xx, 429, timeout) — retried.
 *   - ResultsDownloadError: download-specific failure.
 *
 * Example:
 *   const charts = await resultsApi.getRunCharts("01HRUN...");
 *   const blob = await resultsApi.downloadExportBundle("01HRUN...", signal);
 */

import { AxiosError } from "axios";
import { ZodError } from "zod";
import { apiClient } from "@/api/client";
import type { RunChartsPayload } from "@/types/results";
import { RunChartsPayloadSchema } from "@/types/results.schemas";
import {
  ResultsNotFoundError,
  ResultsAuthError,
  ResultsValidationError,
  ResultsNetworkError,
  ResultsDownloadError,
  isTransientError,
} from "./errors";
import { resultsLogger } from "./logger";
import {
  API_MAX_RETRIES,
  API_RETRY_BASE_DELAY_MS,
  API_JITTER_FACTOR,
  DOWNLOAD_TIMEOUT_MS,
  EXPORT_BLOB_MIME_TYPE,
} from "./constants";

// ---------------------------------------------------------------------------
// Internal helpers — exported for testing
// ---------------------------------------------------------------------------

/**
 * Compute the backoff delay for a retry attempt.
 *
 * Uses exponential backoff with configurable jitter per CLAUDE.md §9:
 *   delay = base * 2^attempt + random(0, base * 2^attempt * jitter_factor)
 *
 * Args:
 *   attempt: Zero-based retry attempt number.
 *
 * Returns:
 *   Delay in milliseconds.
 */
export function computeBackoffDelay(attempt: number): number {
  const base = API_RETRY_BASE_DELAY_MS * Math.pow(2, attempt);
  const jitter = Math.random() * base * API_JITTER_FACTOR;
  return base + jitter;
}

/**
 * Sleep for a given duration, cancellable via AbortSignal.
 *
 * Args:
 *   ms: Duration in milliseconds.
 *   signal: Optional AbortSignal for cancellation.
 *
 * Returns:
 *   Promise that resolves after the delay or rejects on abort.
 */
export function cancellableSleep(ms: number, signal?: AbortSignal): Promise<void> {
  return new Promise((resolve, reject) => {
    if (signal?.aborted) {
      reject(new DOMException("Aborted", "AbortError"));
      return;
    }

    const timer = setTimeout(resolve, ms);

    signal?.addEventListener(
      "abort",
      () => {
        clearTimeout(timer);
        reject(new DOMException("Aborted", "AbortError"));
      },
      { once: true },
    );
  });
}

/**
 * Classify an AxiosError into the appropriate domain error.
 *
 * Separates 401/403 (auth, fail-fast) from 404 (not-found, fail-fast)
 * from 5xx/429 (transient, retry).
 *
 * Args:
 *   err: The Axios error to classify.
 *   runId: Run ID for error context.
 *
 * Returns:
 *   A typed ResultsError subclass.
 */
export function classifyAxiosError(
  err: AxiosError,
  runId: string,
): ResultsNotFoundError | ResultsAuthError | ResultsNetworkError {
  const status = err.response?.status;
  if (status === 404) {
    return new ResultsNotFoundError(runId, err);
  }
  if (status === 401 || status === 403) {
    return new ResultsAuthError(runId, status, err);
  }
  return new ResultsNetworkError(runId, status, err);
}

// ---------------------------------------------------------------------------
// API service
// ---------------------------------------------------------------------------

export const resultsApi = {
  /**
   * Fetch the full charts payload for a completed run.
   *
   * Retries transient failures (5xx, 429, network timeout) up to
   * API_MAX_RETRIES times with exponential backoff and jitter.
   * Fails fast on 404, 401/403, and schema validation errors.
   *
   * Args:
   *   runId: ULID of the run whose results to fetch.
   *
   * Returns:
   *   RunChartsPayload with equity curve, trades, trials, and metrics.
   *
   * Raises:
   *   ResultsNotFoundError: Run does not exist (HTTP 404).
   *   ResultsAuthError: Authentication or authorisation failure (HTTP 401/403).
   *   ResultsValidationError: Response failed Zod schema validation.
   *   ResultsNetworkError: Transient failure after all retries exhausted.
   */
  async getRunCharts(runId: string): Promise<RunChartsPayload> {
    const startTime = performance.now();
    resultsLogger.fetchStart(runId);

    let lastError: unknown;

    for (let attempt = 0; attempt <= API_MAX_RETRIES; attempt++) {
      try {
        const resp = await apiClient.get<unknown>(`/runs/${runId}/charts`);

        let parsed: RunChartsPayload;
        try {
          parsed = RunChartsPayloadSchema.parse(resp.data);
        } catch (zodErr) {
          // Schema validation failure — permanent, do not retry.
          const validationErrors = zodErr instanceof ZodError ? zodErr.issues : zodErr;
          resultsLogger.validationFailure(runId, validationErrors);
          throw new ResultsValidationError(runId, validationErrors, zodErr);
        }

        const durationMs = Math.round(performance.now() - startTime);
        resultsLogger.fetchSuccess(runId, durationMs, {
          pointCount: parsed.equity_curve.length,
          tradeCount: parsed.trades.length,
        });
        return parsed;
      } catch (err) {
        // Domain errors (validation, not-found, auth) propagate immediately — no retry.
        if (
          err instanceof ResultsValidationError ||
          err instanceof ResultsNotFoundError ||
          err instanceof ResultsAuthError
        ) {
          throw err;
        }

        // Classify Axios errors into domain errors.
        if (err instanceof AxiosError) {
          const classified = classifyAxiosError(err, runId);

          // Non-transient errors: fail fast, no retry.
          if (!isTransientError(classified)) {
            const durationMs = Math.round(performance.now() - startTime);
            resultsLogger.fetchFailure(runId, classified, durationMs);
            throw classified;
          }

          lastError = classified;
        } else {
          // Non-Axios, non-domain error — fail fast, do not retry unknown errors.
          const durationMs = Math.round(performance.now() - startTime);
          resultsLogger.fetchFailure(runId, err, durationMs);
          throw err;
        }

        // Retry if we have attempts remaining.
        if (attempt < API_MAX_RETRIES) {
          const delayMs = computeBackoffDelay(attempt);
          resultsLogger.fetchRetry(runId, attempt + 1, API_MAX_RETRIES, delayMs);
          await cancellableSleep(delayMs);
        }
      }
    }

    // All retries exhausted.
    const durationMs = Math.round(performance.now() - startTime);
    resultsLogger.fetchFailure(runId, lastError, durationMs);
    if (lastError instanceof ResultsNetworkError) {
      throw lastError;
    }
    throw new ResultsNetworkError(runId, undefined, lastError);
  },

  /**
   * Download the export zip bundle for a completed run.
   *
   * Supports cancellation via AbortSignal. Uses DOWNLOAD_TIMEOUT_MS
   * as the request timeout. Validates the response blob MIME type
   * before returning. Does not retry (downloads can be large
   * and partially transferred).
   *
   * Args:
   *   runId: ULID of the run to export.
   *   signal: Optional AbortSignal for cancellation.
   *
   * Returns:
   *   Blob containing the zip archive (metadata.json + data files).
   *
   * Raises:
   *   ResultsNotFoundError: Run does not exist (HTTP 404).
   *   ResultsAuthError: Authentication or authorisation failure (HTTP 401/403).
   *   ResultsDownloadError: Timeout, abort, network failure, or invalid blob.
   */
  async downloadExportBundle(runId: string, signal?: AbortSignal): Promise<Blob> {
    const startTime = performance.now();
    resultsLogger.downloadStart(runId);

    try {
      const resp = await apiClient.get(`/runs/${runId}/export`, {
        responseType: "blob",
        timeout: DOWNLOAD_TIMEOUT_MS,
        signal,
      });

      const blob = resp.data as Blob;

      // Validate blob MIME type — guard against server returning HTML error pages.
      if (
        blob.type &&
        blob.type !== EXPORT_BLOB_MIME_TYPE &&
        !blob.type.startsWith("application/")
      ) {
        resultsLogger.downloadFailure(
          runId,
          new Error(`Unexpected MIME type: ${blob.type}`),
          Math.round(performance.now() - startTime),
        );
        throw new ResultsDownloadError(
          runId,
          "unknown",
          new Error(`Unexpected MIME type: ${blob.type}`),
        );
      }

      const durationMs = Math.round(performance.now() - startTime);
      resultsLogger.downloadSuccess(runId, durationMs, blob.size);
      return blob;
    } catch (err) {
      // Re-throw domain errors that were just classified above.
      if (err instanceof ResultsDownloadError) {
        throw err;
      }

      const durationMs = Math.round(performance.now() - startTime);

      // Cancelled by user.
      if (err instanceof DOMException && err.name === "AbortError") {
        resultsLogger.downloadAborted(runId);
        throw new ResultsDownloadError(runId, "abort", err);
      }

      // Axios error — classify.
      if (err instanceof AxiosError) {
        if (err.response?.status === 404) {
          resultsLogger.downloadFailure(runId, err, durationMs);
          throw new ResultsNotFoundError(runId, err);
        }
        if (err.response?.status === 401 || err.response?.status === 403) {
          resultsLogger.downloadFailure(runId, err, durationMs);
          throw new ResultsAuthError(runId, err.response.status as 401 | 403, err);
        }
        if (err.code === "ECONNABORTED") {
          resultsLogger.downloadFailure(runId, err, durationMs);
          throw new ResultsDownloadError(runId, "timeout", err);
        }
        resultsLogger.downloadFailure(runId, err, durationMs);
        throw new ResultsDownloadError(runId, "network", err);
      }

      resultsLogger.downloadFailure(runId, err, durationMs);
      throw new ResultsDownloadError(runId, "unknown", err);
    }
  },
};
