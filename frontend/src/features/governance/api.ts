/**
 * Governance feature API layer — data fetching for approvals, overrides, and promotions.
 *
 * Purpose:
 *   Fetch and mutate governance entities (approvals, overrides, promotions)
 *   via the shared backend HTTP client. Implements retry logic for transient
 *   failures on idempotent reads per CLAUDE.md §9, propagates X-Correlation-Id
 *   headers per CLAUDE.md §8, and supports AbortSignal cancellation for
 *   in-flight request teardown on component unmount.
 *
 * Responsibilities:
 *   - List approvals (GET /api/approvals) with retry.
 *   - Approve / reject approvals (POST /api/approvals/{id}/approve|reject).
 *     Mutations do NOT retry (non-idempotent).
 *   - List overrides (GET /api/overrides) with retry.
 *   - Get override detail (GET /api/overrides/{id}) with retry.
 *   - Submit override request (POST /api/overrides/request) — no retry.
 *   - List promotions (GET /api/promotions) with retry.
 *   - Classify AxiosErrors into domain-specific governance errors.
 *   - Validate every response with Zod schemas (safeParse).
 *   - Wrap unknown non-Error throwables into GovernanceNetworkError.
 *
 * Does NOT:
 *   - Contain business logic, UI rendering, or React state management.
 *   - Bypass the shared apiClient (which provides auth token injection,
 *     base URL, and 401 redirect handling).
 *   - Retry mutations.
 *
 * Dependencies:
 *   - apiClient from @/api/client (shared axios instance with interceptors).
 *   - Zod schemas from @/types/governance.
 *   - Error types and classifier from ./errors.
 *   - retryWithBackoff from ./retry.
 *   - governanceLogger from ./logger.
 *
 * Example:
 *   const controller = new AbortController();
 *   const approvals = await governanceApi.listApprovals("corr-1", controller.signal);
 */

import { AxiosError, type AxiosRequestConfig } from "axios";
import { apiClient } from "@/api/client";
import {
  ApprovalDetailSchema,
  ApprovalListSchema,
  ApprovalDecisionResponseSchema,
  OverrideListSchema,
  OverrideDetailSchema,
  OverrideCreateResponseSchema,
  PromotionHistoryListSchema,
} from "@/types/governance";
import type {
  ApprovalDetail,
  OverrideDetail,
  OverrideCreateResponse,
  ApprovalDecisionResponse,
  OverrideRequestForm,
  PromotionHistoryEntry,
} from "@/types/governance";
import {
  GovernanceNotFoundError,
  GovernanceAuthError,
  GovernanceNetworkError,
  GovernanceValidationError,
  GovernanceSoDError,
} from "./errors";
import { retryWithBackoff } from "./retry";
import { governanceLogger } from "./logger";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/** Canonical correlation header name (matches backend tracing convention). */
const CORRELATION_HEADER = "X-Correlation-Id";

/**
 * Build the per-request axios config carrying correlation header and signal.
 *
 * The header is omitted entirely when no correlationId is supplied so the
 * shared apiClient interceptor can inject a fallback UUID.
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
 * Classify an AxiosError into a domain-specific governance error.
 *
 * Args:
 *   err: The AxiosError to classify.
 *   entityId: Entity ID for error context.
 *
 * Returns:
 *   A typed governance error subclass.
 */
function classifyAxiosError(
  err: AxiosError,
  entityId: string,
): GovernanceNotFoundError | GovernanceAuthError | GovernanceNetworkError | GovernanceSoDError {
  const status = err.response?.status;
  if (status === 404) return new GovernanceNotFoundError(entityId, err);
  if (status === 401) return new GovernanceAuthError(entityId, 401, err);
  if (status === 403) return new GovernanceAuthError(entityId, 403, err);
  if (status === 409) return new GovernanceSoDError(entityId, err);
  return new GovernanceNetworkError(entityId, status, err);
}

