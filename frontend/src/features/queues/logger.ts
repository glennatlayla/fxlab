/**
 * Queues feature structured logger — typed log events for observability.
 *
 * Purpose:
 *   Provide structured, typed logging for all queues operations (snapshots,
 *   contention analysis). Follows CLAUDE.md §8 with operation, correlation_id,
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
    category: "queues",
    message,
    level: level === "warn" ? "warning" : level,
    data: entry,
  });

  switch (level) {
    case "debug":
      // eslint-disable-next-line no-console
      console.debug(`[Queues] ${message}`, entry);
      break;
    case "info":
      // eslint-disable-next-line no-console
      console.info(`[Queues] ${message}`, entry);
      break;
    case "warn":
      console.warn(`[Queues] ${message}`, entry);
      break;
    case "error":
      console.error(`[Queues] ${message}`, entry);
      break;
  }
}

/** Queues structured logger singleton. */
export const queuesLogger = {
  // -------------------------------------------------------------------------
  // Queue list lifecycle
  // -------------------------------------------------------------------------

  listQueuesStart(correlationId?: string): void {
    emit("info", "Fetching queue list", {
      operation: "queues.list_queues",
      component: "queuesApi",
      correlation_id: correlationId,
    });
  },

  listQueuesSuccess(count: number, durationMs: number, correlationId?: string): void {
    emit("info", `Fetched ${count} queue(s)`, {
      operation: "queues.list_queues",
      component: "queuesApi",
      duration_ms: durationMs,
      result: "success",
      queue_count: count,
      correlation_id: correlationId,
    });
  },

  listQueuesFailure(error: unknown, durationMs: number, correlationId?: string): void {
    emit("error", "Failed to fetch queue list", {
      operation: "queues.list_queues",
      component: "queuesApi",
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
  // Queue contention lifecycle
  // -------------------------------------------------------------------------

  getContentionStart(queueClass: string, correlationId?: string): void {
    emit("info", `Fetching contention for queue class ${queueClass}`, {
      operation: "queues.get_contention",
      component: "queuesApi",
      queue_class: queueClass,
      correlation_id: correlationId,
    });
  },

  getContentionSuccess(
    queueClass: string,
    contentionScore: number,
    durationMs: number,
    correlationId?: string,
  ): void {
    emit("info", `Fetched contention for ${queueClass} (score ${contentionScore})`, {
      operation: "queues.get_contention",
      component: "queuesApi",
      queue_class: queueClass,
      contention_score: contentionScore,
      duration_ms: durationMs,
      result: "success",
      correlation_id: correlationId,
    });
  },

  getContentionFailure(
    queueClass: string,
    error: unknown,
    durationMs: number,
    correlationId?: string,
  ): void {
    emit("error", `Failed to fetch contention for ${queueClass}`, {
      operation: "queues.get_contention",
      component: "queuesApi",
      queue_class: queueClass,
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
      operation: "queues.validation_failure",
      component: "queuesApi",
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
      operation: "queues.page_mount",
      component: pageName,
      correlation_id: correlationId,
    });
  },

  pageUnmount(pageName: string, correlationId?: string): void {
    emit("debug", `${pageName} unmounted`, {
      operation: "queues.page_unmount",
      component: pageName,
      correlation_id: correlationId,
    });
  },

  // -------------------------------------------------------------------------
  // Retry observability (CLAUDE.md §9)
  // -------------------------------------------------------------------------

  retryAttempt(attempt: number, delayMs: number, error: unknown, correlationId?: string): void {
    emit("warn", `Retrying queues API call (attempt ${attempt}, delay ${delayMs}ms)`, {
      operation: "queues.retry_attempt",
      component: "queuesApi",
      attempt,
      delay_ms: delayMs,
      result: "partial",
      error: error instanceof Error ? error.message : String(error),
      correlation_id: correlationId,
    });
  },
};
