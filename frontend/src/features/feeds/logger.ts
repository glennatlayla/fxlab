/**
 * Feeds feature structured logger — typed log events for observability.
 *
 * Purpose:
 *   Provide structured, typed logging for all feeds operations (registry,
 *   detail, health). Follows CLAUDE.md §8 with operation, correlation_id,
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
    category: "feeds",
    message,
    level: level === "warn" ? "warning" : level,
    data: entry,
  });

  switch (level) {
    case "debug":
      // eslint-disable-next-line no-console
      console.debug(`[Feeds] ${message}`, entry);
      break;
    case "info":
      // eslint-disable-next-line no-console
      console.info(`[Feeds] ${message}`, entry);
      break;
    case "warn":
      console.warn(`[Feeds] ${message}`, entry);
      break;
    case "error":
      console.error(`[Feeds] ${message}`, entry);
      break;
  }
}

/** Feeds structured logger singleton. */
export const feedsLogger = {
  // -------------------------------------------------------------------------
  // Feed list lifecycle
  // -------------------------------------------------------------------------

  listFeedsStart(limit: number, offset: number, correlationId?: string): void {
    emit("info", `Fetching feed list (limit=${limit}, offset=${offset})`, {
      operation: "feeds.list_feeds",
      component: "feedsApi",
      limit,
      offset,
      correlation_id: correlationId,
    });
  },

  listFeedsSuccess(
    count: number,
    totalCount: number,
    durationMs: number,
    correlationId?: string,
  ): void {
    emit("info", `Fetched ${count} feed(s) of ${totalCount}`, {
      operation: "feeds.list_feeds",
      component: "feedsApi",
      duration_ms: durationMs,
      result: "success",
      feed_count: count,
      total_count: totalCount,
      correlation_id: correlationId,
    });
  },

  listFeedsFailure(error: unknown, durationMs: number, correlationId?: string): void {
    emit("error", "Failed to fetch feed list", {
      operation: "feeds.list_feeds",
      component: "feedsApi",
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
  // Feed detail lifecycle
  // -------------------------------------------------------------------------

  getFeedStart(feedId: string, correlationId?: string): void {
    emit("info", `Fetching feed ${feedId}`, {
      operation: "feeds.get_feed",
      component: "feedsApi",
      feed_id: feedId,
      correlation_id: correlationId,
    });
  },

  getFeedSuccess(feedId: string, durationMs: number, correlationId?: string): void {
    emit("info", `Fetched feed ${feedId}`, {
      operation: "feeds.get_feed",
      component: "feedsApi",
      feed_id: feedId,
      duration_ms: durationMs,
      result: "success",
      correlation_id: correlationId,
    });
  },

  getFeedFailure(feedId: string, error: unknown, durationMs: number, correlationId?: string): void {
    emit("error", `Failed to fetch feed ${feedId}`, {
      operation: "feeds.get_feed",
      component: "feedsApi",
      feed_id: feedId,
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
  // Feed health lifecycle
  // -------------------------------------------------------------------------

  listFeedHealthStart(correlationId?: string): void {
    emit("info", "Fetching feed health report", {
      operation: "feeds.list_feed_health",
      component: "feedsApi",
      correlation_id: correlationId,
    });
  },

  listFeedHealthSuccess(count: number, durationMs: number, correlationId?: string): void {
    emit("info", `Fetched health report for ${count} feed(s)`, {
      operation: "feeds.list_feed_health",
      component: "feedsApi",
      duration_ms: durationMs,
      result: "success",
      feed_count: count,
      correlation_id: correlationId,
    });
  },

  listFeedHealthFailure(error: unknown, durationMs: number, correlationId?: string): void {
    emit("error", "Failed to fetch feed health report", {
      operation: "feeds.list_feed_health",
      component: "feedsApi",
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
      operation: "feeds.validation_failure",
      component: "feedsApi",
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
      operation: "feeds.page_mount",
      component: pageName,
      correlation_id: correlationId,
    });
  },

  pageUnmount(pageName: string, correlationId?: string): void {
    emit("debug", `${pageName} unmounted`, {
      operation: "feeds.page_unmount",
      component: pageName,
      correlation_id: correlationId,
    });
  },

  // -------------------------------------------------------------------------
  // Retry observability (CLAUDE.md §9)
  // -------------------------------------------------------------------------

  retryAttempt(attempt: number, delayMs: number, error: unknown, correlationId?: string): void {
    emit("warn", `Retrying feeds API call (attempt ${attempt}, delay ${delayMs}ms)`, {
      operation: "feeds.retry_attempt",
      component: "feedsApi",
      attempt,
      delay_ms: delayMs,
      result: "partial",
      error: error instanceof Error ? error.message : String(error),
      correlation_id: correlationId,
    });
  },
};
