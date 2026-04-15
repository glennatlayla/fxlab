/**
 * Strategy API service — HTTP calls for strategy management and draft persistence.
 *
 * Purpose:
 *   Centralise all strategy-related API calls behind typed functions.
 *   Consumed by hooks (useStrategyDraft, useDraftAutosave), page components
 *   (StrategyStudio), and the DslEditor for live validation.
 *
 * Responsibilities:
 *   - Call POST /strategies to create a new strategy (M10).
 *   - Call POST /strategies/validate-dsl for live DSL validation (M10).
 *   - Call GET /strategies/{id} to fetch a strategy by ID (M10).
 *   - Call POST /strategies/draft/autosave for periodic draft persistence.
 *   - Call GET /strategies/draft/autosave/latest for session recovery.
 *   - Call DELETE /strategies/draft/autosave/{id} for "Start Fresh".
 *   - Map HTTP responses to typed interfaces.
 *
 * Does NOT:
 *   - Contain business logic or validation.
 *   - Manage state (that's the hooks' job).
 *   - Handle auth (apiClient interceptors handle Bearer tokens).
 *
 * Dependencies:
 *   - @/api/client (axios instance with auth injection).
 *   - @/types/strategy for typed request/response shapes.
 *
 * Error conditions:
 *   - Network errors → AxiosError thrown to caller.
 *   - 401 → intercepted by apiClient, triggers logout.
 *   - 404 → throws, caller decides how to handle.
 *   - 422 on validation failure → throws with structured details.
 *
 * Example:
 *   const result = await strategyApi.createStrategy({ name: "RSI Reversal", ... });
 *   const validation = await strategyApi.validateDsl("RSI(14) < 30");
 */

import { AxiosError } from "axios";
import { apiClient } from "@/api/client";
import type {
  DraftAutosavePayload,
  DraftAutosaveResponse,
  DraftAutosaveRecord,
} from "@/types/strategy";
import { DraftAutosaveResponseSchema, DraftAutosaveRecordSchema } from "@/types/strategy.schemas";

// ---------------------------------------------------------------------------
// Types for strategy creation and DSL validation (M10)
// ---------------------------------------------------------------------------

/** Request payload for POST /strategies. */
export interface CreateStrategyRequest {
  name: string;
  entry_condition: string;
  exit_condition: string;
  description?: string;
  instrument?: string;
  timeframe?: string;
  max_position_size?: number;
  stop_loss_percent?: number;
  take_profit_percent?: number;
  parameters?: Record<string, unknown>;
}

/** Validation error detail from the DSL parser. */
export interface DslValidationError {
  message: string;
  line: number;
  column: number;
  suggestion: string | null;
}

/** Result of DSL validation. */
export interface DslValidationResult {
  is_valid: boolean;
  errors: DslValidationError[];
  indicators_used: string[];
  variables_used: string[];
}

/** Result of strategy creation — includes both the persisted strategy and validation metadata. */
export interface CreateStrategyResult {
  strategy: {
    id: string;
    name: string;
    code: string;
    version: string;
    created_by: string;
    is_active: boolean;
    created_at: string;
    updated_at: string;
  };
  entry_validation: DslValidationResult;
  exit_validation: DslValidationResult;
  indicators_used: string[];
  variables_used: string[];
}

/** Strategy record returned by GET /strategies/{id}. */
export interface StrategyRecord {
  id: string;
  name: string;
  code: string;
  version: string;
  created_by: string;
  is_active: boolean;
  parsed_code: Record<string, unknown>;
  created_at: string;
  updated_at: string;
}

/** Typed error for strategy API failures. */
export class StrategyApiError extends Error {
  constructor(
    message: string,
    public readonly statusCode?: number,
    public readonly detail?: string,
  ) {
    super(message);
    this.name = "StrategyApiError";
  }
}

