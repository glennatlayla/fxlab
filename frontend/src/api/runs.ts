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

import type { AxiosResponse } from "axios";
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

export const runsFromIrApi = {
  submitRunFromIr,
};
