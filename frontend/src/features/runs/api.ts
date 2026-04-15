/**
 * Runs API service — HTTP calls for run submission and monitoring.
 *
 * Purpose:
 *   Centralise all run-related API calls behind typed functions.
 *   Consumed by hooks (useRunPolling, useRunSubmission) and the
 *   RunPage component tree.
 *
 * Responsibilities:
 *   - Submit research runs via POST /runs/research.
 *   - Submit optimization runs via POST /runs/optimize.
 *   - Poll run status via GET /runs/{run_id}.
 *   - Fetch trial list via GET /runs/{run_id}/trials.
 *   - Fetch single trial detail via GET /runs/{run_id}/trials/{trial_id}.
 *   - Cancel a run via POST /runs/{run_id}/cancel.
 *   - Validate all API responses at runtime with Zod schemas.
 *
 * Does NOT:
 *   - Contain business logic or polling orchestration (see useRunPolling).
 *   - Manage state (that's the hooks' job).
 *   - Handle auth (apiClient interceptors handle Bearer tokens).
 *
 * Dependencies:
 *   - @/api/client (axios instance with auth injection).
 *   - @/types/run for typed request/response shapes.
 *   - @/types/run.schemas for Zod runtime validation.
 *
 * Error conditions:
 *   - Network errors → AxiosError thrown to caller.
 *   - 401 → intercepted by apiClient, triggers logout.
 *   - 404 on getRunStatus → throws, caller decides how to handle.
 *   - 422 on submission → throws with validation details.
 *   - ZodError → response did not match expected schema.
 *
 * Example:
 *   const run = await runsApi.submitResearchRun({ strategy_build_id: "...", config: {...} });
 *   const status = await runsApi.getRunStatus(run.id);
 *   const trials = await runsApi.getTrials(run.id, { offset: 0, limit: 50 });
 */

import { apiClient } from "@/api/client";
import type {
  RunRecord,
  TrialRecord,
  ResearchRunSubmission,
  OptimizationRunSubmission,
} from "@/types/run";
import { RunRecordSchema, TrialRecordSchema, TrialListResponseSchema } from "@/types/run.schemas";

// ---------------------------------------------------------------------------
// Response types for paginated trial list
// ---------------------------------------------------------------------------

/** Paginated trial list response shape. */
export interface TrialListResponse {
  /** Array of trial records for the requested page. */
  trials: TrialRecord[];
  /** Total number of trials in this run. */
  total: number;
  /** Offset used for this page. */
  offset: number;
  /** Page size limit. */
  limit: number;
}

/** Pagination parameters for trial list requests. */
export interface TrialListParams {
  /** Zero-based offset into the trial list. */
  offset: number;
  /** Maximum number of trials to return. */
  limit: number;
}

/** Paginated run list response shape. */
export interface RunListResponse {
  /** Array of run records. */
  runs: RunRecord[];
  /** Total number of runs. */
  total: number;
  /** Offset used for this page. */
  offset: number;
  /** Page size limit. */
  limit: number;
}

/** Pagination parameters for run list requests. */
export interface RunListParams {
  /** Zero-based offset into the run list. */
  offset?: number;
  /** Maximum number of runs to return. */
  limit?: number;
  /** Optional filter by status (pending, running, complete, failed, cancelled). */
  status?: string;
}

// ---------------------------------------------------------------------------
// API service
// ---------------------------------------------------------------------------

