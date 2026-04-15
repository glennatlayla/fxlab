/**
 * OptimizationProgress — trial gauge, best trial, trials-per-minute.
 *
 * Purpose:
 *   Display live optimization metrics in a compact card format.
 *   Shows trial count gauge, best-trial-so-far, and throughput.
 *
 * Responsibilities:
 *   - Render trial completion gauge.
 *   - Display best objective value and which trial achieved it.
 *   - Show trials-per-minute throughput metric.
 *
 * Does NOT:
 *   - Fetch data (receives OptimizationMetrics as props).
 *   - Handle polling or state management.
 */

import { RUN_STATUS } from "@/types/run";
import type { OptimizationProgressProps } from "../types";

/**
 * Render optimization progress metrics.
 *
 * Args:
 *   metrics: Aggregated optimization metrics.
 *   status: Current run status.
 *   className: Optional additional CSS class names.
 */
export function OptimizationProgress({
  metrics,
  status,
  className = "",
}: OptimizationProgressProps) {
  const { totalTrials, completedTrials, bestObjectiveValue, bestTrialIndex, trialsPerMinute } =
    metrics;
  const percentage = totalTrials > 0 ? Math.round((completedTrials / totalTrials) * 100) : 0;
  const isActive = status === RUN_STATUS.RUNNING;

  return (
    <div
      className={`rounded-lg border border-gray-700 bg-gray-800 p-4 ${className}`.trim()}
      data-testid="optimization-progress"
    >
      <h3 className="mb-3 text-sm font-semibold text-gray-300">Optimization Progress</h3>

      <div className="grid grid-cols-1 gap-4 sm:grid-cols-3">
        {/* Trial gauge */}
        <div className="text-center">
          <div className="text-2xl font-bold text-white">
            {completedTrials}
            <span className="text-sm font-normal text-gray-400"> / {totalTrials}</span>
          </div>
          <div className="mt-1 text-xs text-gray-400">Trials ({percentage}%)</div>
          <div
            className="mt-2 h-1.5 w-full overflow-hidden rounded-full bg-gray-700"
            role="progressbar"
            aria-valuenow={percentage}
            aria-valuemin={0}
            aria-valuemax={100}
            aria-label={`Optimization trial progress: ${percentage}%`}
          >
            <div
              className={`h-full rounded-full bg-blue-500 transition-all duration-500 ${isActive ? "animate-pulse" : ""}`}
              style={{ width: `${percentage}%` }}
            />
          </div>
        </div>

        {/* Best trial */}
        <div className="text-center">
          <div className="text-2xl font-bold text-white">
            {bestObjectiveValue !== null ? bestObjectiveValue.toFixed(4) : "—"}
          </div>
          <div className="mt-1 text-xs text-gray-400">
            Best Objective{bestTrialIndex !== null ? ` (Trial #${bestTrialIndex})` : ""}
          </div>
        </div>

        {/* Throughput */}
        <div className="text-center">
          <div className="text-2xl font-bold text-white">{trialsPerMinute.toFixed(1)}</div>
          <div className="mt-1 text-xs text-gray-400">Trials / min</div>
        </div>
      </div>
    </div>
  );
}
