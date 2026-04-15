/**
 * FeedDetailPage — full detail view for a single registered feed.
 *
 * Purpose:
 *   Render the /feeds/:feedId route. Surfaces the feed metadata header,
 *   the recent connectivity test timeline, the configuration version
 *   history, and the recent anomalies for this feed (read from the
 *   authoritative health report).
 *
 * Responsibilities:
 *   - Fetch feed detail via feedsApi.getFeed().
 *   - Cross-fetch feed health to surface anomalies + status badge for the feed.
 *   - Render loading, error (incl. 404), and empty states.
 *   - Honor AbortSignal teardown via TanStack Query.
 *
 * Does NOT:
 *   - Mutate feed configuration.
 *   - Compute health state locally — consumes the health report verbatim.
 */

import { memo, useEffect, useId, useMemo } from "react";
import { useQuery } from "@tanstack/react-query";
import { feedsApi } from "../api";
import { feedsLogger } from "../logger";
import { FeedsNotFoundError } from "../errors";
import {
  FEED_HEALTH_BADGE_CLASSES,
  FEED_HEALTH_LABELS,
  CONNECTIVITY_STATUS_CLASSES,
  CONNECTIVITY_STATUS_LABELS,
  ANOMALY_TYPE_LABELS,
} from "../constants";
import type { FeedHealthReport } from "@/types/feeds";

interface FeedDetailPageProps {
  /** Feed ULID to render. */
  feedId: string;
}