export const runsApi = {
  /**
   * Fetch a paginated list of runs.
   *
   * Used by the run list/history views to show recent runs.
   *
   * Args:
   *   params: Pagination and filter parameters (optional).
   *
   * Returns:
   *   RunListResponse with run array and pagination metadata.
   *
   * Raises:
   *   AxiosError on network failure.
   *   ZodError if response does not match expected schema.
   */
  async listRuns(params?: RunListParams): Promise<RunListResponse> {
    const resp = await apiClient.get<RunListResponse>("/runs", { params });
    // Validate each run in the response
    const validRuns = resp.data.runs.map((run) => RunRecordSchema.parse(run));
    return {
      ...resp.data,
      runs: validRuns,
    };
  },

  /**
   * Submit a research run for execution.
   *
   * Args:
   *   payload: Research run configuration with strategy build ID.
   *
   * Returns:
   *   RunRecord for the newly created run (status will be "pending").
   *
   * Raises:
   *   AxiosError on network failure or 422 validation error.
   *   ZodError if response does not match RunRecordSchema.
   */
  async submitResearchRun(payload: ResearchRunSubmission): Promise<RunRecord> {
    const resp = await apiClient.post<RunRecord>("/runs/research", payload);
    return RunRecordSchema.parse(resp.data);
  },

  /**
   * Submit an optimization run for execution.
   *
   * Args:
   *   payload: Optimization run configuration with strategy build ID and max trials.
   *
   * Returns:
   *   RunRecord for the newly created run (status will be "pending").
   *
   * Raises:
   *   AxiosError on network failure or 422 validation error.
   *   ZodError if response does not match RunRecordSchema.
   */
  async submitOptimizationRun(payload: OptimizationRunSubmission): Promise<RunRecord> {
    const resp = await apiClient.post<RunRecord>("/runs/optimize", payload);
    return RunRecordSchema.parse(resp.data);
  },

  /**
   * Fetch the current status of a run.
   *
   * Used by the polling hook to check for state transitions.
   *
   * Args:
   *   runId: ULID of the run to check.
   *
   * Returns:
   *   RunRecord with current status and live progress fields.
   *
   * Raises:
   *   AxiosError with 404 if run does not exist.
   *   ZodError if response does not match RunRecordSchema.
   */
  async getRunStatus(runId: string): Promise<RunRecord> {
    const resp = await apiClient.get<RunRecord>(`/runs/${runId}`);
    return RunRecordSchema.parse(resp.data);
  },

  /**
   * Fetch a paginated list of trials for a run.
   *
   * Supports virtual scroll by requesting specific pages of trials.
   *
   * Args:
   *   runId: ULID of the parent run.
   *   params: Pagination parameters (offset, limit).
   *
   * Returns:
   *   TrialListResponse with trial array and pagination metadata.
   *
   * Raises:
   *   AxiosError with 404 if run does not exist.
   *   ZodError if response does not match TrialListResponseSchema.
   */
  async getTrials(runId: string, params: TrialListParams): Promise<TrialListResponse> {
    const resp = await apiClient.get<TrialListResponse>(`/runs/${runId}/trials`, { params });
    return TrialListResponseSchema.parse(resp.data);
  },

  /**
   * Fetch a single trial by ID.
   *
   * Used by the TrialDetailModal to show full trial information.
   *
   * Args:
   *   runId: ULID of the parent run.
   *   trialId: ULID of the trial.
   *
   * Returns:
   *   TrialRecord with full parameters, metrics, and fold data.
   *
   * Raises:
   *   AxiosError with 404 if trial does not exist.
   *   ZodError if response does not match TrialRecordSchema.
   */
  async getTrialDetail(runId: string, trialId: string): Promise<TrialRecord> {
    const resp = await apiClient.get<TrialRecord>(`/runs/${runId}/trials/${trialId}`);
    return TrialRecordSchema.parse(resp.data);
  },

  /**
   * Cancel a running or pending run.
   *
   * Args:
   *   runId: ULID of the run to cancel.
   *   reason: Human-readable reason for cancellation.
   *
   * Returns:
   *   RunRecord with updated status ("cancelled").
   *
   * Raises:
   *   AxiosError with 409 if run is already in a terminal state.
   *   ZodError if response does not match RunRecordSchema.
   */
  async cancelRun(runId: string, reason: string): Promise<RunRecord> {
    const resp = await apiClient.post<RunRecord>(`/runs/${runId}/cancel`, {
      reason,
    });
    return RunRecordSchema.parse(resp.data);
  },
};
