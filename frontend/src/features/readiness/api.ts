/**
 * Readiness feature API layer — data fetching with retry and error classification.
 *
 * Purpose:
 *   Fetch and generate readiness reports from the backend API.
 *   Implements retry logic for transient failures per CLAUDE.md §9.
 *
 * Responsibilities:
 *   - Fetch readiness report for a run (GET /runs/{runId}/readiness).
 *   - Generate a new readiness report (POST /runs/{runId}/readiness).
 *   - Submit for promotion (POST /promotions/request).
 *   - Retry transient errors with exponential backoff + jitter.
 *   - Classify errors into domain-specific types.
 *   - Validate responses with Zod schemas.
 *
 * Does NOT:
 *   - Contain business logic or UI rendering.
 *   - Manage React state or caching (TanStack Query handles that).
 *
 * Dependencies:
 *   - axios for HTTP requests.
 *   - Zod schemas from @/types/readiness.
 *   - Error types from ./errors.
 *   - Logger from ./logger.
 *   - Constants from ./constants.
 *
 * Example:
 *   const report = await readinessApi.getReadinessReport("01HRUN...");
 *   await readinessApi.generateReadinessReport("01HRUN...");
 */

import axios, { AxiosError } from "axios";
import { ReadinessReportPayloadSchema, PromotionResponseSchema } from "@/types/readiness";
import type { ReadinessReportPayload } from "@/types/readiness";
import {
  ReadinessNotFoundError,
  ReadinessAuthError,
  ReadinessNetworkError,
  ReadinessValidationError,
  ReadinessGenerationError,
  isTransientError,
} from "./errors";
import { readinessLogger } from "./logger";
import {
  READINESS_API_MAX_RETRIES,
  READINESS_API_RETRY_BASE_DELAY_MS,
  READINESS_API_JITTER_FACTOR,
} from "./constants";

// ---------------------------------------------------------------------------
// Utility functions — exported for testability
// ---------------------------------------------------------------------------

/**
 * Compute exponential backoff delay with jitter.
 *
 * Args:
 *   attempt: Zero-based attempt index.
 *
 * Returns:
 *   Delay in milliseconds.
 *
 * Example:
 *   computeBackoffDelay(0) // ~1000-1250ms
 *   computeBackoffDelay(1) // ~2000-2500ms
 */
export function computeBackoffDelay(attempt: number): number {
  const base = READINESS_API_RETRY_BASE_DELAY_MS * Math.pow(2, attempt);
  const jitter = Math.random() * base * READINESS_API_JITTER_FACTOR;
  return base + jitter;
}

/**
 * Cancellable sleep that resolves after the given delay or rejects if
 * the AbortSignal fires. Uses a real setTimeout so fake timers in tests
 * can control it via vi.advanceTimersByTimeAsync().
 *
 * Args:
 *   ms: Delay in milliseconds.
 *   signal: Optional AbortSignal for cancellation.
 *
 * Returns:
 *   Promise that resolves after the delay.
 *
 * Raises:
 *   DOMException (AbortError) if signal is aborted.
 */
