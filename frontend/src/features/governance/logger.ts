/**
 * Governance feature structured logger — typed log events for observability.
 *
 * Purpose:
 *   Provide structured, typed logging for all governance operations
 *   (approvals, overrides, promotions). Follows CLAUDE.md §8 structured
 *   logging standards with operation name, correlation ID, component,
 *   duration, and result fields.
 *
 * Responsibilities:
 *   - Log approval list, approve, reject lifecycle.
 *   - Log override list, get, request lifecycle.
 *   - Log promotion list lifecycle.
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
    category: "governance",
    message,
    level: level === "warn" ? "warning" : level,
    data: entry,
  });

  switch (level) {
    case "debug":
      // eslint-disable-next-line no-console
      console.debug(`[Governance] ${message}`, entry);
      break;
    case "info":
      // eslint-disable-next-line no-console
      console.info(`[Governance] ${message}`, entry);
      break;
    case "warn":
      // eslint-disable-next-line no-console
      console.warn(`[Governance] ${message}`, entry);
      break;
    case "error":
      // eslint-disable-next-line no-console
      console.error(`[Governance] ${message}`, entry);
      break;
  }
}

/**
 * Governance structured logger singleton.
 *
 * All methods accept an optional correlationId for distributed trace linking.
 */
export const governanceLogger = {
  // -------------------------------------------------------------------------
  // Approval lifecycle
  // -------------------------------------------------------------------------

  listApprovalsStart(correlationId?: string): void {
    emit("info", "Fetching approval list", {
      operation: "governance.list_approvals",
      component: "governanceApi",
      correlation_id: correlationId,
    });
  },

  listApprovalsSuccess(count: number, durationMs: number, correlationId?: string): void {
    emit("info", `Fetched ${count} approval(s)`, {
      operation: "governance.list_approvals",
      component: "governanceApi",
      duration_ms: durationMs,
      result: "success",
      approval_count: count,
      correlation_id: correlationId,
    });
  },

  listApprovalsFailure(error: unknown, durationMs: number, correlationId?: string): void {
    emit("error", "Failed to fetch approval list", {
      operation: "governance.list_approvals",
      component: "governanceApi",
      duration_ms: durationMs,
      result: "failure",
      error: error instanceof Error ? error.message : String(error),
      correlation_id: correlationId,
    });
    if (error instanceof Error) {
      Sentry.captureException(error);
    }
  },

  approveStart(approvalId: string, correlationId?: string): void {
    emit("info", `Approving request ${approvalId}`, {
      operation: "governance.approve_request",
      component: "governanceApi",
      approval_id: approvalId,
      correlation_id: correlationId,
    });
  },

  approveSuccess(approvalId: string, durationMs: number, correlationId?: string): void {
    emit("info", `Approved request ${approvalId}`, {
      operation: "governance.approve_request",
      component: "governanceApi",
      approval_id: approvalId,
      duration_ms: durationMs,
      result: "success",
      correlation_id: correlationId,
    });
  },

  approveFailure(
    approvalId: string,
    error: unknown,
    durationMs: number,
    correlationId?: string,
  ): void {
    emit("error", `Failed to approve request ${approvalId}`, {
      operation: "governance.approve_request",
      component: "governanceApi",
      approval_id: approvalId,
      duration_ms: durationMs,
      result: "failure",
      error: error instanceof Error ? error.message : String(error),
      correlation_id: correlationId,
    });
    if (error instanceof Error) {
      Sentry.captureException(error);
    }
  },

  rejectStart(approvalId: string, correlationId?: string): void {
    emit("info", `Rejecting request ${approvalId}`, {
      operation: "governance.reject_request",
      component: "governanceApi",
      approval_id: approvalId,
      correlation_id: correlationId,
    });
  },

  rejectSuccess(approvalId: string, durationMs: number, correlationId?: string): void {
    emit("info", `Rejected request ${approvalId}`, {
      operation: "governance.reject_request",
      component: "governanceApi",
      approval_id: approvalId,
      duration_ms: durationMs,
      result: "success",
      correlation_id: correlationId,
    });
  },

  rejectFailure(
    approvalId: string,
    error: unknown,
    durationMs: number,
    correlationId?: string,
  ): void {
    emit("error", `Failed to reject request ${approvalId}`, {
      operation: "governance.reject_request",
      component: "governanceApi",
      approval_id: approvalId,
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
  // Override lifecycle
  // -------------------------------------------------------------------------

  listOverridesStart(correlationId?: string): void {
    emit("info", "Fetching override list", {
      operation: "governance.list_overrides",
      component: "governanceApi",
      correlation_id: correlationId,
    });
  },

  listOverridesSuccess(count: number, durationMs: number, correlationId?: string): void {
    emit("info", `Fetched ${count} override(s)`, {
      operation: "governance.list_overrides",
      component: "governanceApi",
      duration_ms: durationMs,
      result: "success",
      override_count: count,
      correlation_id: correlationId,
    });
  },

  listOverridesFailure(error: unknown, durationMs: number, correlationId?: string): void {
    emit("error", "Failed to fetch override list", {
      operation: "governance.list_overrides",
      component: "governanceApi",
      duration_ms: durationMs,
      result: "failure",
      error: error instanceof Error ? error.message : String(error),
      correlation_id: correlationId,
    });
    if (error instanceof Error) {
      Sentry.captureException(error);
    }
  },

  getOverrideStart(overrideId: string, correlationId?: string): void {
    emit("info", `Fetching override ${overrideId}`, {
      operation: "governance.get_override",
      component: "governanceApi",
      override_id: overrideId,
      correlation_id: correlationId,
    });
  },

  getOverrideSuccess(overrideId: string, durationMs: number, correlationId?: string): void {
    emit("info", `Fetched override ${overrideId}`, {
      operation: "governance.get_override",
      component: "governanceApi",
      override_id: overrideId,
      duration_ms: durationMs,
      result: "success",
      correlation_id: correlationId,
    });
  },

  getOverrideFailure(
    overrideId: string,
    error: unknown,
    durationMs: number,
    correlationId?: string,
  ): void {
    emit("error", `Failed to fetch override ${overrideId}`, {
      operation: "governance.get_override",
      component: "governanceApi",
      override_id: overrideId,
      duration_ms: durationMs,
      result: "failure",
      error: error instanceof Error ? error.message : String(error),
      correlation_id: correlationId,
    });
    if (error instanceof Error) {
      Sentry.captureException(error);
    }
  },

  requestOverrideStart(correlationId?: string): void {
    emit("info", "Submitting override request", {
      operation: "governance.request_override",
      component: "governanceApi",
      correlation_id: correlationId,
    });
  },

  requestOverrideSuccess(overrideId: string, durationMs: number, correlationId?: string): void {
    emit("info", `Override request created: ${overrideId}`, {
      operation: "governance.request_override",
      component: "governanceApi",
      override_id: overrideId,
      duration_ms: durationMs,
      result: "success",
      correlation_id: correlationId,
    });
  },

  requestOverrideFailure(error: unknown, durationMs: number, correlationId?: string): void {
    emit("error", "Failed to submit override request", {
      operation: "governance.request_override",
      component: "governanceApi",
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
  // Promotion lifecycle
  // -------------------------------------------------------------------------

  listPromotionsStart(candidateId: string, correlationId?: string): void {
    emit("info", `Fetching promotion history for candidate ${candidateId}`, {
      operation: "governance.list_promotions",
      component: "governanceApi",
      candidate_id: candidateId,
      correlation_id: correlationId,
    });
  },

  listPromotionsSuccess(
    candidateId: string,
    count: number,
    durationMs: number,
    correlationId?: string,
  ): void {
    emit("info", `Fetched ${count} promotion(s) for candidate ${candidateId}`, {
      operation: "governance.list_promotions",
      component: "governanceApi",
      candidate_id: candidateId,
      duration_ms: durationMs,
      result: "success",
      promotion_count: count,
      correlation_id: correlationId,
    });
  },

  listPromotionsFailure(
    candidateId: string,
    error: unknown,
    durationMs: number,
    correlationId?: string,
  ): void {
    emit("error", `Failed to fetch promotion history for candidate ${candidateId}`, {
      operation: "governance.list_promotions",
      component: "governanceApi",
      candidate_id: candidateId,
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
      operation: "governance.validation_failure",
      component: "governanceApi",
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
      operation: "governance.page_mount",
      component: pageName,
      correlation_id: correlationId,
    });
  },

  pageUnmount(pageName: string, correlationId?: string): void {
    emit("debug", `${pageName} unmounted`, {
      operation: "governance.page_unmount",
      component: pageName,
      correlation_id: correlationId,
    });
  },

  // -------------------------------------------------------------------------
  // Retry observability (CLAUDE.md §9)
  // -------------------------------------------------------------------------

  /**
   * Log a retry attempt for an idempotent governance API call.
   *
   * Args:
   *   attempt: 1-indexed retry attempt number.
   *   delayMs: Delay applied before this attempt.
   *   error: The transient error that triggered the retry.
   *   correlationId: Optional correlation ID for trace linking.
   */
  retryAttempt(attempt: number, delayMs: number, error: unknown, correlationId?: string): void {
    emit("warn", `Retrying governance API call (attempt ${attempt}, delay ${delayMs}ms)`, {
      operation: "governance.retry_attempt",
      component: "governanceApi",
      attempt,
      delay_ms: delayMs,
      result: "partial",
      error: error instanceof Error ? error.message : String(error),
      correlation_id: correlationId,
    });
  },
};
