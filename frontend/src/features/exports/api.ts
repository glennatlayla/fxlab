/**
 * Exports feature API layer — data fetching for export job lifecycle.
 *
 * Purpose:
 *   Fetch export jobs, create new exports, and download completed artifacts
 *   from the shared backend HTTP client. Implements CLAUDE.md §9 retry on
 *   transient errors for idempotent reads (GET), no retry on mutations (POST),
 *   propagates X-Correlation-Id headers per §8, and supports AbortSignal
 *   cancellation for in-flight teardown.
 *
 * Responsibilities:
 *   - Create export job (POST /exports) without retry.
 *   - List exports (GET /exports) with pagination + retry.
 *   - Get export detail (GET /exports/{id}) with retry.
 *   - Download export (GET /exports/{id}/download) without retry (binary).
 *   - Classify AxiosErrors into domain-specific exports errors.
 *   - Validate every response with Zod schemas (safeParse).
 *   - Wrap unknown non-Error throwables into ExportNetworkError.
 *
 * Does NOT:
 *   - Contain business logic, UI rendering, or React state management.
 *   - Bypass the shared apiClient (auth, base URL, 401 handling).
 *
 * Dependencies:
 *   - apiClient from @/api/client.
 *   - Zod schemas from @/types/exports.
 *   - Error types from ./errors.
 *   - retryWithBackoff from ./retry.
 *   - exportsLogger from ./logger.
 *
 * Example:
 *   const job = await exportsApi.createExport("trades", "run-id-123", "corr-1");
 *   const list = await exportsApi.listExports({ object_id: "run-id-123" }, "corr-1");
 */

import { AxiosError, type AxiosRequestConfig } from "axios";
import { apiClient } from "@/api/client";
import {
  ExportJobResponseSchema,
  ExportListResponseSchema,
  type ExportJobResponse,
  type ExportListResponse,
  type ExportType,
} from "@/types/exports";
import {
  ExportNotFoundError,
  ExportAuthError,
  ExportNetworkError,
  ExportValidationError,
} from "./errors";
import { retryWithBackoff } from "./retry";
import { exportsLogger } from "./logger";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

const CORRELATION_HEADER = "X-Correlation-Id";

/**
 * Build the per-request axios config carrying correlation header and signal.
 *
 * The header is omitted when no correlationId is supplied so the shared
 * apiClient interceptor injects a fallback UUID.
 */
function buildConfig(
  correlationId?: string,
  signal?: AbortSignal,
  extra?: Partial<AxiosRequestConfig>,
): AxiosRequestConfig {
  const headers: Record<string, string> = {};
  if (correlationId) {
    headers[CORRELATION_HEADER] = correlationId;
  }
  return { headers, signal, ...extra };
}

/**
 * Classify an AxiosError into a domain-specific exports error.
 */
function classifyAxiosError(
  err: AxiosError,
  entityId: string,
): ExportNotFoundError | ExportAuthError | ExportNetworkError {
  const status = err.response?.status;
  if (status === 404) return new ExportNotFoundError(entityId, err);
  if (status === 401) return new ExportAuthError(entityId, 401, err);
  if (status === 403) return new ExportAuthError(entityId, 403, err);
  return new ExportNetworkError(entityId, status, err);
}

/**
 * Normalize an unknown thrown value:
 * - DOMException("AbortError") → rethrown as-is.
 * - AxiosError → classified exports error.
 * - Already an Error → rethrown as-is.
 * - Anything else → wrapped in ExportNetworkError.
 */
function normalizeError(err: unknown, entityId: string): Error {
  if (err instanceof DOMException && err.name === "AbortError") return err;
  if (err instanceof AxiosError) return classifyAxiosError(err, entityId);
  if (err instanceof Error) return err;
  return new ExportNetworkError(entityId, undefined, err);
}

// ---------------------------------------------------------------------------
// API client
// ---------------------------------------------------------------------------

/** Pagination/filter parameters for the export list. */
export interface ListExportsParams {
  object_id?: string;
  export_type?: ExportType;
}

/**
 * Exports API client.
 *
 * All methods throw domain-specific errors from ./errors.ts.
 * Idempotent GET methods are wrapped in retryWithBackoff per §9.
 * POST methods (createExport) do NOT retry per §9 (non-idempotent).
 */
