/**
 * Artifacts feature API layer — data fetching for artifact browser and downloads.
 *
 * Purpose:
 *   Fetch artifact lists and trigger downloads from the shared backend HTTP client.
 *   Implements CLAUDE.md §9 retry on transient errors for idempotent reads,
 *   propagates X-Correlation-Id headers per §8, and supports AbortSignal
 *   cancellation for in-flight teardown.
 *
 * Responsibilities:
 *   - List artifacts (GET /artifacts) with filters and pagination + retry.
 *   - Download artifact (GET /artifacts/{artifact_id}/download) triggers browser download.
 *   - Classify AxiosErrors into domain-specific artifacts errors.
 *   - Validate every response with Zod schemas (safeParse).
 *   - Wrap unknown non-Error throwables into ArtifactNetworkError.
 *
 * Does NOT:
 *   - Contain business logic, UI rendering, or React state management.
 *   - Bypass the shared apiClient (auth, base URL, 401 handling).
 *
 * Dependencies:
 *   - apiClient from @/api/client.
 *   - Zod schemas from @/types/artifacts.
 *   - Error types from ./errors.
 *   - retryWithBackoff from ./retry.
 *   - artifactLogger from ./logger.
 *
 * Example:
 *   const ctrl = new AbortController();
 *   const page = await artifactApi.listArtifacts(
 *     { artifact_types: [], subject_id: "", limit: 25, offset: 0 },
 *     "corr-1",
 *     ctrl.signal
 *   );
 */

import { AxiosError, type AxiosRequestConfig } from "axios";
import { apiClient } from "@/api/client";
import { ArtifactQueryResponseSchema } from "@/types/artifacts";
import type { ArtifactQueryResponse } from "@/types/artifacts";
import {
  ArtifactNotFoundError,
  ArtifactAuthError,
  ArtifactNetworkError,
  ArtifactValidationError,
} from "./errors";
import { retryWithBackoff } from "./retry";
import { artifactLogger } from "./logger";

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
 * Classify an AxiosError into a domain-specific artifacts error.
 */
function classifyAxiosError(
  err: AxiosError,
  entityId: string,
): ArtifactNotFoundError | ArtifactAuthError | ArtifactNetworkError {
  const status = err.response?.status;
  if (status === 404) return new ArtifactNotFoundError(entityId, err);
  if (status === 401) return new ArtifactAuthError(entityId, 401, err);
  if (status === 403) return new ArtifactAuthError(entityId, 403, err);
  return new ArtifactNetworkError(entityId, status, err);
}

/**
 * Normalize an unknown thrown value:
 * - DOMException("AbortError") → rethrown as-is.
 * - AxiosError → classified artifacts error.
 * - Already an Error → rethrown as-is.
 * - Anything else → wrapped in ArtifactNetworkError.
 */
function normalizeError(err: unknown, entityId: string): Error {
  if (err instanceof DOMException && err.name === "AbortError") return err;
  if (err instanceof AxiosError) return classifyAxiosError(err, entityId);
  if (err instanceof Error) return err;
  return new ArtifactNetworkError(entityId, undefined, err);
}

// ---------------------------------------------------------------------------
// API client
// ---------------------------------------------------------------------------

/** Pagination and filter parameters for the artifact list. */
export interface ListArtifactsParams {
  artifact_types: string[];
  subject_id: string;
  limit: number;
  offset: number;
}

/**
 * Artifacts API client.
 *
 * All methods throw domain-specific errors from ./errors.ts.
 * Idempotent GET methods are wrapped in retryWithBackoff per §9.
 */
export const artifactApi = {
  /**
   * List artifacts with filtering and pagination.
   *
   * Args:
   *   params: { artifact_types, subject_id, limit, offset } filter/pagination window.
   *   correlationId: Optional correlation ID for distributed tracing.
   *   signal: Optional AbortSignal for request cancellation.
   *
   * Returns:
   *   ArtifactQueryResponse with artifacts page, total_count, limit, offset.
   *
   * Raises:
   *   ArtifactAuthError, ArtifactNetworkError, ArtifactValidationError.
   */
  async listArtifacts(
    params: ListArtifactsParams,
    correlationId?: string,
    signal?: AbortSignal,
  ): Promise<ArtifactQueryResponse> {
    const startTime = performance.now();
    artifactLogger.listArtifactsStart(
      params.limit,
      params.offset,
      params.artifact_types,
      params.subject_id,
      correlationId,
    );

    const queryParams: Record<string, unknown> = {
      limit: params.limit,
      offset: params.offset,
    };
    if (params.artifact_types.length > 0) {
      queryParams.artifact_types = params.artifact_types;
    }
    if (params.subject_id) {
      queryParams.subject_id = params.subject_id;
    }

    const config = buildConfig(correlationId, signal, { params: queryParams });

    try {
      const data = await retryWithBackoff(
        async () => {
          try {
            const response = await apiClient.get("/artifacts", config);
            const parseResult = ArtifactQueryResponseSchema.safeParse(response.data);
            if (!parseResult.success) {
              artifactLogger.validationFailure(
                "artifact list",
                parseResult.error.issues,
                correlationId,
              );
              throw new ArtifactValidationError(
                "list",
                parseResult.error.issues,
                parseResult.error,
              );
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
            artifactLogger.retryAttempt(attempt, delayMs, err, correlationId),
        },
      );
      const durationMs = Math.round(performance.now() - startTime);
      artifactLogger.listArtifactsSuccess(
        data.artifacts.length,
        data.total_count,
        durationMs,
        correlationId,
      );
      return data;
    } catch (err) {
      const durationMs = Math.round(performance.now() - startTime);
      const normalized = normalizeError(err, "list");
      artifactLogger.listArtifactsFailure(normalized, durationMs, correlationId);
      throw normalized;
    }
  },

  /**
   * Download an artifact by ID.
   *
   * Triggers a browser download of the artifact from the storage backend.
   *
   * Args:
   *   artifactId: The ID of the artifact to download.
   *   correlationId: Optional correlation ID for distributed tracing.
   *
   * Returns:
   *   void (side effect: browser download).
   *
   * Raises:
   *   ArtifactAuthError, ArtifactNetworkError.
   */
  async downloadArtifact(artifactId: string, correlationId?: string): Promise<void> {
    const startTime = performance.now();
    artifactLogger.downloadStart(artifactId, correlationId);

    const config = buildConfig(correlationId, undefined, {
      responseType: "blob",
    });

    try {
      const response = await apiClient.get(`/artifacts/${artifactId}/download`, config);
      const blob = response.data as Blob;
      const url = window.URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = `artifact-${artifactId}`;
      document.body.appendChild(link);
      link.click();
      document.body.removeChild(link);
      window.URL.revokeObjectURL(url);

      const durationMs = Math.round(performance.now() - startTime);
      artifactLogger.downloadSuccess(artifactId, durationMs, correlationId);
    } catch (err) {
      const durationMs = Math.round(performance.now() - startTime);
      const normalized = normalizeError(err, artifactId);
      artifactLogger.downloadFailure(artifactId, normalized, durationMs, correlationId);
      throw normalized;
    }
  },
};
