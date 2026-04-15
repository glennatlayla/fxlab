/**
 * useRunSubmission — Hook for submitting research and optimization runs.
 *
 * Purpose:
 *   Provide a typed, state-managed interface for submitting runs to the
 *   backend. Handles loading state, error state, transient failure retry,
 *   and success navigation. Emits structured log events via RunLogger (§8).
 *
 * Responsibilities:
 *   - Submit research runs via runsApi.submitResearchRun.
 *   - Submit optimization runs via runsApi.submitOptimizationRun.
 *   - Retry transient failures (5xx, network errors) with exponential backoff (§9).
 *   - Track submission loading and error state.
 *   - Return the created RunRecord on success for navigation.
 *   - Log submission lifecycle events for observability.
 *
 * Does NOT:
 *   - Handle polling (see useRunPolling).
 *   - Handle form validation (that's the component's job).
 *   - Handle cancellation (see runsApi.cancelRun).
 *   - Retry permanent failures (400, 401, 403, 404, 422).
 *
 * Dependencies:
 *   - runsApi for HTTP calls (repository layer).
 *   - RunMonitorService for transient error detection (service layer).
 *   - RunLogger for structured logging (infrastructure layer).
 *   - @/types/run for submission payload types.
 *
 * Error conditions:
 *   - Network failure → retries up to SUBMISSION_MAX_RETRIES, then sets error.
 *   - 5xx server error → retries with exponential backoff + jitter.
 *   - 422 validation error → immediate failure, no retry.
 *   - Preflight failure → sets error; caller should check run.preflight_results.
 *
 * Example:
 *   const { submitResearch, submitOptimization, isSubmitting, error } = useRunSubmission();
 *   const run = await submitResearch({ strategy_build_id: "...", config: {...} });
 *   navigate(`/runs/${run.id}`);
 */

import { useState, useCallback, useRef } from "react";
import type { RunRecord, ResearchRunSubmission, OptimizationRunSubmission } from "@/types/run";
import { runsApi } from "./api";
import {
  isTransientError,
  SUBMISSION_MAX_RETRIES,
  SUBMISSION_RETRY_BASE_MS,
  calculateRetryDelay,
} from "./services/RunMonitorService";
import { RunLogger } from "./services/RunLogger";

// ---------------------------------------------------------------------------
// Hook return type
// ---------------------------------------------------------------------------

/** Return value of useRunSubmission hook. */
export interface UseRunSubmissionResult {
  /** Submit a research run. Returns the created RunRecord on success. */
  submitResearch: (payload: ResearchRunSubmission) => Promise<RunRecord>;
  /** Submit an optimization run. Returns the created RunRecord on success. */
  submitOptimization: (payload: OptimizationRunSubmission) => Promise<RunRecord>;
  /** True while a submission request is in flight. */
  isSubmitting: boolean;
  /** Error from the most recent failed submission (null on success). */
  error: Error | null;
  /** Clear the current error state (e.g., before retrying). */
  clearError: () => void;
}

// ---------------------------------------------------------------------------
// Internal retry helper
// ---------------------------------------------------------------------------

/**
 * Sleep for a given number of milliseconds.
 *
 * Args:
 *   ms: Duration in milliseconds.
 *
 * Returns:
 *   Promise that resolves after the delay.
 */
function sleep(ms: number): Promise<void> {
  return new Promise((resolve) => setTimeout(resolve, ms));
}

/**
 * Execute an async function with transient failure retry.
 *
 * Retries on transient errors (5xx, network) with exponential backoff + jitter.
 * Does NOT retry on permanent failures (4xx client errors).
 * Logs each retry attempt via RunLogger.
 *
 * Args:
 *   fn: Async function to execute.
 *   maxRetries: Maximum number of retry attempts.
 *   baseMs: Base delay for backoff calculation.
 *   logger: RunLogger instance for structured logging.
 *   runType: "research" or "optimization" (for logging context).
 *
 * Returns:
 *   Result of the successful function call.
 *
 * Raises:
 *   The last error if all retries are exhausted or error is non-transient.
 */
