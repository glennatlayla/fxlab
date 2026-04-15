/**
 * Audit feature structured logger — typed log events for observability.
 *
 * Purpose:
 *   Provide structured, typed logging for all audit operations (listing,
 *   detail fetch). Follows CLAUDE.md §8 with operation, correlation_id,
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
    category: "audit",
    message,
    level: level === "warn" ? "warning" : level,
    data: entry,
  });

  switch (level) {
    case "debug":
      // eslint-disable-next-line no-console
      console.debug(`[Audit] ${message}`, entry);
      break;
    case "info":
      // eslint-disable-next-line no-console
      console.info(`[Audit] ${message}`, entry);
      break;
    case "warn":
      // eslint-disable-next-line no-console
      console.warn(`[Audit] ${message}`, entry);
      break;
    case "error":
      // eslint-disable-next-line no-console
      console.error(`[Audit] ${message}`, entry);
      break;
  }
}

/** Audit structured logger singleton. */
export const auditLogger = {
  // -------------------------------------------------------------------------
  // Audit list lifecycle
  // -------------------------------------------------------------------------

  listAuditStart(
    limit: number,
    cursor?: string,
    actor?: string,
    action?: string,
    objectType?: string,
    correlationId?: string,
  ): void {
    emit("info", `Fetching audit events (limit=${limit})`, {
      operation: "audit.list_audit",
      component: "auditApi",
      limit,
      cursor,
      actor,
      action,
      object_type: objectType,
      correlation_id: correlationId,
    });
  },

  listAuditSuccess(
    count: number,
    totalCount: number,
    durationMs: number,
    correlationId?: string,
  ): void {
    emit("info", `Fetched ${count} audit event(s) of ${totalCount} total`, {
      operation: "audit.list_audit",
      component: "auditApi",
      duration_ms: durationMs,
      result: "success",
      event_count: count,
      total_count: totalCount,
      correlation_id: correlationId,
    });
  },

  listAuditFailure(error: unknown, durationMs: number, correlationId?: string): void {
    emit("error", "Failed to fetch audit events", {
      operation: "audit.list_audit",
      component: "auditApi",
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
  // Audit event detail lifecycle
  // -------------------------------------------------------------------------

  getAuditEventStart(eventId: string, correlationId?: string): void {
    emit("info", `Fetching audit event ${eventId}`, {
      operation: "audit.get_audit_event",
      component: "auditApi",
      event_id: eventId,
      correlation_id: correlationId,
    });
  },

  getAuditEventSuccess(eventId: string, durationMs: number, correlationId?: string): void {
    emit("info", `Fetched audit event ${eventId}`, {
      operation: "audit.get_audit_event",
      component: "auditApi",
      event_id: eventId,
      duration_ms: durationMs,
      result: "success",
      correlation_id: correlationId,
    });
  },

  getAuditEventFailure(
    eventId: string,
    error: unknown,
    durationMs: number,
    correlationId?: string,
  ): void {
    emit("error", `Failed to fetch audit event ${eventId}`, {
      operation: "audit.get_audit_event",
      component: "auditApi",
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
  // Validation
  // -------------------------------------------------------------------------

  validationFailure(context: string, issues: unknown[], correlationId?: string): void {
    emit("warn", `Validation failure: ${context}`, {
      operation: "audit.validation_failure",
      component: "auditApi",
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
      operation: "audit.page_mount",
      component: pageName,
      correlation_id: correlationId,
    });
  },

  pageUnmount(pageName: string, correlationId?: string): void {
    emit("debug", `${pageName} unmounted`, {
      operation: "audit.page_unmount",
      component: pageName,
      correlation_id: correlationId,
    });
  },

  // -------------------------------------------------------------------------
  // Retry observability (CLAUDE.md §9)
  // -------------------------------------------------------------------------

  retryAttempt(attempt: number, delayMs: number, error: unknown, correlationId?: string): void {
    emit("warn", `Retrying audit API call (attempt ${attempt}, delay ${delayMs}ms)`, {
      operation: "audit.retry_attempt",
      component: "auditApi",
      attempt,
      delay_ms: delayMs,
      result: "partial",
      error: error instanceof Error ? error.message : String(error),
      correlation_id: correlationId,
    });
  },
};