export const exportsApi = {
  /**
   * Create a new export job.
   *
   * Args:
   *   exportType: Type of export (trades, runs, artifacts).
   *   objectId: ID of the object to export (run ID, etc.).
   *   correlationId: Optional correlation ID for distributed tracing.
   *   signal: Optional AbortSignal for request cancellation.
   *
   * Returns:
   *   ExportJobResponse with job ID, status, and metadata.
   *
   * Raises:
   *   ExportAuthError, ExportNetworkError, ExportValidationError.
   *
   * Does NOT retry (non-idempotent mutation per CLAUDE.md §9).
   */
  async createExport(
    exportType: ExportType,
    objectId: string,
    correlationId?: string,
    signal?: AbortSignal,
  ): Promise<ExportJobResponse> {
    const startTime = performance.now();
    exportsLogger.createExportStart(exportType, objectId, correlationId);
    const config = buildConfig(correlationId, signal);

    try {
      const response = await apiClient.post(
        "/exports",
        { export_type: exportType, object_id: objectId },
        config,
      );
      const parseResult = ExportJobResponseSchema.safeParse(response.data);
      if (!parseResult.success) {
        exportsLogger.validationFailure("create export", parseResult.error.issues, correlationId);
        throw new ExportValidationError("create", parseResult.error.issues, parseResult.error);
      }
      const durationMs = Math.round(performance.now() - startTime);
      exportsLogger.createExportSuccess(parseResult.data.id, durationMs, correlationId);
      return parseResult.data;
    } catch (err) {
      const durationMs = Math.round(performance.now() - startTime);
      const normalized = normalizeError(err, "create");
      exportsLogger.createExportFailure(normalized, durationMs, correlationId);
      throw normalized;
    }
  },

  /**
   * List export jobs with optional filtering.
   *
   * Args:
   *   params: Filter parameters (object_id, export_type).
   *   correlationId: Optional correlation ID for distributed tracing.
   *   signal: Optional AbortSignal for request cancellation.
   *
   * Returns:
   *   ExportListResponse with exports array and total_count.
   *
   * Raises:
   *   ExportAuthError, ExportNetworkError, ExportValidationError.
   */
  async listExports(
    params?: ListExportsParams,
    correlationId?: string,
    signal?: AbortSignal,
  ): Promise<ExportListResponse> {
    const startTime = performance.now();
    exportsLogger.listExportsStart(params?.object_id, params?.export_type, correlationId);
    const queryParams: Record<string, string> = {};
    if (params?.object_id) queryParams.object_id = params.object_id;
    if (params?.export_type) queryParams.export_type = params.export_type;

    const config = buildConfig(correlationId, signal, { params: queryParams });

    try {
      const data = await retryWithBackoff(
        async () => {
          try {
            const response = await apiClient.get("/exports", config);
            const parseResult = ExportListResponseSchema.safeParse(response.data);
            if (!parseResult.success) {
              exportsLogger.validationFailure(
                "export list",
                parseResult.error.issues,
                correlationId,
              );
              throw new ExportValidationError("list", parseResult.error.issues, parseResult.error);
            }
            return parseResult.data;
          } catch (err) {
            if (err instanceof AxiosError) throw classifyAxiosError(err, "list");
            throw err;
          }
        },
        {
          signal,
          onRetry: (attempt, delayMs, err) =>
            exportsLogger.retryAttempt(attempt, delayMs, err, correlationId),
        },
      );
      const durationMs = Math.round(performance.now() - startTime);
      exportsLogger.listExportsSuccess(
        data.exports.length,
        data.total_count,
        durationMs,
        correlationId,
      );
      return data;
    } catch (err) {
      const durationMs = Math.round(performance.now() - startTime);
      const normalized = normalizeError(err, "list");
      exportsLogger.listExportsFailure(normalized, durationMs, correlationId);
      throw normalized;
    }
  },

  /**
   * Get export job detail by ID.
   *
   * Args:
   *   id: Export job ID.
   *   correlationId: Optional correlation ID for distributed tracing.
   *   signal: Optional AbortSignal for request cancellation.
   *
   * Returns:
   *   ExportJobResponse with full job details.
   *
   * Raises:
   *   ExportNotFoundError, ExportAuthError, ExportNetworkError, ExportValidationError.
   */
  async getExport(
    id: string,
    correlationId?: string,
    signal?: AbortSignal,
  ): Promise<ExportJobResponse> {
    const startTime = performance.now();
    exportsLogger.getExportStart(id, correlationId);
    const config = buildConfig(correlationId, signal);

    try {
      const data = await retryWithBackoff(
        async () => {
          try {
            const response = await apiClient.get(`/exports/${id}`, config);
            const parseResult = ExportJobResponseSchema.safeParse(response.data);
            if (!parseResult.success) {
              exportsLogger.validationFailure(
                `export detail ${id}`,
                parseResult.error.issues,
                correlationId,
              );
              throw new ExportValidationError(id, parseResult.error.issues, parseResult.error);
            }
            return parseResult.data;
          } catch (err) {
            if (err instanceof AxiosError) throw classifyAxiosError(err, id);
            throw err;
          }
        },
        {
          signal,
          onRetry: (attempt, delayMs, err) =>
            exportsLogger.retryAttempt(attempt, delayMs, err, correlationId),
        },
      );
      const durationMs = Math.round(performance.now() - startTime);
      exportsLogger.getExportSuccess(id, durationMs, correlationId);
      return data;
    } catch (err) {
      const durationMs = Math.round(performance.now() - startTime);
      const normalized = normalizeError(err, id);
      exportsLogger.getExportFailure(id, normalized, durationMs, correlationId);
      throw normalized;
    }
  },

  /**
   * Download export artifact via window.open.
   *
   * Args:
   *   id: Export job ID.
   *   correlationId: Optional correlation ID for distributed tracing.
   *
   * Returns:
   *   undefined (triggers browser download).
   *
   * Raises:
   *   ExportNotFoundError, ExportAuthError (if job not ready).
   *
   * Note:
   *   Opens a new window/tab with the download URL. Does NOT retry
   *   because downloads are browser-initiated and the URL is transient.
   */
  downloadExport(id: string, correlationId?: string): void {
    exportsLogger.downloadStart(id, correlationId);
    try {
      // Build download URL with correlation ID in query params
      const url = new URL(`/exports/${id}/download`, window.location.origin);
      if (correlationId) {
        url.searchParams.set("correlation_id", correlationId);
      }
      // Open in new tab; browser will initiate download if response is binary
      window.open(url.toString(), "_blank");
      exportsLogger.downloadSuccess(id, correlationId);
    } catch (err) {
      const normalized = normalizeError(err, id);
      exportsLogger.downloadFailure(id, normalized, correlationId);
      throw normalized;
    }
  },
};