/**
 * Normalize an unknown thrown value into something safe to rethrow.
 *
 * - AxiosError → classified governance error.
 * - DOMException("AbortError") → rethrown as-is (cancellation signal).
 * - Already a GovernanceError → rethrown as-is.
 * - Anything else (string, object, null) → wrapped in GovernanceNetworkError
 *   so callers always receive a typed Error subclass.
 */
function normalizeError(err: unknown, entityId: string): Error {
  if (err instanceof DOMException && err.name === "AbortError") return err;
  if (err instanceof AxiosError) return classifyAxiosError(err, entityId);
  if (err instanceof Error) return err;
  return new GovernanceNetworkError(entityId, undefined, err);
}

// ---------------------------------------------------------------------------
// API client
// ---------------------------------------------------------------------------

/**
 * Governance API client.
 *
 * All methods throw domain-specific errors from ./errors.ts.
 * Idempotent GET methods are wrapped in retryWithBackoff per §9.
 * Mutations (approve, reject, requestOverride) are NOT retried.
 */
export const governanceApi = {
  // -------------------------------------------------------------------------
  // Approvals
  // -------------------------------------------------------------------------

  async listApprovals(correlationId?: string, signal?: AbortSignal): Promise<ApprovalDetail[]> {
    const startTime = performance.now();
    governanceLogger.listApprovalsStart(correlationId);
    const config = buildConfig(correlationId, signal);

    try {
      const data = await retryWithBackoff(
        async () => {
          try {
            const response = await apiClient.get("/api/approvals", config);
            const parseResult = ApprovalListSchema.safeParse(response.data);
            if (!parseResult.success) {
              governanceLogger.validationFailure(
                "approval list",
                parseResult.error.issues,
                correlationId,
              );
              throw new GovernanceValidationError(
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
            governanceLogger.retryAttempt(attempt, delayMs, err, correlationId),
        },
      );
      const durationMs = Math.round(performance.now() - startTime);
      governanceLogger.listApprovalsSuccess(data.length, durationMs, correlationId);
      return data;
    } catch (err) {
      const durationMs = Math.round(performance.now() - startTime);
      const normalized = normalizeError(err, "list");
      governanceLogger.listApprovalsFailure(normalized, durationMs, correlationId);
      throw normalized;
    }
  },

  async approveRequest(
    approvalId: string,
    correlationId?: string,
    signal?: AbortSignal,
  ): Promise<ApprovalDecisionResponse> {
    const startTime = performance.now();
    governanceLogger.approveStart(approvalId, correlationId);
    const config = buildConfig(correlationId, signal);

    try {
      const response = await apiClient.post(
        `/api/approvals/${approvalId}/approve`,
        undefined,
        config,
      );
      const parseResult = ApprovalDecisionResponseSchema.safeParse(response.data);
      if (!parseResult.success) {
        governanceLogger.validationFailure(
          `approve ${approvalId}`,
          parseResult.error.issues,
          correlationId,
        );
        throw new GovernanceValidationError(
          approvalId,
          parseResult.error.issues,
          parseResult.error,
        );
      }
      const durationMs = Math.round(performance.now() - startTime);
      governanceLogger.approveSuccess(approvalId, durationMs, correlationId);
      return parseResult.data;
    } catch (err) {
      const durationMs = Math.round(performance.now() - startTime);
      const normalized = normalizeError(err, approvalId);
      governanceLogger.approveFailure(approvalId, normalized, durationMs, correlationId);
      throw normalized;
    }
  },

  async rejectRequest(
    approvalId: string,
    rationale: string,
    correlationId?: string,
    signal?: AbortSignal,
  ): Promise<ApprovalDecisionResponse> {
    const startTime = performance.now();
    governanceLogger.rejectStart(approvalId, correlationId);
    const config = buildConfig(correlationId, signal);

    try {
      const response = await apiClient.post(
        `/api/approvals/${approvalId}/reject`,
        { rationale },
        config,
      );
      const parseResult = ApprovalDecisionResponseSchema.safeParse(response.data);
      if (!parseResult.success) {
        governanceLogger.validationFailure(
          `reject ${approvalId}`,
          parseResult.error.issues,
          correlationId,
        );
        throw new GovernanceValidationError(
          approvalId,
          parseResult.error.issues,
          parseResult.error,
        );
      }
      const durationMs = Math.round(performance.now() - startTime);
      governanceLogger.rejectSuccess(approvalId, durationMs, correlationId);
      return parseResult.data;
    } catch (err) {
      const durationMs = Math.round(performance.now() - startTime);
      const normalized = normalizeError(err, approvalId);
      governanceLogger.rejectFailure(approvalId, normalized, durationMs, correlationId);
      throw normalized;
    }
  },

  async getApprovalDetail(
    approvalId: string,
    correlationId?: string,
    signal?: AbortSignal,
  ): Promise<ApprovalDetail> {
    const startTime = performance.now();
    const config = buildConfig(correlationId, signal);

    try {
      const data = await retryWithBackoff(
        async () => {
          try {
            const response = await apiClient.get(`/api/approvals/${approvalId}`, config);
            const parseResult = ApprovalDetailSchema.safeParse(response.data);
            if (!parseResult.success) {
              governanceLogger.validationFailure(
                `approval ${approvalId}`,
                parseResult.error.issues,
                correlationId,
              );
              throw new GovernanceValidationError(
                approvalId,
                parseResult.error.issues,
                parseResult.error,
              );
            }
            return parseResult.data;
          } catch (err) {
            if (err instanceof AxiosError) throw classifyAxiosError(err, approvalId);
            throw err;
          }
        },
        {
          signal,
          onRetry: (attempt, delayMs, err) =>
            governanceLogger.retryAttempt(attempt, delayMs, err, correlationId),
        },
      );
      const durationMs = Math.round(performance.now() - startTime);
      // eslint-disable-next-line no-console
      console.debug(`[governanceApi] getApprovalDetail ${approvalId} (${durationMs}ms)`);
      return data;
    } catch (err) {
      const durationMs = Math.round(performance.now() - startTime);
      const normalized = normalizeError(err, approvalId);

      console.warn(
        `[governanceApi] getApprovalDetail ${approvalId} failed after ${durationMs}ms`,
        normalized,
      );
      throw normalized;
    }
  },

  // -------------------------------------------------------------------------
  // Overrides
  // -------------------------------------------------------------------------

  async listOverrides(correlationId?: string, signal?: AbortSignal): Promise<OverrideDetail[]> {
    const startTime = performance.now();
    governanceLogger.listOverridesStart(correlationId);
    const config = buildConfig(correlationId, signal);

    try {
      const data = await retryWithBackoff(
        async () => {
          try {
            const response = await apiClient.get("/api/overrides", config);
            const parseResult = OverrideListSchema.safeParse(response.data);
            if (!parseResult.success) {
              governanceLogger.validationFailure(
                "override list",
                parseResult.error.issues,
                correlationId,
              );
              throw new GovernanceValidationError(
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
            governanceLogger.retryAttempt(attempt, delayMs, err, correlationId),
        },
      );
      const durationMs = Math.round(performance.now() - startTime);
      governanceLogger.listOverridesSuccess(data.length, durationMs, correlationId);
      return data;
    } catch (err) {
      const durationMs = Math.round(performance.now() - startTime);
      const normalized = normalizeError(err, "list");
      governanceLogger.listOverridesFailure(normalized, durationMs, correlationId);
      throw normalized;
    }
  },

  async getOverride(
    overrideId: string,
    correlationId?: string,
    signal?: AbortSignal,
  ): Promise<OverrideDetail> {
    const startTime = performance.now();
    governanceLogger.getOverrideStart(overrideId, correlationId);
    const config = buildConfig(correlationId, signal);

    try {
      const data = await retryWithBackoff(
        async () => {
          try {
            const response = await apiClient.get(`/api/overrides/${overrideId}`, config);
            const parseResult = OverrideDetailSchema.safeParse(response.data);
            if (!parseResult.success) {
              governanceLogger.validationFailure(
                `override ${overrideId}`,
                parseResult.error.issues,
                correlationId,
              );
              throw new GovernanceValidationError(
                overrideId,
                parseResult.error.issues,
                parseResult.error,
              );
            }
            return parseResult.data;
          } catch (err) {
            if (err instanceof AxiosError) throw classifyAxiosError(err, overrideId);
            throw err;
          }
        },
        {
          signal,
          onRetry: (attempt, delayMs, err) =>
            governanceLogger.retryAttempt(attempt, delayMs, err, correlationId),
        },
      );
      const durationMs = Math.round(performance.now() - startTime);
      governanceLogger.getOverrideSuccess(overrideId, durationMs, correlationId);
      return data;
    } catch (err) {
      const durationMs = Math.round(performance.now() - startTime);
      const normalized = normalizeError(err, overrideId);
      governanceLogger.getOverrideFailure(overrideId, normalized, durationMs, correlationId);
      throw normalized;
    }
  },

  async requestOverride(
    payload: OverrideRequestForm,
    correlationId?: string,
    signal?: AbortSignal,
  ): Promise<OverrideCreateResponse> {
    const startTime = performance.now();
    governanceLogger.requestOverrideStart(correlationId);
    const config = buildConfig(correlationId, signal);

    try {
      const response = await apiClient.post("/api/overrides/request", payload, config);
      const parseResult = OverrideCreateResponseSchema.safeParse(response.data);
      if (!parseResult.success) {
        governanceLogger.validationFailure(
          "override request response",
          parseResult.error.issues,
          correlationId,
        );
        throw new GovernanceValidationError("new", parseResult.error.issues, parseResult.error);
      }
      const durationMs = Math.round(performance.now() - startTime);
      governanceLogger.requestOverrideSuccess(
        parseResult.data.override_id,
        durationMs,
        correlationId,
      );
      return parseResult.data;
    } catch (err) {
      const durationMs = Math.round(performance.now() - startTime);
      const normalized = normalizeError(err, "new");
      governanceLogger.requestOverrideFailure(normalized, durationMs, correlationId);
      throw normalized;
    }
  },

  // -------------------------------------------------------------------------
  // Promotions
  // -------------------------------------------------------------------------

  async listPromotions(
    candidateId: string,
    correlationId?: string,
    signal?: AbortSignal,
  ): Promise<PromotionHistoryEntry[]> {
    const startTime = performance.now();
    governanceLogger.listPromotionsStart(candidateId, correlationId);
    const config = buildConfig(correlationId, signal, {
      params: { candidate_id: candidateId },
    });

    try {
      const data = await retryWithBackoff(
        async () => {
          try {
            const response = await apiClient.get("/api/promotions", config);
            const parseResult = PromotionHistoryListSchema.safeParse(response.data);
            if (!parseResult.success) {
              governanceLogger.validationFailure(
                "promotion list",
                parseResult.error.issues,
                correlationId,
              );
              throw new GovernanceValidationError(
                candidateId,
                parseResult.error.issues,
                parseResult.error,
              );
            }
            return parseResult.data;
          } catch (err) {
            if (err instanceof AxiosError) throw classifyAxiosError(err, candidateId);
            throw err;
          }
        },
        {
          signal,
          onRetry: (attempt, delayMs, err) =>
            governanceLogger.retryAttempt(attempt, delayMs, err, correlationId),
        },
      );
      const durationMs = Math.round(performance.now() - startTime);
      governanceLogger.listPromotionsSuccess(candidateId, data.length, durationMs, correlationId);
      return data;
    } catch (err) {
      const durationMs = Math.round(performance.now() - startTime);
      const normalized = normalizeError(err, candidateId);
      governanceLogger.listPromotionsFailure(candidateId, normalized, durationMs, correlationId);
      throw normalized;
    }
  },
};
