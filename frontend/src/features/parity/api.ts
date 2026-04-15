/**
 * Parity feature API layer — data fetching for parity events and summary.
 *
 * Purpose:
 *   Fetch parity event lists, individual events, and parity summaries from
 *   the shared backend HTTP client. Implements CLAUDE.md §9 retry on transient
 *   errors for idempotent reads, propagates X-Correlation-Id headers per §8,
 *   and supports AbortSignal cancellation for in-flight teardown.
 *
 * Responsibilities:
 *   - List parity events (GET /parity/events) with optional filters + retry.
 *   - Get single parity event (GET /parity/events/{id}) with retry.
 *   - Get parity summary (GET /parity/summary) with retry.
 *   - Classify AxiosErrors into domain-specific parity errors.
 *   - Validate every response with Zod schemas (safeParse).
 *   - Wrap unknown non-Error throwables into ParityNetworkError.
 *
 * Does NOT:
 *   - Contain business logic, UI rendering, or React state management.
 *   - Bypass the shared apiClient (auth, base URL, 401 handling).
 *
 * Dependencies:
 *   - apiClient from @/api/client.
 *   - Zod schemas from @/types/parity.
 *   - Error types from ./errors.
 *   - retryWithBackoff from ./retry.
 *   - parityLogger from ./logger.
 *
 * Example:
 *   const ctrl = new AbortController();
 *   const events = await parityApi.listEvents({ limit: 20 }, "corr-1", ctrl.signal);
 */

import { AxiosError, type AxiosRequestConfig } from "axios";
import { apiClient } from "@/api/client";
import {
  ParityEventListSchema,
  ParityEventSchema,
  ParitySummaryResponseSchema,
} from "@/types/parity";
import type { ParityEventList, ParityEvent, ParitySummaryResponse } from "@/types/parity";
import {
  ParityNotFoundError,
  ParityAuthError,
  ParityNetworkError,
  ParityValidationError,
} from "./errors";
import { retryWithBackoff } from "./retry";
import { parityLogger } from "./logger";

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
 * Classify an AxiosError into a domain-specific parity error.
 */
function classifyAxiosError(
  err: AxiosError,
  entityId: string,
): ParityNotFoundError | ParityAuthError | ParityNetworkError {
  const status = err.response?.status;
  if (status === 404) return new ParityNotFoundError(entityId, err);
  if (status === 401) return new ParityAuthError(entityId, 401, err);
  if (status === 403) return new ParityAuthError(entityId, 403, err);
  return new ParityNetworkError(entityId, status, err);
}

/**
 * Normalize an unknown thrown value:
 * - DOMException("AbortError") → rethrown as-is.
 * - AxiosError → classified parity error.
 * - Already an Error → rethrown as-is.
 * - Anything else → wrapped in ParityNetworkError.
 */
function normalizeError(err: unknown, entityId: string): Error {
  if (err instanceof DOMException && err.name === "AbortError") return err;
  if (err instanceof AxiosError) return classifyAxiosError(err, entityId);
  if (err instanceof Error) return err;
  return new ParityNetworkError(entityId, undefined, err);
}

// ---------------------------------------------------------------------------
// API client
// ---------------------------------------------------------------------------

/** Parameters for listing parity events. */
export interface ListEventsParams {
  /** Optional parity event status filter. */
  status?: string;
  /** Optional instrument filter (e.g., "EURUSD", "SPY"). */
  instrument?: string;
  /** Page size. Default: PARITY_DEFAULT_PAGE_SIZE. */
  limit?: number;
}

/**
 * Parity API client.
 *
 * All methods throw domain-specific errors from ./errors.ts.
 * Idempotent GET methods are wrapped in retryWithBackoff per §9.
 */
