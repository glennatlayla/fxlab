/**
 * Readiness feature structured logger — typed log events for observability.
 *
 * Purpose:
 *   Provide structured, typed logging for all Readiness Report operations.
 *   Follows CLAUDE.md §8 structured logging standards with operation name,
 *   correlation ID, component, duration, and result fields.
 *
 * Responsibilities:
 *   - Log readiness report fetch lifecycle (start, success, failure).
 *   - Log report generation lifecycle.
 *   - Log promotion submission lifecycle.
 *   - Log validation failures.
 *   - Log page lifecycle (mount, unmount).
 *   - Add Sentry breadcrumbs for user action trail.
 *   - Report errors to Sentry with structured context.
 *
 * Does NOT:
 *   - Contain business logic.
 *   - Log PII, secrets, or auth tokens.
 *
 * Dependencies:
 *   - @/infrastructure/sentry for error reporting.
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

  Sentry.addBreadcrumb({
    category: "readiness",
    message,
    level: level === "debug" ? "debug" : level === "warn" ? "warning" : level,
    data: { operation: extra.operation, run_id: extra.run_id, result: extra.result },
  });

  switch (level) {
    case "debug":
      // eslint-disable-next-line no-console
      console.debug(`[Readiness] ${message}`, entry);
      break;
    case "info":
      // eslint-disable-next-line no-console
      console.info(`[Readiness] ${message}`, entry);
      break;
    case "warn":
      // eslint-disable-next-line no-console
      console.warn(`[Readiness] ${message}`, entry);
      break;
    case "error":
      // eslint-disable-next-line no-console
      console.error(`[Readiness] ${message}`, entry);
      break;
  }
}

/**
 * Structured logger for the Readiness Report Viewer feature.
 *
 * All methods follow CLAUDE.md §8 structured logging pattern.
 */
