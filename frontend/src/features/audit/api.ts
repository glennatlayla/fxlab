/**
 * Audit feature API layer — data fetching for audit event explorer.
 *
 * Purpose:
 *   Fetch audit event lists and individual event records from the shared
 *   backend HTTP client. Implements CLAUDE.md §9 retry on transient errors
 *   for idempotent reads, propagates X-Correlation-Id headers per §8, and
 *   supports AbortSignal cancellation for in-flight teardown.
 *
 * Responsibilities:
 *   - List audit events (GET /audit) with filtering, pagination, and retry.
 *   - Get audit event detail (GET /audit/{id}) with retry.
 *   - Classify AxiosErrors into domain-specific audit errors.
 *   - Validate every response with Zod schemas (safeParse).
 *   - Wrap unknown non-Error throwables into AuditNetworkError.
 *
 * Does NOT:
 *   - Contain business logic, UI rendering, or React state management.
 *   - Bypass the shared apiClient (auth, base URL, 401 handling).
 *
 * Dependencies:
 *   - apiClient from @/api/client.
 *   - Zod schemas from @/types/audit.
 *   - Error types from ./errors.
 *   - retryWithBackoff from ./retry.
 *   - auditLogger from ./logger.
 *
 * Example:
 *   const ctrl = new AbortController();
 *   const page = await auditApi.listAudit(
 *     { limit: 20, actor: "operator@example.com" },
 *     "corr-1",
 *     ctrl.signal
 *   );
 */

import { AxiosError, type AxiosRequestConfig } from "axios";
import { apiClient } from "@/api/client";
import {
  AuditEventRecordSchema,
  AuditExplorerResponseSchema,
  type AuditEventRecord,
  type AuditExplorerResponse,
} from "@/types/audit";
import {
  AuditNotFoundError,
  AuditAuthError,
  AuditNetworkError,
  AuditValidationError,
} from "./errors";
import { retryWithBackoff } from "./retry";
import { auditLogger } from "./logger";

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
 * Classify an AxiosError into a domain-specific audit error.
 */
function classifyAxiosError(
  err: AxiosError,
  entityId: string,
): AuditNotFoundError | AuditAuthError | AuditNetworkError {
  const status = err.response?.status;
  if (status === 404) return new AuditNotFoundError(entityId, err);
  if (status === 401) return new AuditAuthError(entityId, 401, err);
  if (status === 403) return new AuditAuthError(entityId, 403, err);
  return new AuditNetworkError(entityId, status, err);
}

/**
 * Normalize an unknown thrown value:
 * - DOMException("AbortError") → rethrown as-is.
 * - AxiosError → classified audit error.
 * - Already an Error → rethrown as-is.
 * - Anything else → wrapped in AuditNetworkError.
 */
function normalizeError(err: unknown, entityId: string): Error {
  if (err instanceof DOMException && err.name === "AbortError") return err;
  if (err instanceof AxiosError) return classifyAxiosError(err, entityId);
  if (err instanceof Error) return err;
  return new AuditNetworkError(entityId, undefined, err);
}

// ---------------------------------------------------------------------------
// API client
// ---------------------------------------------------------------------------

/** Filtering and pagination parameters for the audit event list. */
export interface ListAuditParams {
  /** Optional actor name/email filter. */
  actor?: string;
  /** Optional action type filter. */
  action?: string;
  /** Optional resource type filter. */
  object_type?: string;
  /** Page size (default: AUDIT_DEFAULT_PAGE_SIZE). */
  limit: number;
  /** Cursor for pagination; empty or omitted for first page. */
  cursor?: string;
}

/**
 * Audit API client.
 *
 * All methods throw domain-specific errors from ./errors.ts.
 * Idempotent GET methods are wrapped in retryWithBackoff per §9.
 */
