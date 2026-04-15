/**
 * Artifacts feature structured logger — typed log events for observability.
 *
 * Purpose:
 *   Provide structured, typed logging for all artifacts operations (listing, downloading).
 *   Follows CLAUDE.md §8 with operation, correlation_id, component, duration_ms,
 *   and result fields. Adds Sentry breadcrumbs for the operator action trail.
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
    category: "artifacts",
    message,
    level: level === "warn" ? "warning" : level,
    data: entry,
  });

  switch (level) {
    case "debug":
      // eslint-disable-next-line no-console
      console.debug(`[Artifacts] ${message}`, entry);
      break;
    case "info":
      // eslint-disable-next-line no-console
      console.info(`[Artifacts] ${message}`, entry);
      break;
    case "warn":
      // eslint-disable-next-line no-console
      console.warn(`[Artifacts] ${message}`, entry);
      break;
    case "error":
      // eslint-disable-next-line no-console
      console.error(`[Artifacts] ${message}`, entry);
      break;
  }
}

/** Artifacts structured logger singleton. */
export const artifactLogger = {
  // -------------------------------------------------------------------------
  // Artifact list lifecycle
  // -------------------------------------------------------------------------

  listArtifactsStart(
    limit: number,
    offset: number,
    artifactTypes: string[],
    subjectId?: string,
    correlationId?: string,
  ): void {
    emit("info", `Fetching artifact list (limit=${limit}, offset=${offset})`, {
      operation: "artifacts.list_artifacts",
      component: "artifactApi",
      limit,
      offset,
      artifact_types: artifactTypes,
      subject_id: subjectId,
      correlation_id: correlationId,
    });
  },

  listArtifactsSuccess(
    count: number,
    totalCount: number,
    durationMs: number,
    correlationId?: string,
  ): void {
    emit("info", `Fetched ${count} artifact(s) of ${totalCount}`, {
      operation: "artifacts.list_artifacts",
      component: "artifactApi",
      duration_ms: durationMs,
      result: "success",
      artifact_count: count,
      total_count: totalCount,
      correlation_id: correlationId,
    });
  },

  listArtifactsFailure(error: unknown, durationMs: number, correlationId?: string): void {
    emit("error", "Failed to fetch artifact list", {
      operation: "artifacts.list_artifacts",
      component: "artifactApi",
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
  // Download lifecycle
  // -------------------------------------------------------------------------

  downloadStart(artifactId: string, correlationId?: string): void {
    emit("info", `Downloading artifact ${artifactId}`, {
      operation: "artifacts.download_artifact",
      component: "artifactApi",
      artifact_id: artifactId,
      correlation_id: correlationId,
    });
  },

  downloadSuccess(artifactId: string, durationMs: number, correlationId?: string): void {
    emit("info", `Downloaded artifact ${artifactId}`, {
      operation: "artifacts.download_artifact",
      component: "artifactApi",
      artifact_id: artifactId,
      duration_ms: durationMs,
      result: "success",
      correlation_id: correlationId,
    });
  },

  downloadFailure(
    artifactId: string,
    error: unknown,
    durationMs: number,
    correlationId?: string,
  ): void {
    emit("error", `Failed to download artifact ${artifactId}`, {
      operation: "artifacts.download_artifact",
      component: "artifactApi",
      artifact_id: artifactId,
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
      operation: "artifacts.validation_failure",
      component: "artifactApi",
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
      operation: "artifacts.page_mount",
      component: pageName,
      correlation_id: correlationId,
    });
  },

  pageUnmount(pageName: string, correlationId?: string): void {
    emit("debug", `${pageName} unmounted`, {
      operation: "artifacts.page_unmount",
      component: pageName,
      correlation_id: correlationId,
    });
  },

  // -------------------------------------------------------------------------
  // Retry observability (CLAUDE.md §9)
  // -------------------------------------------------------------------------

  retryAttempt(attempt: number, delayMs: number, error: unknown, correlationId?: string): void {
    emit("warn", `Retrying artifacts API call (attempt ${attempt}, delay ${delayMs}ms)`, {
      operation: "artifacts.retry_attempt",
      component: "artifactApi",
      attempt,
      delay_ms: delayMs,
      result: "partial",
      error: error instanceof Error ? error.message : String(error),
      correlation_id: correlationId,
    });
  },
};