export function cancellableSleep(ms: number, signal?: AbortSignal): Promise<void> {
  return new Promise<void>((resolve, reject) => {
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
 * Classify an AxiosError into a domain-specific readiness error.
 *
 * Args:
 *   err: The AxiosError to classify.
 *   runId: Run ID for error context.
 *
 * Returns:
 *   A ReadinessNotFoundError, ReadinessAuthError, or ReadinessNetworkError.
 */
export function classifyAxiosError(
  err: AxiosError,
  runId: string,
): ReadinessNotFoundError | ReadinessAuthError | ReadinessNetworkError {
  const status = err.response?.status;
  if (status === 404) return new ReadinessNotFoundError(runId, err);
  if (status === 401) return new ReadinessAuthError(runId, 401, err);
  if (status === 403) return new ReadinessAuthError(runId, 403, err);
  return new ReadinessNetworkError(runId, status, err);
}

// ---------------------------------------------------------------------------
// API client
// ---------------------------------------------------------------------------

/**
 * Readiness API client.
 *
 * All methods throw domain-specific errors from ./errors.ts.
 * Transient failures are retried per CLAUDE.md §9.
 */
export const readinessApi = {
  /**
   * Fetch the readiness report for a run.
   *
   * Args:
   *   runId: ULID of the run.
   *   correlationId: Optional correlation ID for structured log tracing.
   *
   * Returns:
   *   Validated ReadinessReportPayload.
   *
   * Raises:
   *   ReadinessNotFoundError: Run or report does not exist (404).
   *   ReadinessAuthError: Authentication/authorization failure (401/403).
   *   ReadinessValidationError: Response fails Zod schema.
   *   ReadinessNetworkError: Transient failure after all retries.
   */
  async getReadinessReport(runId: string, correlationId?: string): Promise<ReadinessReportPayload> {
    const startTime = performance.now();
    readinessLogger.fetchStart(runId, correlationId);

    let lastError: ReadinessNetworkError | null = null;

    for (let attempt = 0; attempt <= READINESS_API_MAX_RETRIES; attempt++) {
      try {
        const response = await axios.get(`/api/runs/${runId}/readiness`);

        // Validate response against Zod schema.
        const parseResult = ReadinessReportPayloadSchema.safeParse(response.data);
        if (!parseResult.success) {
          readinessLogger.validationFailure(runId, parseResult.error.issues, correlationId);
          throw new ReadinessValidationError(runId, parseResult.error.issues, parseResult.error);
        }

        const durationMs = Math.round(performance.now() - startTime);
        readinessLogger.fetchSuccess(
          runId,
          durationMs,
          {
            grade: parseResult.data.grade,
            score: parseResult.data.score,
            dimensionCount: parseResult.data.dimensions.length,
          },
          correlationId,
        );
        return parseResult.data;
      } catch (err) {
        // Re-throw domain errors that should not be retried.
        if (
          err instanceof ReadinessNotFoundError ||
          err instanceof ReadinessAuthError ||
          err instanceof ReadinessValidationError
        ) {
          throw err;
        }

        // Classify Axios errors into domain errors.
        if (err instanceof AxiosError) {
          const classified = classifyAxiosError(err, runId);

          // Non-transient errors: fail fast.
          if (!isTransientError(classified)) {
            const durationMs = Math.round(performance.now() - startTime);
            readinessLogger.fetchFailure(runId, classified, durationMs, correlationId);
            throw classified;
          }

          lastError = classified;
        } else {
          // Non-Axios, non-domain error — fail fast.
          const durationMs = Math.round(performance.now() - startTime);
          readinessLogger.fetchFailure(runId, err, durationMs, correlationId);
          throw err;
        }

        // Retry if attempts remain.
        if (attempt < READINESS_API_MAX_RETRIES) {
          const delayMs = computeBackoffDelay(attempt);
          readinessLogger.fetchRetry(
            runId,
            attempt + 1,
            READINESS_API_MAX_RETRIES,
            delayMs,
            correlationId,
          );
          await cancellableSleep(delayMs);
        }
      }
    }

    // All retries exhausted.
    const durationMs = Math.round(performance.now() - startTime);
    readinessLogger.fetchFailure(runId, lastError, durationMs, correlationId);
    if (lastError instanceof ReadinessNetworkError) {
      throw lastError;
    }
    throw new ReadinessNetworkError(runId, undefined, lastError);
  },

  /**
   * Generate a new readiness report for a run.
   *
   * Requires runs:write scope. Does NOT retry (generation is idempotent
   * but potentially expensive — let the user manually retry).
   *
   * Args:
   *   runId: ULID of the run.
   *   correlationId: Optional correlation ID for structured log tracing.
   *
   * Returns:
   *   Validated ReadinessReportPayload (the freshly generated report).
   *
   * Raises:
   *   ReadinessNotFoundError: Run does not exist (404).
   *   ReadinessAuthError: Missing runs:write scope (401/403).
   *   ReadinessGenerationError: Server-side generation failure.
   */
  async generateReadinessReport(
    runId: string,
    correlationId?: string,
  ): Promise<ReadinessReportPayload> {
    const startTime = performance.now();
    readinessLogger.generateStart(runId, correlationId);

    try {
      const response = await axios.post(`/api/runs/${runId}/readiness`);

      const parseResult = ReadinessReportPayloadSchema.safeParse(response.data);
      if (!parseResult.success) {
        readinessLogger.validationFailure(runId, parseResult.error.issues, correlationId);
        throw new ReadinessValidationError(runId, parseResult.error.issues, parseResult.error);
      }

      const durationMs = Math.round(performance.now() - startTime);
      readinessLogger.generateSuccess(runId, durationMs, parseResult.data.grade, correlationId);
      return parseResult.data;
    } catch (err) {
      if (
        err instanceof ReadinessValidationError ||
        err instanceof ReadinessNotFoundError ||
        err instanceof ReadinessAuthError
      ) {
        throw err;
      }
      if (err instanceof AxiosError) {
        const status = err.response?.status;
        if (status === 404) throw new ReadinessNotFoundError(runId, err);
        if (status === 401) throw new ReadinessAuthError(runId, 401, err);
        if (status === 403) throw new ReadinessAuthError(runId, 403, err);

        const durationMs = Math.round(performance.now() - startTime);
        readinessLogger.generateFailure(runId, err, durationMs, correlationId);
        throw new ReadinessGenerationError(runId, status, err);
      }
      const durationMs = Math.round(performance.now() - startTime);
      readinessLogger.generateFailure(runId, err, durationMs, correlationId);
      throw err;
    }
  },

  /**
   * Submit a run for promotion to the next stage.
   *
   * Args:
   *   runId: ULID of the run to promote.
   *   rationale: Free-text rationale for the promotion request.
   *   targetStage: Target deployment stage (e.g., "paper", "live").
   *   correlationId: Optional correlation ID for structured log tracing.
   *
   * Returns:
   *   Promotion request ID.
   *
   * Raises:
   *   ReadinessAuthError: Missing request_promotion scope (401/403).
   *   ReadinessValidationError: Response fails Zod schema.
   *   ReadinessNetworkError: Server failure.
   */
  async submitForPromotion(
    runId: string,
    rationale: string,
    targetStage: string,
    correlationId?: string,
  ): Promise<{ promotion_id: string }> {
    const startTime = performance.now();
    readinessLogger.promotionStart(runId, correlationId);

    try {
      const response = await axios.post("/api/promotions/request", {
        run_id: runId,
        rationale,
        target_stage: targetStage,
      });

      // Validate promotion response against Zod schema.
      const parseResult = PromotionResponseSchema.safeParse(response.data);
      if (!parseResult.success) {
        readinessLogger.validationFailure(runId, parseResult.error.issues, correlationId);
        throw new ReadinessValidationError(runId, parseResult.error.issues, parseResult.error);
      }

      const durationMs = Math.round(performance.now() - startTime);
      readinessLogger.promotionSuccess(runId, durationMs, correlationId);
      return parseResult.data;
    } catch (err) {
      if (err instanceof ReadinessValidationError || err instanceof ReadinessAuthError) {
        throw err;
      }
      if (err instanceof AxiosError) {
        const status = err.response?.status;
        if (status === 401) throw new ReadinessAuthError(runId, 401, err);
        if (status === 403) throw new ReadinessAuthError(runId, 403, err);

        const durationMs = Math.round(performance.now() - startTime);
        readinessLogger.promotionFailure(runId, err, durationMs, correlationId);
        throw new ReadinessNetworkError(runId, status, err);
      }
      const durationMs = Math.round(performance.now() - startTime);
      readinessLogger.promotionFailure(runId, err, durationMs, correlationId);
      throw err;
    }
  },
};