export const readinessLogger = {
  // -------------------------------------------------------------------------
  // Report fetch lifecycle
  // -------------------------------------------------------------------------

  fetchStart(runId: string, correlationId?: string): void {
    emit("info", "Fetching readiness report", {
      operation: "readiness.fetch_report",
      component: "readinessApi",
      run_id: runId,
      correlation_id: correlationId,
    });
  },

  fetchSuccess(
    runId: string,
    durationMs: number,
    meta: { grade: string; score: number; dimensionCount: number },
    correlationId?: string,
  ): void {
    emit("info", "Readiness report fetched successfully", {
      operation: "readiness.fetch_report",
      component: "readinessApi",
      result: "success",
      run_id: runId,
      duration_ms: durationMs,
      grade: meta.grade,
      score: meta.score,
      dimension_count: meta.dimensionCount,
      correlation_id: correlationId,
    });
  },

  fetchFailure(runId: string, error: unknown, durationMs: number, correlationId?: string): void {
    const errorMessage = error instanceof Error ? error.message : String(error);
    emit("error", "Readiness report fetch failed", {
      operation: "readiness.fetch_report",
      component: "readinessApi",
      result: "failure",
      run_id: runId,
      duration_ms: durationMs,
      error: errorMessage,
      correlation_id: correlationId,
    });
    Sentry.captureException(error, {
      tags: { feature: "Readiness", operation: "fetch_report" },
      contexts: {
        readiness: { run_id: runId, duration_ms: durationMs, correlation_id: correlationId },
      },
    });
  },

  fetchRetry(
    runId: string,
    attempt: number,
    maxRetries: number,
    delayMs: number,
    correlationId?: string,
  ): void {
    emit("warn", `Retrying readiness fetch (attempt ${attempt} of ${maxRetries})`, {
      operation: "readiness.fetch_report",
      component: "readinessApi",
      run_id: runId,
      attempt,
      max_retries: maxRetries,
      delay_ms: Math.round(delayMs),
      correlation_id: correlationId,
    });
  },

  // -------------------------------------------------------------------------
  // Report generation lifecycle
  // -------------------------------------------------------------------------

  generateStart(runId: string, correlationId?: string): void {
    emit("info", "Generating readiness report", {
      operation: "readiness.generate_report",
      component: "readinessApi",
      run_id: runId,
      correlation_id: correlationId,
    });
  },

  generateSuccess(runId: string, durationMs: number, grade: string, correlationId?: string): void {
    emit("info", "Readiness report generated successfully", {
      operation: "readiness.generate_report",
      component: "readinessApi",
      result: "success",
      run_id: runId,
      duration_ms: durationMs,
      grade,
      correlation_id: correlationId,
    });
  },

  generateFailure(runId: string, error: unknown, durationMs: number, correlationId?: string): void {
    const errorMessage = error instanceof Error ? error.message : String(error);
    emit("error", "Readiness report generation failed", {
      operation: "readiness.generate_report",
      component: "readinessApi",
      result: "failure",
      run_id: runId,
      duration_ms: durationMs,
      error: errorMessage,
      correlation_id: correlationId,
    });
    Sentry.captureException(error, {
      tags: { feature: "Readiness", operation: "generate_report" },
      contexts: {
        readiness: { run_id: runId, duration_ms: durationMs, correlation_id: correlationId },
      },
    });
  },

  // -------------------------------------------------------------------------
  // Promotion submission lifecycle
  // -------------------------------------------------------------------------

  promotionStart(runId: string, correlationId?: string): void {
    emit("info", "Submitting for promotion", {
      operation: "readiness.submit_promotion",
      component: "readinessApi",
      run_id: runId,
      correlation_id: correlationId,
    });
  },

  promotionSuccess(runId: string, durationMs: number, correlationId?: string): void {
    emit("info", "Promotion submitted successfully", {
      operation: "readiness.submit_promotion",
      component: "readinessApi",
      result: "success",
      run_id: runId,
      duration_ms: durationMs,
      correlation_id: correlationId,
    });
  },

  promotionFailure(
    runId: string,
    error: unknown,
    durationMs: number,
    correlationId?: string,
  ): void {
    const errorMessage = error instanceof Error ? error.message : String(error);
    emit("error", "Promotion submission failed", {
      operation: "readiness.submit_promotion",
      component: "readinessApi",
      result: "failure",
      run_id: runId,
      duration_ms: durationMs,
      error: errorMessage,
      correlation_id: correlationId,
    });
    Sentry.captureException(error, {
      tags: { feature: "Readiness", operation: "submit_promotion" },
      contexts: {
        readiness: { run_id: runId, duration_ms: durationMs, correlation_id: correlationId },
      },
    });
  },

  // -------------------------------------------------------------------------
  // Validation
  // -------------------------------------------------------------------------

  validationFailure(runId: string, errors: unknown, correlationId?: string): void {
    const errorCount = Array.isArray(errors) ? errors.length : 1;
    emit("warn", `Readiness report response failed schema validation (${errorCount} issue(s))`, {
      operation: "readiness.fetch_report",
      component: "readinessApi",
      result: "failure",
      run_id: runId,
      validation_error_count: errorCount,
      validation_errors: errors,
      correlation_id: correlationId,
    });
    Sentry.captureException(new Error("ReadinessReportPayload schema validation failed"), {
      tags: { feature: "Readiness", operation: "schema_validation" },
      contexts: { readiness: { run_id: runId, error_count: errorCount } },
    });
  },

  // -------------------------------------------------------------------------
  // Page lifecycle
  // -------------------------------------------------------------------------

  pageMount(runId: string, correlationId?: string): void {
    emit("info", "Readiness page mounted", {
      operation: "readiness.render_page",
      component: "RunReadinessPage",
      run_id: runId,
      correlation_id: correlationId,
    });
  },

  pageUnmount(runId: string, correlationId?: string): void {
    emit("debug", "Readiness page unmounting", {
      operation: "readiness.render_page",
      component: "RunReadinessPage",
      run_id: runId,
      correlation_id: correlationId,
    });
  },
};
