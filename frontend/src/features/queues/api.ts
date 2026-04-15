/**
 * Queues feature API layer — data fetching for queue snapshots and contention.
 *
 * Purpose:
 *   Fetch queue snapshot list and queue contention responses from the
 *   shared backend HTTP client. Implements CLAUDE.md §9 retry on transient
 *   errors for idempotent reads, propagates X-Correlation-Id headers per §8,
 *   and supports AbortSignal cancellation for in-flight teardown.
 *
 * Responsibilities:
 *   - List queues (GET /queues/) with retry.
 *   - Get contention for a queue class (GET /queues/{queue_class}/contention) with retry.
 *   - Classify AxiosErrors into domain-specific queues errors.
 *   - Validate every response with Zod schemas (safeParse).
 *   - Wrap unknown non-Error throwables into QueuesNetworkError.
 *
 * Does NOT:
 *   - Contain business logic, UI rendering, or React state management.
 *   - Bypass the shared apiClient (auth, base URL, 401 handling).
 *
 * Dependencies:
 *   - apiClient from @/api/client.
 *   - Zod schemas from @/types/queues.
 *   - Error types from ./errors.
 *   - retryWithBackoff from ./retry.
 *   - queuesLogger from ./logger.
 *
 * Example:
 *   const ctrl = new AbortController();
 *   const list = await queuesApi.listQueues("corr-1", ctrl.signal);
 *   const contention = await queuesApi.getContention("task_queue", "corr-1", ctrl.signal);
 */

import { AxiosError, type AxiosRequestConfig } from "axios";
import { apiClient } from "@/api/client";
import { QueueListResponseSchema, QueueContentionSchema } from "@/types/queues";
import type { QueueListResponse, QueueContention } from "@/types/queues";
import {
  QueuesNotFoundError,
  QueuesAuthError,
  QueuesNetworkError,
  QueuesValidationError,
} from "./errors";
import { retryWithBackoff } from "./retry";
import { queuesLogger } from "./logger";

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
 * Classify an AxiosError into a domain-specific queues error.
 */
function classifyAxiosError(
  err: AxiosError,
  entityId: string,
): QueuesNotFoundError | QueuesAuthError | QueuesNetworkError {
  const status = err.response?.status;
  if (status === 404) return new QueuesNotFoundError(entityId, err);
  if (status === 401) return new QueuesAuthError(entityId, 401, err);
  if (status === 403) return new QueuesAuthError(entityId, 403, err);
  return new QueuesNetworkError(entityId, status, err);
}

/**
 * Normalize an unknown thrown value:
 * - DOMException("AbortError") → rethrown as-is.
 * - AxiosError → classified queues error.
 * - Already an Error → rethrown as-is.
 * - Anything else → wrapped in QueuesNetworkError.
 */
function normalizeError(err: unknown, entityId: string): Error {
  if (err instanceof DOMException && err.name === "AbortError") return err;
  if (err instanceof AxiosError) return classifyAxiosError(err, entityId);
  if (err instanceof Error) return err;
  return new QueuesNetworkError(entityId, undefined, err);
}

// ---------------------------------------------------------------------------
// API client
// ---------------------------------------------------------------------------

/**
 * Queues API client.
 *
 * All methods throw domain-specific errors from ./errors.ts.
 * Idempotent GET methods are wrapped in retryWithBackoff per §9.
 */
export const queuesApi = {
  /**
   * List all queues in the system.
   *
   * Args:
   *   correlationId: Optional correlation ID for distributed tracing.
   *   signal: Optional AbortSignal for request cancellation.
   *
   * Returns:
   *   QueueListResponse with queues array and generated_at timestamp.
   *
   * Raises:
   *   QueuesAuthError, QueuesNetworkError, QueuesValidationError.
   *
   * Example:
   *   const response = await queuesApi.listQueues("corr-123");
   *   console.log(response.queues.length);
   */
  async listQueues(correlationId?: string, signal?: AbortSignal): Promise<QueueListResponse> {
    const startTime = performance.now();
    queuesLogger.listQueuesStart(correlationId);
    const config = buildConfig(correlationId, signal);

    try {
      const data = await retryWithBackoff(
        async () => {
          try {
            const response = await apiClient.get("/queues/", config);
            const parseResult = QueueListResponseSchema.safeParse(response.data);
            if (!parseResult.success) {
              queuesLogger.validationFailure("queue list", parseResult.error.issues, correlationId);
              throw new QueuesValidationError("list", parseResult.error.issues, parseResult.error);
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
            queuesLogger.retryAttempt(attempt, delayMs, err, correlationId),
        },
      );
      const durationMs = Math.round(performance.now() - startTime);
      queuesLogger.listQueuesSuccess(data.queues.length, durationMs, correlationId);
      return data;
    } catch (err) {
      const durationMs = Math.round(performance.now() - startTime);
      const normalized = normalizeError(err, "list");
      queuesLogger.listQueuesFailure(normalized, durationMs, correlationId);
      throw normalized;
    }
  },

  /**
   * Get contention metrics for a specific queue class.
   *
   * Args:
   *   queueClass: The queue class identifier (e.g., "task_queue", "event_queue").
   *   correlationId: Optional correlation ID for distributed tracing.
   *   signal: Optional AbortSignal for request cancellation.
   *
   * Returns:
   *   QueueContention with depth, running, failed, and contention_score.
   *
   * Raises:
   *   QueuesNotFoundError, QueuesAuthError, QueuesNetworkError, QueuesValidationError.
   *
   * Example:
   *   const contention = await queuesApi.getContention("task_queue", "corr-123");
   *   console.log(contention.contention_score);
   */
  async getContention(
    queueClass: string,
    correlationId?: string,
    signal?: AbortSignal,
  ): Promise<QueueContention> {
    const startTime = performance.now();
    queuesLogger.getContentionStart(queueClass, correlationId);
    const config = buildConfig(correlationId, signal);

    try {
      const data = await retryWithBackoff(
        async () => {
          try {
            const response = await apiClient.get(`/queues/${queueClass}/contention`, config);
            const parseResult = QueueContentionSchema.safeParse(response.data);
            if (!parseResult.success) {
              queuesLogger.validationFailure(
                `contention for ${queueClass}`,
                parseResult.error.issues,
                correlationId,
              );
              throw new QueuesValidationError(
                queueClass,
                parseResult.error.issues,
                parseResult.error,
              );
            }
            return parseResult.data;
          } catch (err) {
            if (err instanceof AxiosError) throw classifyAxiosError(err, queueClass);
            throw err;
          }
        },
        {
          signal,
          onRetry: (attempt, delayMs, err) =>
            queuesLogger.retryAttempt(attempt, delayMs, err, correlationId),
        },
      );
      const durationMs = Math.round(performance.now() - startTime);
      queuesLogger.getContentionSuccess(
        queueClass,
        data.contention_score,
        durationMs,
        correlationId,
      );
      return data;
    } catch (err) {
      const durationMs = Math.round(performance.now() - startTime);
      const normalized = normalizeError(err, queueClass);
      queuesLogger.getContentionFailure(queueClass, normalized, durationMs, correlationId);
      throw normalized;
    }
  },
};