export const FeedDetailPage = memo(function FeedDetailPage({ feedId }: FeedDetailPageProps) {
  const correlationId = useId();

  useEffect(() => {
    feedsLogger.pageMount("FeedDetailPage", correlationId);
    return () => feedsLogger.pageUnmount("FeedDetailPage", correlationId);
  }, [correlationId]);

  const detailQuery = useQuery({
    queryKey: ["feeds", "detail", feedId],
    queryFn: ({ signal }) => feedsApi.getFeed(feedId, correlationId, signal),
  });

  const healthQuery = useQuery({
    queryKey: ["feeds", "health"],
    queryFn: ({ signal }) => feedsApi.listFeedHealth(correlationId, signal),
  });

  const detail = detailQuery.data;
  const healthReport = useMemo<FeedHealthReport | undefined>(
    () => healthQuery.data?.feeds.find((r) => r.feed_id === feedId),
    [healthQuery.data, feedId],
  );

  if (detailQuery.isLoading) {
    return (
      <div
        data-testid="feed-detail-loading"
        role="status"
        className="flex items-center justify-center py-12"
      >
        <p className="text-sm text-slate-500">Loading feed…</p>
      </div>
    );
  }

  if (detailQuery.error) {
    const isNotFound = detailQuery.error instanceof FeedsNotFoundError;
    return (
      <div
        data-testid={isNotFound ? "feed-detail-not-found" : "feed-detail-error"}
        role="alert"
        className="rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700"
      >
        <p className="font-medium">{isNotFound ? "Feed not found" : "Failed to load feed"}</p>
        <p className="mt-1">
          {detailQuery.error instanceof Error ? detailQuery.error.message : "Unknown error."}
        </p>
        {!isNotFound && (
          <button
            type="button"
            onClick={() => detailQuery.refetch()}
            className="mt-2 rounded-md bg-red-600 px-3 py-1.5 text-sm text-white hover:bg-red-700"
          >
            Retry
          </button>
        )}
      </div>
    );
  }

  if (!detail) {
    return (
      <div data-testid="feed-detail-empty" className="py-12 text-center text-sm text-slate-500">
        No feed data.
      </div>
    );
  }

  const { feed, version_history, connectivity_tests } = detail;

  return (
    <article data-testid="feed-detail-page" className="mx-auto max-w-4xl space-y-6">
      <header className="space-y-2">
        <div className="flex items-center justify-between gap-3">
          <h1 className="text-xl font-semibold text-slate-900">{feed.name}</h1>
          {healthReport && (
            <span
              data-testid={`feed-detail-health-badge-${feed.id}`}
              className={`inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium ring-1 ring-inset ${FEED_HEALTH_BADGE_CLASSES[healthReport.status]}`}
            >
              {FEED_HEALTH_LABELS[healthReport.status]}
            </span>
          )}
        </div>
        <p className="text-sm text-slate-500">
          {feed.provider} · {feed.is_active ? "active" : "inactive"}
          {feed.is_quarantined ? " · quarantined" : ""}
        </p>
        <code data-testid="feed-detail-id" className="block font-mono text-xs text-slate-400">
          {feed.id}
        </code>
      </header>

      <section aria-label="Configuration version history" className="space-y-2">
        <h2 className="text-sm font-semibold text-slate-700">Configuration history</h2>
        {version_history.length === 0 ? (
          <p data-testid="feed-detail-versions-empty" className="text-xs text-slate-500">
            No version history recorded.
          </p>
        ) : (
          <ul
            data-testid="feed-detail-versions"
            className="divide-y divide-slate-100 rounded-lg border border-slate-200 bg-white"
          >
            {version_history.map((v) => (
              <li
                key={v.version}
                data-testid={`feed-detail-version-${v.version}`}
                className="px-4 py-2 text-sm"
              >
                <div className="flex items-center justify-between">
                  <span className="font-medium text-slate-900">v{v.version}</span>
                  <time className="text-xs text-slate-500">{v.created_at}</time>
                </div>
                {v.change_summary && (
                  <p className="mt-0.5 text-xs text-slate-600">{v.change_summary}</p>
                )}
              </li>
            ))}
          </ul>
        )}
      </section>

      <section aria-label="Recent connectivity tests" className="space-y-2">
        <h2 className="text-sm font-semibold text-slate-700">Recent connectivity tests</h2>
        {connectivity_tests.length === 0 ? (
          <p data-testid="feed-detail-connectivity-empty" className="text-xs text-slate-500">
            No connectivity tests recorded.
          </p>
        ) : (
          <ul
            data-testid="feed-detail-connectivity"
            className="divide-y divide-slate-100 rounded-lg border border-slate-200 bg-white"
          >
            {connectivity_tests.map((test) => (
              <li
                key={test.id}
                data-testid={`feed-detail-connectivity-${test.id}`}
                className="flex items-center justify-between px-4 py-2 text-sm"
              >
                <div>
                  <span
                    className={`inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium ring-1 ring-inset ${CONNECTIVITY_STATUS_CLASSES[test.status]}`}
                  >
                    {CONNECTIVITY_STATUS_LABELS[test.status]}
                  </span>
                  {test.latency_ms != null && (
                    <span className="ml-2 text-xs text-slate-500">{test.latency_ms} ms</span>
                  )}
                  {test.error_message && (
                    <span className="ml-2 text-xs text-red-600">{test.error_message}</span>
                  )}
                </div>
                <time className="text-xs text-slate-500">{test.tested_at}</time>
              </li>
            ))}
          </ul>
        )}
      </section>

      <section aria-label="Recent anomalies" className="space-y-2">
        <h2 className="text-sm font-semibold text-slate-700">Recent anomalies</h2>
        {!healthReport || healthReport.recent_anomalies.length === 0 ? (
          <p data-testid="feed-detail-anomalies-empty" className="text-xs text-slate-500">
            No anomalies recorded.
          </p>
        ) : (
          <ul
            data-testid="feed-detail-anomalies"
            className="divide-y divide-slate-100 rounded-lg border border-slate-200 bg-white"
          >
            {healthReport.recent_anomalies.map((a) => (
              <li
                key={a.id}
                data-testid={`feed-detail-anomaly-${a.id}`}
                className="px-4 py-2 text-sm"
              >
                <div className="flex items-center justify-between">
                  <span className="font-medium text-slate-900">
                    {ANOMALY_TYPE_LABELS[a.anomaly_type]}
                  </span>
                  <span className="text-xs uppercase text-slate-500">{a.severity}</span>
                </div>
                <p className="mt-0.5 text-xs text-slate-600">{a.message}</p>
                <time className="mt-0.5 block text-xs text-slate-400">{a.detected_at}</time>
              </li>
            ))}
          </ul>
        )}
      </section>
    </article>
  );
});
