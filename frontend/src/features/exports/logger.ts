/**
 * Exports feature structured logger — typed log events for observability.
 *
 * Purpose:
 *   Provide structured, typed logging for all exports operations
 *   (create, list, get, download). Follows CLAUDE.md §8 with operation,
 *   correlation_id, component, duration_ms, and result fields. Adds
 *   Sentry breadcrumbs for the operator action trail.
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
    category: "exports",
    message,
    level: level === "warn" ? "warning" : level,
    data: entry,
  });

  switch (level) {
    case "debug":
      // eslint-disable-next-line no-console
      console.debug(`[Exports] ${message}`, entry);
      break;
    case "info":
      // eslint-disable-next-line no-console
      console.info(`[Exports] ${message}`, entry);
      break;
    case "warn":
      // eslint-disable-next-line no-console
      console.warn(`[Exports] ${message}`, entry);
      break;
    case "error":
      // eslint-disable-next-line no-console
      console.error(`[Exports] ${message}`, entry);
      break;
  }
}

/** Exports structured logger singleton. */
export const exportsLogger = {
  // -------------------------------------------------------------------------
  // Create export lifecycle
  // -------------------------------------------------------------------------

  createExportStart(exportType: string, objectId: string, correlationId?: string): void {
    emit("info", `Creating export (type=${exportType}, object=${objectId})`, {
      operation: "exports.create_export",
      component: "exportsApi",
      export_type: exportType,
      object_id: objectId,
      correlation_id: correlationId,
    });
  },

  createExportSuccess(exportId: string, durationMs: number, correlationId?: string): void {
    emit("info", `Export job created ${exportId}`, {
      operation: "exports.create_export",
      component: "exportsApi",
      export_id: exportId,
      duration_ms: durationMs,
      result: "success",
      correlation_id: correlationId,
    });
  },

  createExportFailure(error: unknown, durationMs: number, correlationId?: string): void {
    emit("error", "Failed to create export job", {
      operation: "exports.create_export",
      component: "exportsApi",
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
  // List exports lifecycle
  // -------------------------------------------------------------------------

  listExportsStart(objectId?: string, exportType?: string, correlationId?: string): void {
    emit("info", "Fetching export list", {
      operation: "exports.list_exports",
      component: "exportsApi",
      object_id: objectId,
      export_type: exportType,
      correlation_id: correlationId,
    });
  },

  listExportsSuccess(
    count: number,
    totalCount: number,
    durationMs: number,
    correlationId?: string,
  ): void {
    emit("info", `Fetched ${count} export(s) of ${totalCount}`, {
      operation: "exports.list_exports",
      component: "exportsApi",
      duration_ms: durationMs,
      result: "success",
      export_count: count,
      total_count: totalCount,
      correlation_id: correlationId,
    });
  },

  listExportsFailure(error: unknown, durationMs: number, correlationId?: string): void {
    emit("error", "Failed to fetch export list", {
      operation: "exports.list_exports",
      component: "exportsApi",
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
  // Get export lifecycle
  // -------------------------------------------------------------------------

  getExportStart(exportId: string, correlationId?: string): void {
    emit("info", `Fetching export ${exportId}`, {
      operation: "exports.get_export",
      component: "exportsApi",
      export_id: exportId,
      correlation_id: correlationId,
    });
  },

  getExportSuccess(exportId: string, durationMs: number, correlationId?: string): void {
    emit("info", `Fetched export ${exportId}`, {
      operation: "exports.get_export",
      component: "exportsApi",
      export_id: exportId,
      duration_ms: durationMs,
      result: "success",
      correlation_id: correlationId,
    });
  },

  getExportFailure(
    exportId: string,
    error: unknown,
    durationMs: number,
    correlationId?: string,
  ): void {
    emit("error", `Failed to fetch export ${exportId}`, {
      operation: "exports.get_export",
      component: "exportsApi",
      export_id: exportId,
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

  downloadStart(exportId: string, correlationId?: string): void {
    emit("info", `Downloading export ${exportId}`, {
      operation: "exports.download_export",
      component: "exportsApi",
      export_id: exportId,
      correlation_id: correlationId,
    });
  },

  downloadSuccess(exportId: string, correlationId?: string): void {
    emit("info", `Downloaded export ${exportId}`, {
      operation: "exports.download_export",
      component: "exportsApi",
      export_id: exportId,
      result: "success",
      correlation_id: correlationId,
    });
  },

  downloadFailure(exportId: string, error: unknown, correlationId?: string): void {
    emit("error", `Failed to download export ${exportId}`, {
      operation: "exports.download_export",
      component: "exportsApi",
      export_id: exportId,
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
      operation: "exports.validation_failure",
      component: "exportsApi",
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
      operation: "exports.page_mount",
      component: pageName,
      correlation_id: correlationId,
    });
  },

  pageUnmount(pageName: string, correlationId?: string): void {
    emit("debug", `${pageName} unmounted`, {
      operation: "exports.page_unmount",
      component: pageName,
      correlation_id: correlationId,
    });
  },

  // -------------------------------------------------------------------------
  // Retry observability (CLAUDE.md §9)
  // -------------------------------------------------------------------------

  retryAttempt(attempt: number, delayMs: number, error: unknown, correlationId?: string): void {
    emit("warn", `Retrying exports API call (attempt ${attempt}, delay ${delayMs}ms)`, {
      operation: "exports.retry_attempt",
      component: "exportsApi",
      attempt,
      delay_ms: delayMs,
      result: "partial",
      error: error instanceof Error ? error.message : String(error),
      correlation_id: correlationId,
    });
  },
};
