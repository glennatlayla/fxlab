/**
 * RunProgressBar — trial completion progress indicator.
 *
 * Purpose:
 *   Show visual progress of trial execution as a percentage bar
 *   with label showing completed/total counts.
 *
 * Responsibilities:
 *   - Calculate and display completion percentage.
 *   - Animate the progress bar fill during active runs.
 *   - Display completed_trials / trial_count as text.
 *
 * Does NOT:
 *   - Fetch data (receives props from parent).
 *   - Handle click events.
 */

import { RUN_STATUS } from "@/types/run";
import type { RunProgressBarProps } from "../types";

/**
 * Render a trial progress bar.
 *
 * Args:
 *   completedTrials: Number of completed trials.
 *   totalTrials: Total number of trials planned.
 *   status: Current run status (controls animation).
 *   className: Optional additional CSS class names.
 */
export function RunProgressBar({
  completedTrials,
  totalTrials,
  status,
  className = "",
}: RunProgressBarProps) {
  const percentage = totalTrials > 0 ? Math.round((completedTrials / totalTrials) * 100) : 0;
  const isActive = status === RUN_STATUS.RUNNING;

  return (
    <div className={`w-full ${className}`.trim()} data-testid="run-progress-bar">
      <div className="mb-1 flex items-center justify-between text-sm">
        <span className="text-gray-400">Trial Progress</span>
        <span className="font-mono text-gray-300">
          {completedTrials} / {totalTrials} ({percentage}%)
        </span>
      </div>
      <div
        className="h-2.5 w-full overflow-hidden rounded-full bg-gray-700"
        role="progressbar"
        aria-valuenow={percentage}
        aria-valuemin={0}
        aria-valuemax={100}
        aria-label={`Trial progress: ${percentage}%`}
      >
        <div
          className={`h-full rounded-full transition-all duration-500 ${
            status === RUN_STATUS.COMPLETE
              ? "bg-green-500"
              : status === RUN_STATUS.FAILED
                ? "bg-red-500"
                : "bg-blue-500"
          } ${isActive ? "animate-pulse" : ""}`}
          style={{ width: `${percentage}%` }}
        />
      </div>
    </div>
  );
}
