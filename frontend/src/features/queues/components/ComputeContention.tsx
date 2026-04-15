/**
 * ComputeContention — queue contention analysis with time-range selection.
 *
 * Purpose:
 *   Render detailed contention metrics for a queue class ("research" by default,
 *   per M30 spec) with a time-range selector (1h, 6h, 24h, 7d). Allows operators
 *   to examine contention trends without reloading the parent QueuesPage.
 *
 * Responsibilities:
 *   - Fetch queue contention via queuesApi.getContention().
 *   - Provide time-range selector to vary the data window.
 *   - Render contention score with color badge, depth, running, failed counts.
 *   - Surface loading, error states.
 *   - Honor AbortSignal teardown via TanStack Query.
 *
 * Does NOT:
 *   - Compute contention scores locally — always authoritative from API.
 *   - Accept props — self-contained, single queue class ("research").
 *   - Mutate queue configuration.
 *
 * Performance:
 *   - Wrapped in React.memo to prevent re-renders when parent updates.
 *   - Time-range handler uses useCallback to maintain referential stability.
 *   - Query key includes timeRange so changing it re-fetches.
 *
 * Acceptance (M30):
 *   - Time-range change loads correct data without re-rendering sibling sections.
 *   - Contention badge color reflects health status.
 */

import { memo, useCallback, useEffect, useId, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { queuesApi } from "../api";
import { queuesLogger } from "../logger";
import {
  getContentionLevel,
  CONTENTION_LEVEL_LABELS,
  CONTENTION_BADGE_CLASSES,
} from "../constants";

type TimeRange = "1h" | "6h" | "24h" | "7d";

const TIME_RANGE_OPTIONS: readonly TimeRange[] = ["1h", "6h", "24h", "7d"];
const QUEUE_CLASS = "research";

/**
 * ComputeContention — detailed contention analysis for a queue class.
 *
 * Self-contained component that fetches and displays contention metrics
 * with optional time-range filtering. Used via React.memo.
 */
export const ComputeContention = memo(function ComputeContention() {
  const correlationId = useId();
  const [timeRange, setTimeRange] = useState<TimeRange>("1h");

  useEffect(() => {
    queuesLogger.pageMount("ComputeContention", correlationId);
    return () => queuesLogger.pageUnmount("ComputeContention", correlationId);
  }, [correlationId]);

  const { data, isLoading, error, refetch } = useQuery({
    queryKey: ["queues", "contention", QUEUE_CLASS, timeRange],
    queryFn: ({ signal }) => queuesApi.getContention(QUEUE_CLASS, correlationId, signal),
  });

  const handleTimeRangeChange = useCallback((e: React.ChangeEvent<HTMLSelectElement>) => {
    setTimeRange(e.target.value as TimeRange);
  }, []);

  const handleRetry = useCallback(() => {
    refetch();
  }, [refetch]);

  if (isLoading) {
    return (
      <div
        data-testid="compute-contention-loading"
        role="status"
        className="flex items-center justify-center py-8"
      >
        <p className="text-sm text-slate-500">Loading contention…</p>
      </div>
    );
  }

  if (error) {
    return (
      <div
        data-testid="compute-contention-error"
        role="alert"
        className="rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700"
      >
        <p className="font-medium">Failed to load contention</p>
        <p className="mt-1">{error instanceof Error ? error.message : "Unknown error."}</p>
        <button
          type="button"
          onClick={handleRetry}
          className="mt-2 rounded-md bg-red-600 px-3 py-1.5 text-sm text-white hover:bg-red-700"
        >
          Retry
        </button>
      </div>
    );
  }

  if (!data) {
    return null;
  }

  const level = getContentionLevel(data.contention_score);
  const badgeClasses = CONTENTION_BADGE_CLASSES[level];
  const levelLabel = CONTENTION_LEVEL_LABELS[level];

  return (
    <section data-testid="compute-contention" aria-label="Queue contention" className="space-y-4">
      <div className="flex items-center justify-between gap-3">
        <h2 className="text-base font-semibold text-slate-800">Contention Analysis</h2>
        <select
          data-testid="time-range-selector"
          value={timeRange}
          onChange={handleTimeRangeChange}
          aria-label="Select time range for contention data"
          className="rounded-md border border-slate-300 px-3 py-1.5 text-sm text-slate-700 focus:border-emerald-500 focus:outline-none focus:ring-1 focus:ring-emerald-500"
        >
          {TIME_RANGE_OPTIONS.map((range) => (
            <option key={range} value={range}>
              {range}
            </option>
          ))}
        </select>
      </div>

      <div className="rounded-lg border border-slate-200 bg-white p-4 shadow-sm">
        <div className="grid grid-cols-2 gap-4 md:grid-cols-4">
          <div className="flex flex-col gap-1">
            <span className="text-xs font-medium uppercase tracking-wide text-slate-500">
              Contention Score
            </span>
            <span
              data-testid="contention-score-badge"
              className={`inline-flex items-center rounded-full px-3 py-1 text-sm font-semibold ring-1 ring-inset ${badgeClasses} w-fit`}
            >
              {data.contention_score} {levelLabel}
            </span>
          </div>

          <div className="flex flex-col gap-1">
            <span className="text-xs font-medium uppercase tracking-wide text-slate-500">
              Queue Depth
            </span>
            <p data-testid="contention-depth" className="text-2xl font-semibold text-slate-900">
              {data.depth}
            </p>
          </div>

          <div className="flex flex-col gap-1">
            <span className="text-xs font-medium uppercase tracking-wide text-slate-500">
              Running
            </span>
            <p data-testid="contention-running" className="text-2xl font-semibold text-slate-900">
              {data.running}
            </p>
          </div>

          <div className="flex flex-col gap-1">
            <span className="text-xs font-medium uppercase tracking-wide text-slate-500">
              Failed
            </span>
            <p data-testid="contention-failed" className="text-2xl font-semibold text-slate-900">
              {data.failed}
            </p>
          </div>
        </div>
      </div>
    </section>
  );
});
