/**
 * Results Explorer structured logger — typed log events for observability.
 *
 * Purpose:
 *   Provide structured, typed logging for all Results Explorer operations.
 *   Follows CLAUDE.md §8 structured logging standards with operation name,
 *   correlation ID, component, duration, and result fields.
 *
 * Responsibilities:
 *   - Log API fetch lifecycle (start, success, failure, retry).
 *   - Log download lifecycle (start, success, failure, abort).
 *   - Log validation failures (Zod schema mismatch).
 *   - Log page lifecycle (mount, unmount).
 *   - Add Sentry breadcrumbs for user action trail.
 *   - Report errors to Sentry with structured context.
 *
 * Does NOT:
 *   - Contain business logic.
 *   - Block user interactions (all logging is synchronous console calls).
 *   - Log PII, secrets, or auth tokens.
 *
 * Dependencies:
 *   - @/infrastructure/sentry for error reporting.
 *
 * Example:
 *   resultsLogger.fetchStart("01HRUN...");
 *   resultsLogger.fetchRetry("01HRUN...", 1, 3, 1000);
 *   resultsLogger.fetchSuccess("01HRUN...", 150, { pointCount: 2000 });
 *   resultsLogger.fetchFailure("01HRUN...", error, 150);
 */

import { Sentry } from "@/infrastructure/sentry";

/** Structured log extra fields per CLAUDE.md §8. */
interface LogExtra {
  operation: string;
  component: string;
  correlation_id?: string;
  duration_ms?: number;
  result?: "success" | "failure" | "partial" | "abort";
  [key: string]: unknown;
}

/**
 * Emit a structured log event and add a Sentry breadcrumb.
 *
 * Args:
 *   level: Log severity.
 *   message: Human-readable log message.
 *   extra: Structured key-value fields.
 */
function emit(level: "debug" | "info" | "warn" | "error", message: string, extra: LogExtra): void {
  const entry = { ...extra, timestamp: new Date().toISOString() };

  // Add Sentry breadcrumb for user action trail.
  Sentry.addBreadcrumb({
    category: "results-explorer",
    message,
    level: level === "debug" ? "debug" : level === "warn" ? "warning" : level,
    data: { operation: extra.operation, run_id: extra.run_id, result: extra.result },
  });

  switch (level) {
    case "debug":
      // eslint-disable-next-line no-console
      console.debug(`[ResultsExplorer] ${message}`, entry);
      break;
    case "info":
      // eslint-disable-next-line no-console
      console.info(`[ResultsExplorer] ${message}`, entry);
      break;
    case "warn":
      // eslint-disable-next-line no-console
      console.warn(`[ResultsExplorer] ${message}`, entry);
      break;
    case "error":
      // eslint-disable-next-line no-console
      console.error(`[ResultsExplorer] ${message}`, entry);
      break;
  }
}

/**
 * Structured logger for the Results Explorer feature.
 *
 * All methods follow the CLAUDE.md §8 structured logging pattern:
 * operation, component, correlation_id, duration_ms, result.
 */
