/**
 * API orchestrator for the side-by-side run comparison view.
 *
 * Purpose:
 *   Fetch the metrics + equity-curve for two completed runs in parallel
 *   so the ``/runs/compare?a=...&b=...`` page can render both panels
 *   in a single round-trip's worth of latency.
 *
 * Responsibilities:
 *   - Compose ``getMetrics(runId)`` and ``getEquityCurve(runId)`` for
 *     both ``runIdA`` and ``runIdB`` via ``Promise.all``.
 *   - Surface a typed :class:`RunCompareData` result containing both
 *     runs' metrics, equity curves, and a small ``RunMeta`` summary
 *     suitable for the panel header.
 *   - Forward ``AbortSignal`` to every underlying request so the page
 *     can cancel in-flight fetches on unmount or param change.
 *
 * Does NOT:
 *   - Render UI or own React state — pure orchestration.
 *   - Add new HTTP endpoints — we reuse the existing M2.C3 sub-resource
 *     endpoints (``/runs/{id}/results/metrics`` and
 *     ``/runs/{id}/results/equity-curve``).
 *   - Compute deltas — the page component owns rendering / styling.
 *
 * Run-meta source-of-truth:
 *   The backend does not expose a plain ``GET /runs/{id}`` route in
 *   :mod:`services.api.routes.runs` (only ``/results``, ``/results/*``
 *   and ``/cancel``). Per the M-compare brief we derive the run meta
 *   shown in the panel header from the metrics endpoint payload — it
 *   already carries ``run_id`` and ``completed_at``. ``status`` is
 *   inferred from the success of the metrics fetch ("completed", since
 *   the metrics endpoint itself returns 409 when the run has not yet
 *   completed, and surfaces 404 when the run does not exist).
 *
 * Dependencies:
 *   - getMetrics, getEquityCurve from @/api/run_results (existing M2.C3
 *     wrappers — they own error classification).
 *   - @/types/run_results for response shapes.
 *
 * Error conditions:
 *   - Any error from the underlying fetches surfaces unchanged so the
 *     caller can branch on ``RunResultsNotFoundError`` /
 *     ``RunResultsConflictError`` etc. and surface the offending
 *     ``run_id`` in the banner.
 *
 * Example:
 *   const data = await fetchRunCompare(
 *     "01HRUNAAAAAAAAAAAAAAAAAAAA",
 *     "01HRUNBBBBBBBBBBBBBBBBBBBB",
 *   );
 *   // data.runA.metrics.sharpe_ratio === 1.45
 *   // data.runB.equityCurve.points.length === 250
 */

import { getEquityCurve, getMetrics } from "@/api/run_results";
import type { EquityCurveResponse, RunMetrics } from "@/types/run_results";

/**
 * Lightweight summary of a run, suitable for the comparison panel header.
 *
 * Distinct from the full ``RunRecord`` (which the run-monitor page uses);
 * we keep this minimal so we don't depend on a backend route that does
 * not exist for the compare view.
 *
 * Attributes:
 *   run_id: ULID of the run.
 *   status: Inferred run status. The compare view only fetches metrics
 *     + equity curve, both of which require the run to be COMPLETED, so
 *     a successful fetch implies "completed". Surfacing the field
 *     explicitly keeps the consumer panel decoupled from that detail.
 *   completed_at: ISO-8601 timestamp the engine finished, or null when
 *     the metrics endpoint did not include one (defensive — current
 *     backend always emits one for completed runs).
 */
export interface RunMeta {
  run_id: string;
  status: "completed";
  completed_at: string | null;
}

/**
 * One side of the comparison — all the data required to render a single
 * panel (metrics tiles, equity-curve chart, and the header summary).
 */
export interface RunComparePanelData {
  meta: RunMeta;
  metrics: RunMetrics;
  equityCurve: EquityCurveResponse;
}

/**
 * Top-level payload returned by :func:`fetchRunCompare`.
 *
 * ``runA`` corresponds to the ``a`` URL search param; ``runB`` to ``b``.
 * The page component is responsible for deciding which side is the
 * "base" vs the "variant" — this orchestrator stays neutral.
 */
export interface RunCompareData {
  runA: RunComparePanelData;
  runB: RunComparePanelData;
}

/**
 * Build a :class:`RunMeta` from a freshly-fetched :class:`RunMetrics`.
 *
 * The metrics endpoint is the source of truth for the panel header
 * because it already enforces "run exists AND is completed" via its
 * 404 / 409 contract.
 *
 * Args:
 *   metrics: Response body from ``GET /runs/{run_id}/results/metrics``.
 *
 * Returns:
 *   A :class:`RunMeta` populated from the metrics payload.
 */
function metaFromMetrics(metrics: RunMetrics): RunMeta {
  return {
    run_id: metrics.run_id,
    status: "completed",
    completed_at: metrics.completed_at,
  };
}

/**
 * Fetch metrics + equity curve for a single side of the comparison.
 *
 * Internal helper used by :func:`fetchRunCompare`. Pulled out so the
 * Promise.all in ``fetchRunCompare`` only lists two top-level
 * promises, which keeps stack traces readable when one side fails.
 *
 * Args:
 *   runId: ULID of the run to fetch.
 *   signal: Optional AbortSignal forwarded to both underlying requests.
 *
 * Returns:
 *   A :class:`RunComparePanelData` for this side.
 *
 * Raises:
 *   Whatever the underlying ``getMetrics`` / ``getEquityCurve`` raise
 *   (RunResultsNotFoundError, RunResultsConflictError,
 *   RunResultsAuthError, RunResultsValidationError,
 *   RunResultsNetworkError, AbortError).
 */
async function fetchOneSide(runId: string, signal?: AbortSignal): Promise<RunComparePanelData> {
  const [metrics, equityCurve] = await Promise.all([
    getMetrics(runId, signal),
    getEquityCurve(runId, signal),
  ]);
  return {
    meta: metaFromMetrics(metrics),
    metrics,
    equityCurve,
  };
}

/**
 * Fetch the full comparison payload for two runs in parallel.
 *
 * All four underlying HTTP calls (metrics + equity-curve for each run)
 * fire concurrently via a single ``Promise.all`` so total latency is
 * the slowest of the four, not the sum.
 *
 * Args:
 *   runIdA: ULID of the "A" side (mapped from the ``?a=`` URL param).
 *   runIdB: ULID of the "B" side (mapped from the ``?b=`` URL param).
 *   signal: Optional AbortSignal forwarded to every underlying request.
 *
 * Returns:
 *   A :class:`RunCompareData` with both sides populated.
 *
 * Raises:
 *   Any error from the underlying API layer is re-thrown unchanged so
 *   the caller can branch on it. ``Promise.all`` rejects on the first
 *   rejection, but the AbortSignal cancels the other in-flight requests
 *   so we don't leak them.
 *
 * Example:
 *   const controller = new AbortController();
 *   const data = await fetchRunCompare(
 *     "01HRUNAAAAAAAAAAAAAAAAAAAA",
 *     "01HRUNBBBBBBBBBBBBBBBBBBBB",
 *     controller.signal,
 *   );
 */
export async function fetchRunCompare(
  runIdA: string,
  runIdB: string,
  signal?: AbortSignal,
): Promise<RunCompareData> {
  const [runA, runB] = await Promise.all([
    fetchOneSide(runIdA, signal),
    fetchOneSide(runIdB, signal),
  ]);
  return { runA, runB };
}