export const strategyApi = {
  /**
   * Persist a draft autosave to the backend.
   *
   * Args:
   *   payload: Draft form state + metadata for recovery.
   *
   * Returns:
   *   DraftAutosaveResponse with server-assigned ID and timestamp.
   *
   * Raises:
   *   AxiosError on network failure or 422 validation error.
   *   ZodError if response does not match schema (runtime validation).
   */
  async saveAutosave(payload: DraftAutosavePayload): Promise<DraftAutosaveResponse> {
    const resp = await apiClient.post<DraftAutosaveResponse>("/strategies/draft/autosave", payload);
    // Validate response structure at runtime before returning to caller
    return DraftAutosaveResponseSchema.parse(resp.data);
  },

  /**
   * Retrieve the latest draft autosave for a user.
   *
   * Args:
   *   userId: ULID of the user to check for recoverable drafts.
   *
   * Returns:
   *   DraftAutosaveRecord if a recoverable draft exists, null otherwise.
   *   Returns null on 204 No Content (no draft found).
   *
   * Raises:
   *   ZodError if 200 response does not match schema (runtime validation).
   */
  async getLatestAutosave(userId: string): Promise<DraftAutosaveRecord | null> {
    const resp = await apiClient.get<DraftAutosaveRecord>("/strategies/draft/autosave/latest", {
      params: { user_id: userId },
    });

    // Backend returns 204 No Content when no autosave exists.
    if (resp.status === 204) return null;

    // Validate response structure at runtime before returning to caller
    return DraftAutosaveRecordSchema.parse(resp.data);
  },

  /**
   * Delete a draft autosave record ("Start Fresh" action).
   *
   * Args:
   *   autosaveId: ULID of the autosave record to delete.
   *
   * Raises:
   *   AxiosError with 404 if the autosave does not exist.
   */
  async deleteAutosave(autosaveId: string): Promise<void> {
    await apiClient.delete(`/strategies/draft/autosave/${autosaveId}`);
  },

  // -----------------------------------------------------------------------
  // Strategy CRUD and DSL validation (M10)
  // -----------------------------------------------------------------------

  /**
   * Create a new strategy with validated DSL conditions.
   *
   * Args:
   *   request: CreateStrategyRequest with name, conditions, and risk params.
   *
   * Returns:
   *   CreateStrategyResult with persisted strategy and validation metadata.
   *
   * Raises:
   *   StrategyApiError with 422 if DSL conditions are invalid.
   *   AxiosError on network failure.
   *
   * Example:
   *   const result = await strategyApi.createStrategy({
   *     name: "RSI Reversal",
   *     entry_condition: "RSI(14) < 30",
   *     exit_condition: "RSI(14) > 70",
   *   });
   */
  async createStrategy(request: CreateStrategyRequest): Promise<CreateStrategyResult> {
    try {
      const resp = await apiClient.post<CreateStrategyResult>("/strategies/", request);
      return resp.data;
    } catch (err) {
      if (err instanceof AxiosError && err.response) {
        const status = err.response.status;
        const detail =
          typeof err.response.data?.detail === "string"
            ? err.response.data.detail
            : "Strategy creation failed";
        throw new StrategyApiError(detail, status, detail);
      }
      throw err;
    }
  },

  /**
   * Validate a DSL condition expression without creating a strategy.
   *
   * Used by the DslEditor for live validation as the user types.
   * This is a lightweight call — no side effects, no persistence.
   *
   * Args:
   *   expression: Raw DSL condition string.
   *
   * Returns:
   *   DslValidationResult with is_valid, errors, indicators, variables.
   *
   * Example:
   *   const result = await strategyApi.validateDsl("RSI(14) < 30");
   *   if (!result.is_valid) { showErrors(result.errors); }
   */
  async validateDsl(expression: string): Promise<DslValidationResult> {
    const resp = await apiClient.post<DslValidationResult>("/strategies/validate-dsl", {
      expression,
    });
    return resp.data;
  },

  /**
   * Retrieve a strategy by its ULID.
   *
   * Args:
   *   strategyId: ULID of the strategy.
   *
   * Returns:
   *   StrategyRecord with parsed code fields.
   *
   * Raises:
   *   StrategyApiError with 404 if strategy does not exist.
   */
  async getStrategy(strategyId: string): Promise<StrategyRecord> {
    try {
      const resp = await apiClient.get<StrategyRecord>(`/strategies/${strategyId}`);
      return resp.data;
    } catch (err) {
      if (err instanceof AxiosError && err.response?.status === 404) {
        throw new StrategyApiError("Strategy not found", 404);
      }
      throw err;
    }
  },
};
