/**
 * Parity feature structured logger — typed log events for observability.
 *
 * Purpose:
 *   Provide structured, typed logging for all parity operations (events,
 *   summary). Follows CLAUDE.md §8 with operation, correlation_id,
 *   component, duration_ms, and result fields. Adds Sentry breadcrumbs
 *   for the operator action trail.
 *
 * Does NOT:
 *   - Contain business logic.
 *   - Log PII, secrets, or auth tokens.
 */

import { Sentry } from "@/infrastructure/sentry";

interface LogExtra {
  operation: string;
  component: string;
  correlation_id?: string;
  duration_ms?: number;
  result?: "success" | "failure" | "partial" | "abort";
  [key: string]: unknown;
}

function emit(level: "debug" | "info" | "warn" | "error", message: string, extra: LogExtra): void {
  const entry = { ...extra, timestamp: new Date().toISOString() };

  Sentry.addBreadcrumb({
    category: "parity",
    message,
    level: level === "warn" ? "warning" : level,
    data: entry,
  });

  switch (level) {
    case "debug":
      // eslint-disable-next-line no-console
      console.debug(`[Parity] ${message}`, entry);
      break;
    case "info":
      // eslint-disable-next-line no-console
      console.info(`[Parity] ${message}`, entry);
      break;
    case "warn":
      console.warn(`[Parity] ${message}`, entry);
      break;
    case "error":
      console.error(`[Parity] ${message}`, entry);
      break;
  }
}

/** Parity structured logger singleton. */
export const parityLogger = {
  // -------------------------------------------------------------------------
  // Event list lifecycle
  // -------------------------------------------------------------------------

  listEventsStart(
    limit: number,
    status?: string,
    instrument?: string,
    correlationId?: string,
  ): void {
    emit("info", `Fetching parity events (limit=${limit})`, {
      operation: "parity.list_events",
      component: "parityApi",
      limit,
      status: status || "all",
      instrument: instrument || "all",
      correlation_id: correlationId,
    });
  },

  listEventsSuccess(
    count: number,
    totalCount: number,
    durationMs: number,
    correlationId?: string,
  ): void {
    emit("info", `Fetched ${count} parity event(s) of ${totalCount}`, {
      operation: "parity.list_events",
      component: "parityApi",
      duration_ms: durationMs,
      result: "success",
      event_count: count,
      total_count: totalCount,
      correlation_id: correlationId,
    });
  },

  listEventsFailure(error: unknown, durationMs: number, correlationId?: string): void {
    emit("error", "Failed to fetch parity events", {
      operation: "parity.list_events",
      component: "parityApi",
      duration_ms: durationMs,
      result: "failure",
      error: error instanceof Error ? error.message : String(error),
      correlation_id: correlationId,
    });
    if (error instanceof Error) {
      Sentry.captureException(error);
    }
  },

  // -------------------------------------------------------------------------
  // Event detail lifecycle
  // -------------------------------------------------------------------------

  getEventStart(eventId: string, correlationId?: string): void {
    emit("info", `Fetching parity event ${eventId}`, {
      operation: "parity.get_event",
      component: "parityApi",
      event_id: eventId,
      correlation_id: correlationId,
    });
  },

  getEventSuccess(eventId: string, durationMs: number, correlationId?: string): void {
    emit("info", `Fetched parity event ${eventId}`, {
      operation: "parity.get_event",
      component: "parityApi",
      event_id: eventId,
      duration_ms: durationMs,
      result: "success",
      correlation_id: correlationId,
    });
  },

  getEventFailure(
    eventId: string,
    error: unknown,
    durationMs: number,
    correlationId?: string,
  ): void {
    emit("error", `Failed to fetch parity event ${eventId}`, {
      operation: "parity.get_event",
      component: "parityApi",
      event_id: eventId,
      duration_ms: durationMs,
      result: "failure",
      error: error instanceof Error ? error.message : String(error),
      correlation_id: correlationId,
    });
    if (error instanceof Error) {
      Sentry.captureException(error);
    }
  },

  // -------------------------------------------------------------------------
  // Summary lifecycle
  // -------------------------------------------------------------------------

  getSummaryStart(correlationId?: string): void {
    emit("info", "Fetching parity summary", {
      operation: "parity.get_summary",
      component: "parityApi",
      correlation_id: correlationId,
    });
  },

  getSummarySuccess(
    instrumentCount: number,
    totalEventCount: number,
    durationMs: number,
    correlationId?: string,
  ): void {
    emit("info", `Fetched parity summary for ${instrumentCount} instrument(s)`, {
      operation: "parity.get_summary",
      component: "parityApi",
      duration_ms: durationMs,
      result: "success",
      instrument_count: instrumentCount,
      total_event_count: totalEventCount,
      correlation_id: correlationId,
    });
  },

  getSummaryFailure(error: unknown, durationMs: number, correlationId?: string): void {
    emit("error", "Failed to fetch parity summary", {
      operation: "parity.get_summary",
      component: "parityApi",
      duration_ms: durationMs,
      result: "failure",
      error: error instanceof Error ? error.message : String(error),
      correlation_id: correlationId,
    });
    if (error instanceof Error) {
      Sentry.captureException(error);
    }
  },

  // -------------------------------------------------------------------------
  // Validation
  // -------------------------------------------------------------------------

  validationFailure(context: string, issues: unknown[], correlationId?: string): void {
    emit("warn", `Validation failure: ${context}`, {
      operation: "parity.validation_failure",
      component: "parityApi",
      issue_count: issues.length,
      issues: Array.isArray(issues) ? issues : [issues],
      correlation_id: correlationId,
    });
  },

  // -------------------------------------------------------------------------
  // Page lifecycle
  // -------------------------------------------------------------------------

  pageMount(pageName: string, correlationId?: string): void {
    emit("debug", `${pageName} mounted`, {
      operation: "parity.page_mount",
      component: pageName,
      correlation_id: correlationId,
    });
  },

  pageUnmount(pageName: string, correlationId?: string): void {
    emit("debug", `${pageName} unmounted`, {
      operation: "parity.page_unmount",
      component: pageName,
      correlation_id: correlationId,
    });
  },

  // -------------------------------------------------------------------------
  // Retry observability (CLAUDE.md §9)
  // -------------------------------------------------------------------------

  retryAttempt(attempt: number, delayMs: number, error: unknown, correlationId?: string): void {
    emit("warn", `Retrying parity API call (attempt ${attempt}, delay ${delayMs}ms)`, {
      operation: "parity.retry_attempt",
      component: "parityApi",
      attempt,
      delay_ms: delayMs,
      result: "partial",
      error: error instanceof Error ? error.message : String(error),
      correlation_id: correlationId,
    });
  },
};
