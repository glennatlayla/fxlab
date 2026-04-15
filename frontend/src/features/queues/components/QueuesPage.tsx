/**
 * QueuesPage — paginated registry of all queues with per-queue-class cards.
 *
 * Purpose:
 *   Render the /queues page (M30). Operators can view queue snapshots with
 *   depth, contention score, and other metrics. The ComputeContention
 *   component below the list provides detailed contention analysis with
 *   time-range selection.
 *
 * Responsibilities:
 *   - Fetch all queues via queuesApi.listQueues().
 *   - Render a card for each queue showing: queue_name, depth, and contention_score.
 *   - Color-code contention badges based on level (low/medium/high).
 *   - Surface loading, error, and empty states.
 *   - Compose ComputeContention section below queue cards.
 *   - Honor AbortSignal teardown via TanStack Query.
 *
 * Does NOT:
 *   - Mutate queue configuration (read-only surface in M30).
 *   - Compute contention scores locally — fetches authoritative data from API.
 *
 * Acceptance:
 *   - Queue cards update via TanStack Query without full page reload.
 *   - Contention badge color reflects health status immediately.
 */

import { memo, useCallback, useEffect, useId, useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import { queuesApi } from "../api";
import { queuesLogger } from "../logger";
import {
  getContentionLevel,
  CONTENTION_LEVEL_LABELS,
  CONTENTION_BADGE_CLASSES,
} from "../constants";
import type { QueueSnapshot } from "@/types/queues";
import { ComputeContention } from "./ComputeContention";

/**
 * QueuesPage — operator dashboard for queue monitoring.
 *
 * Fetches the authoritative list of all queues and renders per-queue cards
 * with current depth and contention. Uses React.memo for performance.
 */
export const QueuesPage = memo(function QueuesPage() {
  const correlationId = useId();

  useEffect(() => {
    queuesLogger.pageMount("QueuesPage", correlationId);
    return () => queuesLogger.pageUnmount("QueuesPage", correlationId);
  }, [correlationId]);

  const { data, isLoading, error, refetch } = useQuery({
    queryKey: ["queues", "list"],
    queryFn: ({ signal }) => queuesApi.listQueues(correlationId, signal),
  });

  const queues = useMemo<readonly QueueSnapshot[]>(() => data?.queues ?? [], [data]);

  const handleRetry = useCallback(() => {
    refetch();
  }, [refetch]);

  return (
    <div data-testid="queues-page" className="mx-auto max-w-5xl space-y-6">
      <div>
        <h1 className="text-xl font-semibold text-slate-900">Queue Operations</h1>
        <p className="mt-1 text-sm text-slate-500">
          Monitor queue depth, contention, and throughput across queue classes.
        </p>
      </div>

      {isLoading ? (
        <div
          data-testid="queues-loading"
          role="status"
          className="flex items-center justify-center py-12"
        >
          <p className="text-sm text-slate-500">Loading queues…</p>
        </div>
      ) : error ? (
        <div
          data-testid="queues-error"
          role="alert"
          className="rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700"
        >
          <p className="font-medium">Failed to load queues</p>
          <p className="mt-1">{error instanceof Error ? error.message : "Unknown error."}</p>
          <button
            type="button"
            onClick={handleRetry}
            className="mt-2 rounded-md bg-red-600 px-3 py-1.5 text-sm text-white hover:bg-red-700"
          >
            Retry
          </button>
        </div>
      ) : queues.length === 0 ? (
        <div data-testid="queues-empty" className="py-12 text-center text-sm text-slate-500">
          No queues registered.
        </div>
      ) : (
        <section aria-label="Queue registry" className="space-y-3">
          <h2 className="text-base font-semibold text-slate-800">Queue Snapshots</h2>
          <ul
            data-testid="queues-list"
            className="grid grid-cols-1 gap-3 md:grid-cols-2 lg:grid-cols-3"
          >
            {queues.map((queue) => {
              const level = getContentionLevel(queue.contention_score);
              const badgeClasses = CONTENTION_BADGE_CLASSES[level];
              const levelLabel = CONTENTION_LEVEL_LABELS[level];

              return (
                <li
                  key={queue.id}
                  data-testid={`queue-card-${queue.queue_name}`}
                  className="rounded-lg border border-slate-200 bg-white p-4 shadow-sm"
                >
                  <div className="space-y-3">
                    <div>
                      <h3 className="text-sm font-semibold text-slate-900">{queue.queue_name}</h3>
                    </div>

                    <div className="grid grid-cols-2 gap-2 text-xs">
                      <div className="flex flex-col gap-1">
                        <span className="text-slate-500">Depth</span>
                        <span
                          data-testid={`queue-depth-${queue.queue_name}`}
                          className="text-lg font-semibold text-slate-900"
                        >
                          {queue.depth}
                        </span>
                      </div>
                      <div className="flex flex-col gap-1">
                        <span className="text-slate-500">Contention</span>
                        <span
                          data-testid={`queue-contention-badge-${queue.queue_name}`}
                          className={`inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium ring-1 ring-inset ${badgeClasses} w-fit`}
                        >
                          {queue.contention_score} {levelLabel}
                        </span>
                      </div>
                    </div>

                    <p className="text-xs text-slate-500">
                      {new Date(queue.timestamp).toLocaleString()}
                    </p>
                  </div>
                </li>
              );
            })}
          </ul>
        </section>
      )}

      <ComputeContention />
    </div>
  );
});