export const parityApi = {
  /**
   * List parity events with optional filtering.
   *
   * Args:
   *   params: {status?, instrument?, limit} filter and pagination params.
   *   correlationId: Optional correlation ID for distributed tracing.
   *   signal: Optional AbortSignal for request cancellation.
   *
   * Returns:
   *   ParityEventList with events array, total_count, and generated_at.
   *
   * Raises:
   *   ParityAuthError, ParityNetworkError, ParityValidationError.
   */
  async listEvents(
    params: ListEventsParams = {},
    correlationId?: string,
    signal?: AbortSignal,
  ): Promise<ParityEventList> {
    const startTime = performance.now();
    parityLogger.listEventsStart(
      params.limit ?? 20,
      params.status,
      params.instrument,
      correlationId,
    );

    const queryParams: Record<string, unknown> = { limit: params.limit ?? 20 };
    if (params.status) queryParams.status = params.status;
    if (params.instrument) queryParams.instrument = params.instrument;

    const config = buildConfig(correlationId, signal, { params: queryParams });

    try {
      const data = await retryWithBackoff(
        async () => {
          try {
            const response = await apiClient.get("/parity/events", config);
            const parseResult = ParityEventListSchema.safeParse(response.data);
            if (!parseResult.success) {
              parityLogger.validationFailure(
                "parity events",
                parseResult.error.issues,
                correlationId,
              );
              throw new ParityValidationError("list", parseResult.error.issues, parseResult.error);
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
            parityLogger.retryAttempt(attempt, delayMs, err, correlationId),
        },
      );
      const durationMs = Math.round(performance.now() - startTime);
      parityLogger.listEventsSuccess(
        data.events.length,
        data.total_count,
        durationMs,
        correlationId,
      );
      return data;
    } catch (err) {
      const durationMs = Math.round(performance.now() - startTime);
      const normalized = normalizeError(err, "list");
      parityLogger.listEventsFailure(normalized, durationMs, correlationId);
      throw normalized;
    }
  },

  /**
   * Get a single parity event by ID.
   *
   * Args:
   *   id: The parity event ID.
   *   correlationId: Optional correlation ID for distributed tracing.
   *   signal: Optional AbortSignal for request cancellation.
   *
   * Returns:
   *   ParityEvent with all fields including severity, delta, and timestamp.
   *
   * Raises:
   *   ParityNotFoundError, ParityAuthError, ParityNetworkError, ParityValidationError.
   */
  async getEvent(id: string, correlationId?: string, signal?: AbortSignal): Promise<ParityEvent> {
    const startTime = performance.now();
    parityLogger.getEventStart(id, correlationId);
    const config = buildConfig(correlationId, signal);

    try {
      const data = await retryWithBackoff(
        async () => {
          try {
            const response = await apiClient.get(`/parity/events/${id}`, config);
            const parseResult = ParityEventSchema.safeParse(response.data);
            if (!parseResult.success) {
              parityLogger.validationFailure(
                `parity event ${id}`,
                parseResult.error.issues,
                correlationId,
              );
              throw new ParityValidationError(id, parseResult.error.issues, parseResult.error);
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
            parityLogger.retryAttempt(attempt, delayMs, err, correlationId),
        },
      );
      const durationMs = Math.round(performance.now() - startTime);
      parityLogger.getEventSuccess(id, durationMs, correlationId);
      return data;
    } catch (err) {
      const durationMs = Math.round(performance.now() - startTime);
      const normalized = normalizeError(err, id);
      parityLogger.getEventFailure(id, normalized, durationMs, correlationId);
      throw normalized;
    }
  },

  /**
   * Get the overall parity summary across all instruments.
   *
   * Returns a breakdown of parity events by instrument, including event counts
   * by severity level and the worst severity detected per instrument.
   *
   * Args:
   *   correlationId: Optional correlation ID for distributed tracing.
   *   signal: Optional AbortSignal for request cancellation.
   *
   * Returns:
   *   ParitySummaryResponse with summaries array and total_event_count.
   *
   * Raises:
   *   ParityAuthError, ParityNetworkError, ParityValidationError.
   */
  async getSummary(correlationId?: string, signal?: AbortSignal): Promise<ParitySummaryResponse> {
    const startTime = performance.now();
    parityLogger.getSummaryStart(correlationId);
    const config = buildConfig(correlationId, signal);

    try {
      const data = await retryWithBackoff(
        async () => {
          try {
            const response = await apiClient.get("/parity/summary", config);
            const parseResult = ParitySummaryResponseSchema.safeParse(response.data);
            if (!parseResult.success) {
              parityLogger.validationFailure(
                "parity summary",
                parseResult.error.issues,
                correlationId,
              );
              throw new ParityValidationError(
                "summary",
                parseResult.error.issues,
                parseResult.error,
              );
            }
            return parseResult.data;
          } catch (err) {
            if (err instanceof AxiosError) throw classifyAxiosError(err, "summary");
            throw err;
          }
        },
        {
          signal,
          onRetry: (attempt, delayMs, err) =>
            parityLogger.retryAttempt(attempt, delayMs, err, correlationId),
        },
      );
      const durationMs = Math.round(performance.now() - startTime);
      parityLogger.getSummarySuccess(
        data.summaries.length,
        data.total_event_count,
        durationMs,
        correlationId,
      );
      return data;
    } catch (err) {
      const durationMs = Math.round(performance.now() - startTime);
      const normalized = normalizeError(err, "summary");
      parityLogger.getSummaryFailure(normalized, durationMs, correlationId);
      throw normalized;
    }
  },
};
