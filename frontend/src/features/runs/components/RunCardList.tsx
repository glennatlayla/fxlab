/**
 * RunCardList — scrollable list of RunCards with status filter chips.
 *
 * Purpose:
 *   Display a vertical stack of RunCard components on mobile screens,
 *   with horizontal filter chips at the top for quick status filtering.
 *
 * Responsibilities:
 *   - Render filter chips: All, Running, Completed, Failed.
 *   - Filter runs by selected status.
 *   - Display filtered run cards in a scrollable list.
 *   - Show empty state when no runs match the filter.
 *   - Show loading skeleton while data is being fetched.
 *   - Forward click events to onRunClick callback.
 *
 * Does NOT:
 *   - Fetch run data (receives runs as prop).
 *   - Manage global state.
 *   - Navigate (parent component handles navigation).
 *
 * Dependencies:
 *   - RunCard (from ./RunCard).
 *   - RunRecord type (from @/types/run).
 *   - RunStatus type (from @/types/run).
 *
 * Example:
 *   <RunCardList
 *     runs={allRuns}
 *     onRunClick={(runId) => navigate(`/runs?id=${runId}`)}
 *     isLoading={isLoading}
 *   />
 */

import { useMemo, useState } from "react";
import type { RunRecord, RunStatus } from "@/types/run";
import { RUN_STATUS } from "@/types/run";
import { RunCard } from "./RunCard";

interface RunCardListProps {
  /** Array of run records to display. */
  runs: RunRecord[];
  /** Callback when a run card is clicked, receives the run ID. */
  onRunClick: (runId: string) => void;
  /** Whether the run list is currently loading. */
  isLoading?: boolean;
  /** Optional additional CSS class names. */
  className?: string;
}

type FilterStatus = RunStatus | "all";

/**
 * Render a scrollable list of run cards with status filters.
 *
 * Args:
 *   runs: Array of run records to display.
 *   onRunClick: Callback when a run card is clicked.
 *   isLoading: Whether data is currently loading.
 *   className: Optional additional CSS classes.
 */
export function RunCardList({
  runs,
  onRunClick,
  isLoading = false,
  className = "",
}: RunCardListProps) {
  const [selectedFilter, setSelectedFilter] = useState<FilterStatus>("all");

  // Filter runs based on selected status
  const filteredRuns = useMemo(() => {
    if (selectedFilter === "all") {
      return runs;
    }
    return runs.filter((run) => run.status === selectedFilter);
  }, [runs, selectedFilter]);

  // Skeleton loading state
  if (isLoading) {
    return (
      <div className={`space-y-2 ${className}`.trim()} role="status" aria-label="Loading runs">
        {[1, 2, 3].map((i) => (
          <div
            key={i}
            className="h-24 w-full animate-pulse rounded-lg border border-gray-700 bg-gray-800"
          />
        ))}
      </div>
    );
  }

  // Filter chips
  const filterOptions: Array<{ label: string; value: FilterStatus }> = [
    { label: "All", value: "all" },
    { label: "Running", value: RUN_STATUS.RUNNING },
    { label: "Completed", value: RUN_STATUS.COMPLETE },
    { label: "Failed", value: RUN_STATUS.FAILED },
  ];

  return (
    <div className={`space-y-4 ${className}`.trim()}>
      {/* Filter chips */}
      <div className="flex gap-2 overflow-x-auto pb-2">
        {filterOptions.map((option) => (
          <button
            key={option.value}
            onClick={() => setSelectedFilter(option.value)}
            className={`flex-shrink-0 rounded-full px-4 py-2 text-sm font-medium transition-colors ${
              selectedFilter === option.value
                ? "bg-blue-600 text-white"
                : "border border-gray-600 bg-gray-800 text-gray-300 hover:bg-gray-700"
            }`}
            aria-pressed={selectedFilter === option.value}
          >
            {option.label}
          </button>
        ))}
      </div>

      {/* Run cards or empty state */}
      {filteredRuns.length === 0 ? (
        <div className="rounded-lg border border-gray-700 bg-gray-800 p-6 text-center">
          <p className="text-sm text-gray-400">
            {selectedFilter === "all"
              ? "No runs yet. Submit a run from Strategy Studio to get started."
              : `No ${selectedFilter} runs found.`}
          </p>
        </div>
      ) : (
        <div className="space-y-2">
          {filteredRuns.map((run) => (
            <RunCard key={run.id} run={run} onClick={onRunClick} />
          ))}
        </div>
      )}
    </div>
  );
}
