/**
 * RunCard — mobile-optimized card displaying a single run.
 *
 * Purpose:
 *   Render a compact, full-width card representing a single run in the RunCardList.
 *   Designed for mobile screens (max-width: 1023px) with touch-friendly tap targets.
 *
 * Responsibilities:
 *   - Display run ID (truncated with monospace font).
 *   - Display status badge using RunStatusBadge component.
 *   - Display strategy build ID (truncated).
 *   - Display run type (research or optimization).
 *   - Display progress bar with trial count.
 *   - Handle click events (onClick callback).
 *   - Provide visual affordance (chevron icon) indicating clickability.
 *
 * Does NOT:
 *   - Fetch data (receives run as prop).
 *   - Manage internal state.
 *   - Navigate (parent component handles navigation).
 *
 * Dependencies:
 *   - RunStatusBadge (from ./RunStatusBadge).
 *   - RunProgressBar (from ./RunProgressBar).
 *   - lucide-react (for ChevronRight icon).
 *   - RunRecord type (from @/types/run).
 *
 * Example:
 *   <RunCard
 *     run={runRecord}
 *     onClick={(runId) => navigate(`/runs?id=${runId}`)}
 *   />
 */

import { ChevronRight } from "lucide-react";
import type { RunRecord } from "@/types/run";
import { RunStatusBadge } from "./RunStatusBadge";
import { RunProgressBar } from "./RunProgressBar";

interface RunCardProps {
  /** The run record to display. */
  run: RunRecord;
  /** Callback fired when the card is clicked, receives the run ID. */
  onClick: (runId: string) => void;
  /** Optional additional CSS class names. */
  className?: string;
}

/**
 * Truncate a ULID to the first 8 characters for display.
 *
 * ULIDs are 26 characters, but we show only the first 8 for brevity.
 * Full ID is available in the monospace font for copy-paste if needed.
 */
function truncateUlid(ulid: string): string {
  return ulid.slice(0, 8);
}

/**
 * Render a mobile-optimized card for a single run.
 *
 * Args:
 *   run: The run record to display.
 *   onClick: Callback when card is clicked.
 *   className: Optional additional CSS classes.
 */
export function RunCard({ run, onClick, className = "" }: RunCardProps) {
  const truncatedRunId = truncateUlid(run.id);
  const truncatedBuildId = truncateUlid(run.strategy_build_id);
  const completedTrials = run.completed_trials ?? 0;
  const totalTrials = run.trial_count ?? 0;

  return (
    <button
      onClick={() => onClick(run.id)}
      data-testid="run-card"
      className={`w-full rounded-lg border border-gray-700 bg-gray-800 p-3 text-left transition-colors hover:bg-gray-700 active:bg-gray-600 ${className}`.trim()}
      aria-label={`Run ${run.id}, status: ${run.status}`}
    >
      {/* Top row: Run ID + Status Badge */}
      <div className="mb-2 flex items-center justify-between gap-2">
        <span className="font-mono text-sm text-gray-300" title={run.id}>
          {truncatedRunId}
        </span>
        <RunStatusBadge status={run.status} />
      </div>

      {/* Middle row: Strategy Build ID + Run Type */}
      <div className="mb-2 flex items-center justify-between gap-2">
        <div className="flex flex-col gap-0.5">
          <span className="text-xs text-gray-500">Build</span>
          <span className="font-mono text-xs text-gray-400" title={run.strategy_build_id}>
            {truncatedBuildId}
          </span>
        </div>
        <div className="flex items-center gap-2">
          <span className="rounded bg-gray-700 px-2 py-1 text-xs text-gray-300">
            {run.run_type}
          </span>
          <ChevronRight className="h-5 w-5 text-gray-500" aria-hidden="true" />
        </div>
      </div>

      {/* Bottom row: Progress bar + Trial count */}
      {totalTrials > 0 && (
        <div className="space-y-1">
          <RunProgressBar
            completedTrials={completedTrials}
            totalTrials={totalTrials}
            status={run.status}
            className="text-xs"
          />
        </div>
      )}
    </button>
  );
}
