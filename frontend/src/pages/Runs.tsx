/**
 * Run Monitor page — M26 real-time execution and optimization tracking.
 *
 * Purpose:
 *   Top-level page component for the /runs route. Handles URL parameter
 *   routing for run detail views and provides the run list/submission
 *   entry point.
 *
 * Responsibilities:
 *   - Parse run ID from URL search params for detail view.
 *   - Render RunDetailView when a run ID is selected.
 *   - Render run list (mobile cards or desktop table) when no run is selected.
 *   - Require authentication via useAuth.
 *   - Fetch recent runs via runsApi.listRuns.
 *
 * Does NOT:
 *   - Execute runs directly (delegated to backend services).
 *   - Design strategies (delegated to Strategy Studio).
 *   - Manage run artifacts (delegated to Artifacts).
 *
 * Dependencies:
 *   - useAuth for authentication enforcement.
 *   - RunDetailView for individual run monitoring.
 *   - RunCardList for mobile run list.
 *   - useSearchParams for URL-based run selection.
 *   - useIsMobile for responsive layout selection.
 *   - useQuery for data fetching with react-query.
 */

import { useSearchParams, useNavigate } from "react-router-dom";
import { useQuery } from "@tanstack/react-query";
import { useAuth } from "@/auth/useAuth";
import { useIsMobile } from "@/hooks/useMediaQuery";
import { RunDetailView } from "@/features/runs/components/RunDetailView";
import { RunCardList } from "@/features/runs/components/RunCardList";
import { runsApi } from "@/features/runs/api";

export default function Runs() {
  useAuth();
  const [searchParams] = useSearchParams();
  const navigate = useNavigate();
  const isMobile = useIsMobile();
  const selectedRunId = searchParams.get("id");

  // Fetch list of recent runs
  const {
    data: runListData,
    isLoading,
    error,
  } = useQuery({
    queryKey: ["runs", "list"],
    queryFn: async () => {
      return runsApi.listRuns({ limit: 50, offset: 0 });
    },
  });

  // Run detail view when an ID is selected
  if (selectedRunId) {
    return (
      <div className="space-y-6">
        <RunDetailView runId={selectedRunId} />
      </div>
    );
  }

  // Handle navigation from card click
  const handleRunClick = (runId: string) => {
    navigate(`/runs?id=${runId}`);
  };

  // Run list / submission entry point
  return (
    <div className="space-y-6" data-testid="runs-page">
      <div>
        <h1 className="text-2xl font-bold text-white">Run Monitor</h1>
        <p className="mt-1 text-sm text-gray-400">
          Monitor active backtests and optimization runs in real-time.
        </p>
      </div>

      {/* Mobile: card-based list */}
      {isMobile ? (
        <div className="space-y-4">
          <div>
            <h2 className="text-lg font-semibold text-white">Recent Runs</h2>
          </div>
          <RunCardList
            runs={runListData?.runs ?? []}
            onRunClick={handleRunClick}
            isLoading={isLoading}
          />
          {error && (
            <div className="rounded-lg border border-red-700 bg-red-900 p-4 text-sm text-red-200">
              Failed to load runs: {error instanceof Error ? error.message : "Unknown error"}
            </div>
          )}
        </div>
      ) : (
        /* Desktop: placeholder for future table view */
        <>
          <div className="rounded-lg border border-gray-700 bg-gray-800 p-6">
            <div className="flex items-center justify-between">
              <h2 className="text-lg font-semibold text-white">Active Runs</h2>
            </div>
            <p className="mt-2 text-sm text-gray-400">
              Submit a run from Strategy Studio or select a run ID to view its progress. Use the URL
              parameter{" "}
              <code className="rounded bg-gray-700 px-1 py-0.5 font-mono text-xs">
                ?id=RUN_ULID
              </code>{" "}
              to view a specific run.
            </p>
          </div>

          <div className="rounded-lg border border-gray-700 bg-gray-800 p-6">
            <h2 className="text-lg font-semibold text-white">Run History</h2>
            <p className="mt-2 text-sm text-gray-400">
              Completed and archived runs will appear here. Filter by strategy, date range, and
              status.
            </p>
          </div>
        </>
      )}
    </div>
  );
}
