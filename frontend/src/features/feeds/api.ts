/**
 * Feeds feature API layer — data fetching for feed registry and health.
 *
 * Purpose:
 *   Fetch feed registry, feed detail, and feed health responses from the
 *   shared backend HTTP client. Implements CLAUDE.md §9 retry on transient
 *   errors for idempotent reads, propagates X-Correlation-Id headers per §8,
 *   and supports AbortSignal cancellation for in-flight teardown.
 *
 * Responsibilities:
 *   - List feeds (GET /feeds) with pagination + retry.
 *   - Get feed detail (GET /feeds/{feed_id}) with retry.
 *   - List feed health report (GET /feed-health) with retry.
 *   - Classify AxiosErrors into domain-specific feeds errors.
 *   - Validate every response with Zod schemas (safeParse).
 *   - Wrap unknown non-Error throwables into FeedsNetworkError.
 *
 * Does NOT:
 *   - Contain business logic, UI rendering, or React state management.
 *   - Bypass the shared apiClient (auth, base URL, 401 handling).
 *
 * Dependencies:
 *   - apiClient from @/api/client.
 *   - Zod schemas from @/types/feeds.
 *   - Error types from ./errors.
 *   - retryWithBackoff from ./retry.
 *   - feedsLogger from ./logger.
 *
 * Example:
 *   const ctrl = new AbortController();
 *   const page = await feedsApi.listFeeds({ limit: 25, offset: 0 }, "corr-1", ctrl.signal);
 */

import { AxiosError, type AxiosRequestConfig } from "axios";
import { apiClient } from "@/api/client";
import {
  FeedListResponseSchema,
  FeedDetailResponseSchema,
  FeedHealthListResponseSchema,
} from "@/types/feeds";
import type { FeedListResponse, FeedDetailResponse, FeedHealthListResponse } from "@/types/feeds";
import {
  FeedsNotFoundError,
  FeedsAuthError,
  FeedsNetworkError,
  FeedsValidationError,
} from "./errors";
import { retryWithBackoff } from "./retry";
import { feedsLogger } from "./logger";

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
 * Classify an AxiosError into a domain-specific feeds error.
 */
function classifyAxiosError(
  err: AxiosError,
  entityId: string,
): FeedsNotFoundError | FeedsAuthError | FeedsNetworkError {
  const status = err.response?.status;
  if (status === 404) return new FeedsNotFoundError(entityId, err);
  if (status === 401) return new FeedsAuthError(entityId, 401, err);
  if (status === 403) return new FeedsAuthError(entityId, 403, err);
  return new FeedsNetworkError(entityId, status, err);
}

/**
 * Normalize an unknown thrown value:
 * - DOMException("AbortError") → rethrown as-is.
 * - AxiosError → classified feeds error.
 * - Already an Error → rethrown as-is.
 * - Anything else → wrapped in FeedsNetworkError.
 */
function normalizeError(err: unknown, entityId: string): Error {
  if (err instanceof DOMException && err.name === "AbortError") return err;
  if (err instanceof AxiosError) return classifyAxiosError(err, entityId);
  if (err instanceof Error) return err;
  return new FeedsNetworkError(entityId, undefined, err);
}

// ---------------------------------------------------------------------------
// API client
// ---------------------------------------------------------------------------

/** Pagination parameters for the feed list. */
export interface ListFeedsParams {
  limit: number;
  offset: number;
}

/**
 * Feeds API client.
 *
 * All methods throw domain-specific errors from ./errors.ts.
 * Idempotent GET methods are wrapped in retryWithBackoff per §9.
 */
