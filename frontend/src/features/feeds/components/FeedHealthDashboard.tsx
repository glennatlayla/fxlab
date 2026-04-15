/**
 * FeedHealthDashboard — operator overview of feed health across the platform.
 *
 * Purpose:
 *   Render the canonical feed-health summary at the top of the Feeds page.
 *   Consumes GET /feed-health (the authoritative source of truth — local
 *   computation of health state is forbidden by the M30 spec) and surfaces
 *   per-status counts plus a non-suppressible degraded badge.
 *
 * Responsibilities:
 *   - Fetch feed health via feedsApi.listFeedHealth().
 *   - Show summary cards for healthy / degraded / quarantined / offline counts.
 *   - List individual degraded or quarantined feeds with their badge.
 *   - Render loading, error, and empty states.
 *   - Honor AbortSignal teardown via TanStack Query.
 *
 * Does NOT:
 *   - Compute derived health state from raw feed data (M30 acceptance rule).
 *   - Allow operators to suppress the degraded badge (M30 acceptance rule).
 *   - Mutate feed configuration.
 */

import { memo, useEffect, useId, useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import { feedsApi } from "../api";
import { feedsLogger } from "../logger";
import { FEED_HEALTH_BADGE_CLASSES, FEED_HEALTH_LABELS } from "../constants";
import type { FeedHealthReport, FeedHealthStatus } from "@/types/feeds";

const ALL_STATUSES: readonly FeedHealthStatus[] = ["healthy", "degraded", "quarantined", "offline"];

interface CountsByStatus {
  healthy: number;
  degraded: number;
  quarantined: number;
  offline: number;
}

function summarize(reports: readonly FeedHealthReport[]): CountsByStatus {
  const counts: CountsByStatus = { healthy: 0, degraded: 0, quarantined: 0, offline: 0 };
  for (const report of reports) {
    counts[report.status] += 1;
  }
  return counts;
}

/** Operator dashboard for live feed health. */
export const FeedHealthDashboard = memo(function FeedHealthDashboard() {
  const correlationId = useId();

  useEffect(() => {
    feedsLogger.pageMount("FeedHealthDashboard", correlationId);
    return () => feedsLogger.pageUnmount("FeedHealthDashboard", correlationId);
  }, [correlationId]);

  const { data, isLoading, error, refetch } = useQuery({
    queryKey: ["feeds", "health"],
    queryFn: ({ signal }) => feedsApi.listFeedHealth(correlationId, signal),
  });

  const reports = useMemo(() => data?.feeds ?? [], [data]);
  const counts = useMemo(() => summarize(reports), [reports]);
  const attentionFeeds = useMemo(
    () => reports.filter((r) => r.status === "degraded" || r.status === "quarantined"),
    [reports],
  );

  if (isLoading) {
    return (
      <div
        data-testid="feed-health-loading"
        role="status"
        className="flex items-center justify-center py-8"
      >
        <p className="text-sm text-slate-500">Loading feed health…</p>
      </div>
    );
  }

  if (error) {
    return (
      <div
        data-testid="feed-health-error"
        role="alert"
        className="rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700"
      >
        <p className="font-medium">Failed to load feed health</p>
        <p className="mt-1">{error instanceof Error ? error.message : "Unknown error."}</p>
        <button
          type="button"
          onClick={() => refetch()}
          className="mt-2 rounded-md bg-red-600 px-3 py-1.5 text-sm text-white hover:bg-red-700"
        >
          Retry
        </button>
      </div>
    );
  }

  return (
    <section data-testid="feed-health-dashboard" className="space-y-4" aria-label="Feed health">
      <div className="grid grid-cols-2 gap-3 md:grid-cols-4">
        {ALL_STATUSES.map((status) => (
          <div
            key={status}
            data-testid={`feed-health-summary-${status}`}
            className="rounded-lg border border-slate-200 bg-white p-4 shadow-sm"
          >
            <p className="text-xs font-medium uppercase tracking-wide text-slate-500">
              {FEED_HEALTH_LABELS[status]}
            </p>
            <p className="mt-1 text-2xl font-semibold text-slate-900">{counts[status]}</p>
          </div>
        ))}
      </div>

      {attentionFeeds.length > 0 ? (
        <div data-testid="feed-health-attention" className="space-y-2">
          <h3 className="text-sm font-semibold text-slate-700">Feeds needing attention</h3>
          <ul className="divide-y divide-slate-100 rounded-lg border border-slate-200 bg-white">
            {attentionFeeds.map((report) => (
              <li
                key={report.feed_id}
                data-testid={`feed-health-row-${report.feed_id}`}
                className="flex items-center justify-between px-4 py-2 text-sm"
              >
                <span className="font-mono text-slate-700">{report.feed_id}</span>
                <span
                  data-testid={`feed-health-badge-${report.feed_id}`}
                  className={`inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium ring-1 ring-inset ${FEED_HEALTH_BADGE_CLASSES[report.status]}`}
                >
                  {FEED_HEALTH_LABELS[report.status]}
                </span>
              </li>
            ))}
          </ul>
        </div>
      ) : (
        <p data-testid="feed-health-empty" className="text-sm text-slate-500">
          All feeds are healthy.
        </p>
      )}
    </section>
  );
});