async function withTransientRetry<T>(
  fn: () => Promise<T>,
  maxRetries: number,
  baseMs: number,
  logger: RunLogger,
  runType: string,
): Promise<T> {
  let lastError: Error | undefined;

  for (let attempt = 0; attempt <= maxRetries; attempt++) {
    try {
      return await fn();
    } catch (err) {
      lastError = err instanceof Error ? err : new Error(String(err));

      // Don't retry non-transient errors (4xx, validation, auth)
      if (!isTransientError(err)) {
        throw lastError;
      }

      // Don't retry if we've exhausted all attempts
      if (attempt >= maxRetries) {
        throw lastError;
      }

      // Log retry attempt (fire-and-forget)
      logger.logSubmissionFailed(runType, lastError, 0);

      // Wait with exponential backoff + jitter before retrying
      const delay = calculateRetryDelay(attempt, baseMs);
      await sleep(delay);
    }
  }

  // TypeScript exhaustiveness — should never reach here
  throw lastError ?? new Error("Retry exhausted");
}

// ---------------------------------------------------------------------------
// Hook implementation
// ---------------------------------------------------------------------------

/**
 * Manage run submission lifecycle with retry and structured logging.
 *
 * Returns:
 *   UseRunSubmissionResult with submit functions, loading, and error state.
 */
export function useRunSubmission(): UseRunSubmissionResult {
  const [isSubmitting, setIsSubmitting] = useState<boolean>(false);
  const [error, setError] = useState<Error | null>(null);
  const loggerRef = useRef<RunLogger>(new RunLogger());

  const clearError = useCallback(() => {
    setError(null);
  }, []);

  /**
   * Submit a research run with transient failure retry.
   *
   * Args:
   *   payload: Research run configuration.
   *
   * Returns:
   *   RunRecord for the newly created run.
   *
   * Raises:
   *   Re-throws after setting error state so the caller can also handle.
   */
  const submitResearch = useCallback(async (payload: ResearchRunSubmission): Promise<RunRecord> => {
    const startMs = Date.now();
    setIsSubmitting(true);
    setError(null);

    // Structured logging: submission started (fire-and-forget)
    loggerRef.current.logSubmissionStarted("research", payload.strategy_build_id);

    try {
      const run = await withTransientRetry(
        () => runsApi.submitResearchRun(payload),
        SUBMISSION_MAX_RETRIES,
        SUBMISSION_RETRY_BASE_MS,
        loggerRef.current,
        "research",
      );

      // Structured logging: submission succeeded
      loggerRef.current.logSubmissionSucceeded(run.id, "research", Date.now() - startMs);

      return run;
    } catch (err) {
      const submissionError = err instanceof Error ? err : new Error(String(err));
      setError(submissionError);

      // Structured logging: submission failed (final failure after retries)
      loggerRef.current.logSubmissionFailed("research", submissionError, Date.now() - startMs);

      throw submissionError;
    } finally {
      setIsSubmitting(false);
    }
  }, []);

  /**
   * Submit an optimization run with transient failure retry.
   *
   * Args:
   *   payload: Optimization run configuration.
   *
   * Returns:
   *   RunRecord for the newly created run.
   *
   * Raises:
   *   Re-throws after setting error state so the caller can also handle.
   */
  const submitOptimization = useCallback(
    async (payload: OptimizationRunSubmission): Promise<RunRecord> => {
      const startMs = Date.now();
      setIsSubmitting(true);
      setError(null);

      // Structured logging: submission started
      loggerRef.current.logSubmissionStarted("optimization", payload.strategy_build_id);

      try {
        const run = await withTransientRetry(
          () => runsApi.submitOptimizationRun(payload),
          SUBMISSION_MAX_RETRIES,
          SUBMISSION_RETRY_BASE_MS,
          loggerRef.current,
          "optimization",
        );

        // Structured logging: submission succeeded
        loggerRef.current.logSubmissionSucceeded(run.id, "optimization", Date.now() - startMs);

        return run;
      } catch (err) {
        const submissionError = err instanceof Error ? err : new Error(String(err));
        setError(submissionError);

        // Structured logging: submission failed (final failure after retries)
        loggerRef.current.logSubmissionFailed(
          "optimization",
          submissionError,
          Date.now() - startMs,
        );

        throw submissionError;
      } finally {
        setIsSubmitting(false);
      }
    },
    [],
  );

  return {
    submitResearch,
    submitOptimization,
    isSubmitting,
    error,
    clearError,
  };
}