export const resultsLogger = {
  // -------------------------------------------------------------------------
  // API fetch lifecycle
  // -------------------------------------------------------------------------

  /** Log the start of a run charts fetch. */
  fetchStart(runId: string, correlationId?: string): void {
    emit("info", "Fetching run charts", {
      operation: "results.fetch_run_charts",
      component: "resultsApi",
      run_id: runId,
      correlation_id: correlationId,
    });
  },

  /**
   * Log a retry attempt with attempt number and delay.
   *
   * Args:
   *   runId: Run ID being fetched.
   *   attempt: Current retry attempt (1-based).
   *   maxRetries: Maximum retries configured.
   *   delayMs: Backoff delay before this attempt in ms.
   *   correlationId: Optional correlation ID for request tracing.
   */
  fetchRetry(
    runId: string,
    attempt: number,
    maxRetries: number,
    delayMs: number,
    correlationId?: string,
  ): void {
    emit("warn", `Retrying fetch (attempt ${attempt} of ${maxRetries})`, {
      operation: "results.fetch_run_charts",
      component: "resultsApi",
      run_id: runId,
      attempt,
      max_retries: maxRetries,
      delay_ms: Math.round(delayMs),
      correlation_id: correlationId,
    });
  },

  /** Log a successful run charts fetch. */
  fetchSuccess(
    runId: string,
    durationMs: number,
    meta: { pointCount: number; tradeCount: number },
    correlationId?: string,
  ): void {
    emit("info", "Run charts fetched successfully", {
      operation: "results.fetch_run_charts",
      component: "resultsApi",
      result: "success",
      run_id: runId,
      duration_ms: durationMs,
      equity_point_count: meta.pointCount,
      trade_count: meta.tradeCount,
      correlation_id: correlationId,
    });
  },

  /** Log a failed run charts fetch. */
  fetchFailure(runId: string, error: unknown, durationMs: number, correlationId?: string): void {
    const errorMessage = error instanceof Error ? error.message : String(error);
    emit("error", "Run charts fetch failed", {
      operation: "results.fetch_run_charts",
      component: "resultsApi",
      result: "failure",
      run_id: runId,
      duration_ms: durationMs,
      error: errorMessage,
      correlation_id: correlationId,
    });
    Sentry.captureException(error, {
      tags: { feature: "ResultsExplorer", operation: "fetch_run_charts" },
      contexts: {
        results: { run_id: runId, duration_ms: durationMs, correlation_id: correlationId },
      },
    });
  },

  /** Log a Zod schema validation failure. */
  validationFailure(runId: string, errors: unknown, correlationId?: string): void {
    const errorCount = Array.isArray(errors) ? errors.length : 1;
    emit("warn", `Run charts response failed schema validation (${errorCount} issue(s))`, {
      operation: "results.fetch_run_charts",
      component: "resultsApi",
      result: "failure",
      run_id: runId,
      validation_error_count: errorCount,
      validation_errors: errors,
      correlation_id: correlationId,
    });
    Sentry.captureException(new Error("RunChartsPayload schema validation failed"), {
      tags: { feature: "ResultsExplorer", operation: "schema_validation" },
      contexts: { results: { run_id: runId, error_count: errorCount } },
    });
  },

  // -------------------------------------------------------------------------
  // Download lifecycle
  // -------------------------------------------------------------------------

  /** Log the start of an export download. */
  downloadStart(runId: string): void {
    emit("info", "Starting export bundle download", {
      operation: "results.download_export_bundle",
      component: "resultsApi",
      run_id: runId,
    });
  },

  /** Log a successful export download. */
  downloadSuccess(runId: string, durationMs: number, sizeBytes: number): void {
    emit("info", "Export bundle downloaded successfully", {
      operation: "results.download_export_bundle",
      component: "resultsApi",
      result: "success",
      run_id: runId,
      duration_ms: durationMs,
      size_bytes: sizeBytes,
    });
  },

  /** Log a failed export download. */
  downloadFailure(runId: string, error: unknown, durationMs: number): void {
    const errorMessage = error instanceof Error ? error.message : String(error);
    emit("error", "Export bundle download failed", {
      operation: "results.download_export_bundle",
      component: "resultsApi",
      result: "failure",
      run_id: runId,
      duration_ms: durationMs,
      error: errorMessage,
    });
    Sentry.captureException(error, {
      tags: { feature: "ResultsExplorer", operation: "download_export" },
      contexts: { results: { run_id: runId, duration_ms: durationMs } },
    });
  },

  /** Log a cancelled export download. */
  downloadAborted(runId: string): void {
    emit("info", "Export bundle download aborted", {
      operation: "results.download_export_bundle",
      component: "resultsApi",
      result: "abort",
      run_id: runId,
    });
  },

  // -------------------------------------------------------------------------
  // Page lifecycle
  // -------------------------------------------------------------------------

  /** Log results page mount. */
  pageMount(runId: string): void {
    emit("info", "Results page mounted", {
      operation: "results.render_page",
      component: "RunResultsPage",
      run_id: runId,
    });
  },

  /** Log results page unmount/cleanup. */
  pageUnmount(runId: string): void {
    emit("debug", "Results page unmounting", {
      operation: "results.render_page",
      component: "RunResultsPage",
      run_id: runId,
    });
  },
};