export const auditApi = {
  /**
   * List audit events with optional filtering and pagination.
   *
   * Args:
   *   params: Filtering and pagination parameters.
   *     - actor: Optional actor name/email to filter by.
   *     - action: Optional action type to filter by.
   *     - object_type: Optional resource type to filter by.
   *     - limit: Page size.
   *     - cursor: Optional pagination cursor for subsequent pages.
   *   correlationId: Optional correlation ID for distributed tracing.
   *   signal: Optional AbortSignal for request cancellation.
   *
   * Returns:
   *   AuditExplorerResponse with events page, total_count, next_cursor, generated_at.
   *
   * Raises:
   *   AuditAuthError, AuditNetworkError, AuditValidationError.
   */
  async listAudit(
    params: ListAuditParams,
    correlationId?: string,
    signal?: AbortSignal,
  ): Promise<AuditExplorerResponse> {
    const startTime = performance.now();
    auditLogger.listAuditStart(
      params.limit,
      params.cursor,
      params.actor,
      params.action,
      params.object_type,
      correlationId,
    );

    const queryParams: Record<string, unknown> = {
      limit: params.limit,
    };
    if (params.actor) queryParams.actor = params.actor;
    if (params.action) queryParams.action = params.action;
    if (params.object_type) queryParams.object_type = params.object_type;
    if (params.cursor) queryParams.cursor = params.cursor;

    const config = buildConfig(correlationId, signal, { params: queryParams });

    try {
      const data = await retryWithBackoff(
        async () => {
          try {
            const response = await apiClient.get("/audit", config);
            const parseResult = AuditExplorerResponseSchema.safeParse(response.data);
            if (!parseResult.success) {
              auditLogger.validationFailure("audit list", parseResult.error.issues, correlationId);
              throw new AuditValidationError("list", parseResult.error.issues, parseResult.error);
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
            auditLogger.retryAttempt(attempt, delayMs, err, correlationId),
        },
      );
      const durationMs = Math.round(performance.now() - startTime);
      auditLogger.listAuditSuccess(data.events.length, data.total_count, durationMs, correlationId);
      return data;
    } catch (err) {
      const durationMs = Math.round(performance.now() - startTime);
      const normalized = normalizeError(err, "list");
      auditLogger.listAuditFailure(normalized, durationMs, correlationId);
      throw normalized;
    }
  },

  /**
   * Get a specific audit event by ID.
   *
   * Args:
   *   id: The audit event ID to fetch.
   *   correlationId: Optional correlation ID for distributed tracing.
   *   signal: Optional AbortSignal for request cancellation.
   *
   * Returns:
   *   AuditEventRecord with event details.
   *
   * Raises:
   *   AuditNotFoundError (if event does not exist),
   *   AuditAuthError, AuditNetworkError, AuditValidationError.
   */
  async getAuditEvent(
    id: string,
    correlationId?: string,
    signal?: AbortSignal,
  ): Promise<AuditEventRecord> {
    const startTime = performance.now();
    auditLogger.getAuditEventStart(id, correlationId);
    const config = buildConfig(correlationId, signal);

    try {
      const data = await retryWithBackoff(
        async () => {
          try {
            const response = await apiClient.get(`/audit/${id}`, config);
            const parseResult = AuditEventRecordSchema.safeParse(response.data);
            if (!parseResult.success) {
              auditLogger.validationFailure(
                `audit event ${id}`,
                parseResult.error.issues,
                correlationId,
              );
              throw new AuditValidationError(id, parseResult.error.issues, parseResult.error);
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
            auditLogger.retryAttempt(attempt, delayMs, err, correlationId),
        },
      );
      const durationMs = Math.round(performance.now() - startTime);
      auditLogger.getAuditEventSuccess(id, durationMs, correlationId);
      return data;
    } catch (err) {
      const durationMs = Math.round(performance.now() - startTime);
      const normalized = normalizeError(err, id);
      auditLogger.getAuditEventFailure(id, normalized, durationMs, correlationId);
      throw normalized;
    }
  },
};
