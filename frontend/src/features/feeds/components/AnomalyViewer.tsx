/**
 * AnomalyViewer — filterable anomaly event table across all feeds.
 *
 * Purpose:
 *   Render a unified table of anomaly events sourced from the feed health
 *   report (GET /feed-health). Flattens all per-feed recent_anomalies into
 *   a single sortable, filterable list. Part of M30 Feed Operations.
 *
 * Responsibilities:
 *   - Fetch the feed health report via feedsApi.listFeedHealth().
 *   - Flatten anomalies from all feed health reports into a single list.
 *   - Provide severity filter (all / high / medium / low).
 *   - Render loading, error, and empty states.
 *   - Display anomaly type using human-readable labels from constants.
 *
 * Does NOT:
 *   - Mutate anomaly records — read-only surface.
 *   - Compute health state locally — consumes the health report verbatim.
 *
 * Dependencies:
 *   - feedsApi.listFeedHealth (from ../api).
 *   - ANOMALY_TYPE_LABELS (from ../constants).
 *   - TanStack Query for data fetching.
 */

import { memo, useEffect, useId, useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { feedsApi } from "../api";
import { feedsLogger } from "../logger";
import { ANOMALY_TYPE_LABELS } from "../constants";
import type { Anomaly } from "@/types/feeds";

/** Severity filter options. */
const SEVERITY_OPTIONS = [
  { value: "all", label: "All severities" },
  { value: "high", label: "High" },
  { value: "medium", label: "Medium" },
  { value: "low", label: "Low" },
] as const;

export const AnomalyViewer = memo(function AnomalyViewer() {
  const correlationId = useId();
  const [severityFilter, setSeverityFilter] = useState<string>("all");

  useEffect(() => {
    feedsLogger.pageMount("AnomalyViewer", correlationId);
    return () => feedsLogger.pageUnmount("AnomalyViewer", correlationId);
  }, [correlationId]);

  const healthQuery = useQuery({
    queryKey: ["feeds", "health"],
    queryFn: ({ signal }) => feedsApi.listFeedHealth(correlationId, signal),
  });

  // Flatten all anomalies from every feed health report into a single list.
  const allAnomalies = useMemo<readonly Anomaly[]>(() => {
    if (!healthQuery.data) return [];
    return healthQuery.data.feeds.flatMap((report) => report.recent_anomalies);
  }, [healthQuery.data]);

  // Apply severity filter.
  const filtered = useMemo(() => {
    if (severityFilter === "all") return allAnomalies;
    return allAnomalies.filter((a) => a.severity === severityFilter);
  }, [allAnomalies, severityFilter]);

  if (healthQuery.isLoading) {
    return (
      <div
        data-testid="anomaly-viewer-loading"
        role="status"
        className="flex items-center justify-center py-12"
      >
        <p className="text-sm text-slate-500">Loading anomalies…</p>
      </div>
    );
  }

  if (healthQuery.error) {
    return (
      <div
        data-testid="anomaly-viewer-error"
        role="alert"
        className="rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700"
      >
        <p className="font-medium">Failed to load anomalies</p>
        <p className="mt-1">
          {healthQuery.error instanceof Error ? healthQuery.error.message : "Unknown error."}
        </p>
        <button
          type="button"
          onClick={() => healthQuery.refetch()}
          className="mt-2 rounded-md bg-red-600 px-3 py-1.5 text-sm text-white hover:bg-red-700"
        >
          Retry
        </button>
      </div>
    );
  }

  if (allAnomalies.length === 0) {
    return (
      <div data-testid="anomaly-viewer-empty" className="py-12 text-center text-sm text-slate-500">
        No anomalies recorded across any feed.
      </div>
    );
  }

  return (
    <div data-testid="anomaly-viewer" className="space-y-3">
      <div className="flex items-center justify-between gap-3">
        <h2 className="text-sm font-semibold text-slate-700">Anomalies ({filtered.length})</h2>
        <select
          data-testid="anomaly-severity-filter"
          value={severityFilter}
          onChange={(e) => setSeverityFilter(e.target.value)}
          aria-label="Filter by severity"
          className="rounded-md border border-slate-300 px-3 py-1.5 text-sm text-slate-700 focus:border-emerald-500 focus:outline-none focus:ring-1 focus:ring-emerald-500"
        >
          {SEVERITY_OPTIONS.map((opt) => (
            <option key={opt.value} value={opt.value}>
              {opt.label}
            </option>
          ))}
        </select>
      </div>

      {filtered.length === 0 ? (
        <p className="py-6 text-center text-xs text-slate-500">
          No anomalies match the selected severity.
        </p>
      ) : (
        <table data-testid="anomaly-viewer-table" className="w-full text-left text-sm">
          <thead>
            <tr className="border-b border-slate-200 text-xs font-medium uppercase text-slate-500">
              <th className="px-3 py-2">Type</th>
              <th className="px-3 py-2">Severity</th>
              <th className="px-3 py-2">Feed</th>
              <th className="px-3 py-2">Message</th>
              <th className="px-3 py-2">Detected</th>
            </tr>
          </thead>
          <tbody className="divide-y divide-slate-100">
            {filtered.map((anomaly) => (
              <tr
                key={anomaly.id}
                data-testid={`anomaly-row-${anomaly.id}`}
                className="hover:bg-slate-50"
              >
                <td className="whitespace-nowrap px-3 py-2 font-medium text-slate-900">
                  {ANOMALY_TYPE_LABELS[anomaly.anomaly_type]}
                </td>
                <td className="whitespace-nowrap px-3 py-2 text-xs uppercase text-slate-600">
                  {anomaly.severity}
                </td>
                <td className="whitespace-nowrap px-3 py-2 font-mono text-xs text-slate-500">
                  {anomaly.feed_id}
                </td>
                <td className="px-3 py-2 text-slate-700">{anomaly.message}</td>
                <td className="whitespace-nowrap px-3 py-2 text-xs text-slate-500">
                  {anomaly.detected_at}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      )}
    </div>
  );
});