export const feedsApi = {
  /**
   * List feeds with pagination.
   *
   * Args:
   *   params: { limit, offset } pagination window.
   *   correlationId: Optional correlation ID for distributed tracing.
   *   signal: Optional AbortSignal for request cancellation.
   *
   * Returns:
   *   FeedListResponse with feeds page, total_count, limit, offset.
   *
   * Raises:
   *   FeedsAuthError, FeedsNetworkError, FeedsValidationError.
   */
  async listFeeds(
    params: ListFeedsParams,
    correlationId?: string,
    signal?: AbortSignal,
  ): Promise<FeedListResponse> {
    const startTime = performance.now();
    feedsLogger.listFeedsStart(params.limit, params.offset, correlationId);
    const config = buildConfig(correlationId, signal, {
      params: { limit: params.limit, offset: params.offset },
    });

    try {
      const data = await retryWithBackoff(
        async () => {
          try {
            const response = await apiClient.get("/feeds", config);
            const parseResult = FeedListResponseSchema.safeParse(response.data);
            if (!parseResult.success) {
              feedsLogger.validationFailure("feed list", parseResult.error.issues, correlationId);
              throw new FeedsValidationError("list", parseResult.error.issues, parseResult.error);
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
            feedsLogger.retryAttempt(attempt, delayMs, err, correlationId),
        },
      );
      const durationMs = Math.round(performance.now() - startTime);
      feedsLogger.listFeedsSuccess(data.feeds.length, data.total_count, durationMs, correlationId);
      return data;
    } catch (err) {
      const durationMs = Math.round(performance.now() - startTime);
      const normalized = normalizeError(err, "list");
      feedsLogger.listFeedsFailure(normalized, durationMs, correlationId);
      throw normalized;
    }
  },

  /**
   * Get feed detail by ID.
   */
  async getFeed(
    feedId: string,
    correlationId?: string,
    signal?: AbortSignal,
  ): Promise<FeedDetailResponse> {
    const startTime = performance.now();
    feedsLogger.getFeedStart(feedId, correlationId);
    const config = buildConfig(correlationId, signal);

    try {
      const data = await retryWithBackoff(
        async () => {
          try {
            const response = await apiClient.get(`/feeds/${feedId}`, config);
            const parseResult = FeedDetailResponseSchema.safeParse(response.data);
            if (!parseResult.success) {
              feedsLogger.validationFailure(
                `feed detail ${feedId}`,
                parseResult.error.issues,
                correlationId,
              );
              throw new FeedsValidationError(feedId, parseResult.error.issues, parseResult.error);
            }
            return parseResult.data;
          } catch (err) {
            if (err instanceof AxiosError) throw classifyAxiosError(err, feedId);
            throw err;
          }
        },
        {
          signal,
          onRetry: (attempt, delayMs, err) =>
            feedsLogger.retryAttempt(attempt, delayMs, err, correlationId),
        },
      );
      const durationMs = Math.round(performance.now() - startTime);
      feedsLogger.getFeedSuccess(feedId, durationMs, correlationId);
      return data;
    } catch (err) {
      const durationMs = Math.round(performance.now() - startTime);
      const normalized = normalizeError(err, feedId);
      feedsLogger.getFeedFailure(feedId, normalized, durationMs, correlationId);
      throw normalized;
    }
  },

  /**
   * List the current feed health report for every registered feed.
   *
   * The UI MUST consume this as the authoritative source of feed health —
   * it MUST NOT compute derived health state locally (M30 spec).
   */
  async listFeedHealth(
    correlationId?: string,
    signal?: AbortSignal,
  ): Promise<FeedHealthListResponse> {
    const startTime = performance.now();
    feedsLogger.listFeedHealthStart(correlationId);
    const config = buildConfig(correlationId, signal);

    try {
      const data = await retryWithBackoff(
        async () => {
          try {
            const response = await apiClient.get("/feed-health", config);
            const parseResult = FeedHealthListResponseSchema.safeParse(response.data);
            if (!parseResult.success) {
              feedsLogger.validationFailure("feed health", parseResult.error.issues, correlationId);
              throw new FeedsValidationError("health", parseResult.error.issues, parseResult.error);
            }
            return parseResult.data;
          } catch (err) {
            if (err instanceof AxiosError) throw classifyAxiosError(err, "health");
            throw err;
          }
        },
        {
          signal,
          onRetry: (attempt, delayMs, err) =>
            feedsLogger.retryAttempt(attempt, delayMs, err, correlationId),
        },
      );
      const durationMs = Math.round(performance.now() - startTime);
      feedsLogger.listFeedHealthSuccess(data.feeds.length, durationMs, correlationId);
      return data;
    } catch (err) {
      const durationMs = Math.round(performance.now() - startTime);
      const normalized = normalizeError(err, "health");
      feedsLogger.listFeedHealthFailure(normalized, durationMs, correlationId);
      throw normalized;
    }
  },
};
