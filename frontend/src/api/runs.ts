/**
 * Runs API client — submission of research runs derived from an
 * imported StrategyIR + ExperimentPlan pair.
 *
 * Purpose:
 *   Provide a typed wrapper around ``POST /runs/from-ir`` (M2.C2)
 *   so the strategy-detail "Execute backtest" flow can submit a plan
 *   without dealing with axios directly.
 *
 * Responsibilities:
 *   - ``submitRunFromIr(strategyId, experimentPlan)``: POST the pair
 *     and return ``{ run_id, status }`` on 201. Errors propagate as
 *     ``AxiosError`` so the caller can surface 422 detail messages
 *     inline in the modal.
 *
 * Does NOT:
 *   - Resolve dataset references (the backend does that).
 *   - Poll run status (see ``features/runs/api.ts`` and
 *     ``useRunPolling`` for that).
 *   - Validate the plan beyond what TypeScript already enforces; the
 *     hand-edited form runs ``validateExperimentPlan`` before calling
 *     this function.
 *
 * Auth scope: ``runs:write`` (enforced by the backend route).
 *
 * Dependencies:
 *   - @/api/client (axios instance with auth + correlation-ID).
 *   - @/types/experiment_plan for the typed payload.
 *
 * Error conditions:
 *   - 401 → intercepted by apiClient, triggers logout.
 *   - 404 → unknown ``dataset_ref`` (caller surfaces inline).
 *   - 422 → Pydantic ValidationError on the plan (caller surfaces inline).
 *   - Network errors → AxiosError thrown to caller.
 *
 * Example:
 *   const { run_id } = await submitRunFromIr(strategyId, plan);
 *   navigate(`/runs/${run_id}`);
 */

import { AxiosError, type AxiosResponse } from "axios";
import { apiClient } from "@/api/client";
import type { ExperimentPlan } from "@/types/experiment_plan";

/**
 * Minimal response shape consumed by the strategy-detail modal.
 *
 * The backend returns the full RunRecord (see
 * ``services/api/routes/runs.py``); we only require ``run_id`` and
 * ``status`` here because the modal navigates immediately to the run
 * monitor, which re-fetches the full record. Additional fields are
 * preserved on ``Record<string, unknown>`` so callers that want them
 * can read them without re-typing.
 */
export interface SubmitRunFromIrResponse {
  /** ULID of the newly created run. */
  run_id: string;
  /** Initial status — typically ``"pending"`` immediately after submit. */
  status: string;
  /** Pass-through for any additional fields on the RunRecord. */
  [key: string]: unknown;
}

/**
 * Submit a research run derived from an imported StrategyIR and a
 * hand-edited (or uploaded) :class:`ExperimentPlan`.
 *
 * Args:
 *   strategyId: ULID of the strategy in the FXLab catalog.
 *   experimentPlan: A plan that has already passed
 *     :func:`validateExperimentPlan`.
 *
 * Returns:
 *   The new run's ``{ run_id, status, ... }`` envelope.
 *
 * Raises:
 *   AxiosError on network failure or non-2xx response. The caller is
 *   responsible for branching on ``error.response?.status`` to render
 *   the right inline message (404 vs 422 vs 500).
 */
export async function submitRunFromIr(
  strategyId: string,
  experimentPlan: ExperimentPlan,
): Promise<SubmitRunFromIrResponse> {
  const resp: AxiosResponse<SubmitRunFromIrResponse> =
    await apiClient.post<SubmitRunFromIrResponse>("/runs/from-ir", {
      strategy_id: strategyId,
      experiment_plan: experimentPlan,
    });
  return resp.data;
}

// ---------------------------------------------------------------------------
// POST /runs/{runId}/cancel — operator-driven cancellation
// ---------------------------------------------------------------------------

/**
 * Wire-format payload returned by ``POST /runs/{run_id}/cancel``.
 *
 * Mirrors :class:`libs.contracts.run_results.RunCancelResult`. The
 * ``cancelled`` flag is the canonical "did anything happen" signal —
 * the backend returns 409 (so this body is only present on 200) when
 * the row was already terminal, but the same shape is used in the
 * detail string for log surfacing parity.
 */
export interface RunCancelResult {
  /** ULID of the run the cancel was requested for. */
  run_id: string;
  /** Status the row carried just before the cancel attempt. */
  previous_status: "pending" | "queued" | "running" | "completed" | "failed" | "cancelled";
  /** Status the row carries after the cancel attempt. */
  current_status: "pending" | "queued" | "running" | "completed" | "failed" | "cancelled";
  /** True when the row was actually transitioned to CANCELLED. */
  cancelled: boolean;
  /** Free-form explanatory string ("user_requested" | "terminal_state" | ...). */
  reason: string;
}

/**
 * Typed error for ``POST /runs/{run_id}/cancel`` failures.
 *
 * Carries the HTTP status and the backend ``detail`` string so the
 * Recent runs section can render a typed toast without parsing
 * free-form messages.
 */
export class CancelRunError extends Error {
  constructor(
    message: string,
    public readonly statusCode?: number,
    public readonly detail?: string,
  ) {
    super(message);
    this.name = "CancelRunError";
  }
}

/**
 * Cancel a research run, aborting any in-flight executor task.
 *
 * Args:
 *   runId: ULID of the run to cancel.
 *   reason: Optional operator-supplied reason. Surfaced in audit logs;
 *     the backend uses the canonical ``error_message='user_requested'``
 *     for the persisted record so the row state is consistent across
 *     callers regardless of what reason was supplied.
 *
 * Returns:
 *   A :class:`RunCancelResult` envelope on 200.
 *
 * Raises:
 *   CancelRunError on any non-2xx response. ``statusCode`` carries the
 *     HTTP status; ``detail`` carries the backend's ``detail`` string
 *     when present.
 *   AxiosError on network failure.
 */
export async function cancelRun(runId: string, reason?: string): Promise<RunCancelResult> {
  try {
    const body = reason !== undefined ? { reason } : undefined;
    const resp = await apiClient.post<RunCancelResult>(`/runs/${runId}/cancel`, body);
    return resp.data;
  } catch (err) {
    if (err instanceof AxiosError && err.response) {
      const status = err.response.status;
      const detailRaw = err.response.data?.detail;
      const detail =
        typeof detailRaw === "string"
          ? detailRaw
          : `Failed to cancel run ${runId} (status ${status})`;
      throw new CancelRunError(
        detail,
        status,
        typeof detailRaw === "string" ? detailRaw : undefined,
      );
    }
    throw err;
  }
}

export const runsFromIrApi = {
  submitRunFromIr,
  cancelRun,
};
