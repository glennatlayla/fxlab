/**
 * ParityPage — paginated registry of parity events with filtering and summary.
 *
 * Purpose:
 *   Render the /parity page (M30). Operators can browse parity mismatches
 *   detected between official and shadow feeds, filter by severity, and view
 *   instrument-level summaries at a glance.
 *
 * Responsibilities:
 *   - Fetch parity events via parityApi.listEvents().
 *   - Fetch parity summary via parityApi.getSummary().
 *   - Provide client-side severity filter (All / INFO / WARNING / CRITICAL).
 *   - Render summary cards per instrument showing event counts and worst severity.
 *   - Render event table with columns: Instrument, Official Feed, Shadow Feed, Delta, Delta %, Severity, Detected At.
 *   - Surface loading, error, and empty states.
 *   - Honor AbortSignal teardown via TanStack Query.
 *
 * Does NOT:
 *   - Mutate parity events (read-only surface in M30).
 *   - Compute derived summary state — fetches from backend.
 *
 * Acceptance:
 *   - Summary section renders above event table.
 *   - Severity filter is client-side (applies to fetched events instantly).
 *   - Severity badges use PARITY_SEVERITY_BADGE_CLASSES (INFO=blue, WARNING=amber, CRITICAL=red).
 *   - CRITICAL badge is visibly red, not neutral.
 */

import { memo, useEffect, useId, useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { parityApi } from "../api";
import { parityLogger } from "../logger";
import {
  PARITY_SEVERITY_BADGE_CLASSES,
  PARITY_SEVERITY_LABELS,
  PARITY_DEFAULT_PAGE_SIZE,
} from "../constants";
import type { ParityEvent, ParityEventSeverity, ParityInstrumentSummary } from "@/types/parity";

interface ParityPageProps {
  /** Optional override of the default page size (used in tests). */
  pageSize?: number;
}

export const ParityPage = memo(function ParityPage({
  pageSize = PARITY_DEFAULT_PAGE_SIZE,
}: ParityPageProps) {
  const correlationId = useId();
  const [severityFilter, setSeverityFilter] = useState<"All" | ParityEventSeverity>("All");

  useEffect(() => {
    parityLogger.pageMount("ParityPage", correlationId);
    return () => parityLogger.pageUnmount("ParityPage", correlationId);
  }, [correlationId]);

  const {
    data: eventsData,
    isLoading: eventsLoading,
    error: eventsError,
    refetch: refetchEvents,
  } = useQuery({
    queryKey: ["parity", "events", { limit: pageSize }],
    queryFn: ({ signal }) => parityApi.listEvents({ limit: pageSize }, correlationId, signal),
  });

  const { data: summaryData, isLoading: summaryLoading } = useQuery({
    queryKey: ["parity", "summary"],
    queryFn: ({ signal }) => parityApi.getSummary(correlationId, signal),
  });

  const events = useMemo<readonly ParityEvent[]>(() => eventsData?.events ?? [], [eventsData]);
  const summaries = useMemo<readonly ParityInstrumentSummary[]>(
    () => summaryData?.summaries ?? [],
    [summaryData],
  );

  // Client-side severity filtering
  const filtered = useMemo(() => {
    if (severityFilter === "All") return events;
    return events.filter((e) => e.severity === severityFilter);
  }, [events, severityFilter]);

  const isLoading = eventsLoading || summaryLoading;

  return (
    <div data-testid="parity-page" className="mx-auto max-w-6xl space-y-6">
      {/* Page header */}
      <div>
        <h1 className="text-xl font-semibold text-slate-900">Parity Monitoring</h1>
        <p className="mt-1 text-sm text-slate-500">
          Monitor data feed parity mismatches between official and shadow sources.
        </p>
      </div>

      {/* Summary section */}
      {!isLoading && (
        <section
          data-testid="parity-summary-section"
          aria-label="Parity summary by instrument"
          className="space-y-3"
        >
          <h2 className="text-base font-semibold text-slate-800">Instruments</h2>
          {summaries.length === 0 ? (
            <p className="text-sm text-slate-500">No parity data available.</p>
          ) : (
            <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
              {summaries.map((summary) => (
                <div
                  key={summary.instrument}
                  data-testid={`parity-summary-${summary.instrument.toLowerCase()}`}
                  className="space-y-2 rounded-lg border border-slate-200 bg-white px-4 py-3"
                >
                  <h3 className="text-sm font-semibold text-slate-900">{summary.instrument}</h3>
                  <p className="text-xs text-slate-600">
                    {summary.event_count} {summary.event_count === 1 ? "event" : "events"}
                  </p>
                  {summary.worst_severity && (
                    <div
                      className={`inline-flex items-center rounded-full px-2.5 py-1 text-xs font-medium ring-1 ring-inset ${
                        PARITY_SEVERITY_BADGE_CLASSES[
                          summary.worst_severity as ParityEventSeverity
                        ] ?? "bg-slate-100 text-slate-800 ring-slate-600/20"
                      }`}
                    >
                      {PARITY_SEVERITY_LABELS[summary.worst_severity as ParityEventSeverity] ??
                        summary.worst_severity}
                    </div>
                  )}
                </div>
              ))}
            </div>
          )}
        </section>
      )}

      {/* Events section */}
      <section aria-label="Parity events" className="space-y-3">
        <div className="flex items-center justify-between gap-3">
          <h2 className="text-base font-semibold text-slate-800">Events</h2>
          <select
            data-testid="parity-severity-filter"
            value={severityFilter}
            onChange={(e) => setSeverityFilter(e.target.value as "All" | ParityEventSeverity)}
            aria-label="Filter by severity"
            className="w-48 rounded-md border border-slate-300 px-3 py-1.5 text-sm text-slate-700 focus:border-emerald-500 focus:outline-none focus:ring-1 focus:ring-emerald-500"
          >
            <option value="All">All</option>
            <option value="INFO">Info</option>
            <option value="WARNING">Warning</option>
            <option value="CRITICAL">Critical</option>
          </select>
        </div>

        {isLoading ? (
          <div
            data-testid="parity-loading"
            role="status"
            className="flex items-center justify-center py-12"
          >
            <p className="text-sm text-slate-500">Loading parity events…</p>
          </div>
        ) : eventsError ? (
          <div
            data-testid="parity-error"
            role="alert"
            className="rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700"
          >
            <p className="font-medium">Failed to load parity events</p>
            <p className="mt-1">
              {eventsError instanceof Error ? eventsError.message : "Unknown error."}
            </p>
            <button
              type="button"
              onClick={() => refetchEvents()}
              className="mt-2 rounded-md bg-red-600 px-3 py-1.5 text-sm text-white hover:bg-red-700"
            >
              Retry
            </button>
          </div>
        ) : filtered.length === 0 ? (
          <div data-testid="parity-empty" className="py-12 text-center text-sm text-slate-500">
            {events.length === 0
              ? "No parity events detected."
              : "No events match the selected filter."}
          </div>
        ) : (
          <div
            data-testid="parity-events-table"
            className="overflow-x-auto rounded-lg border border-slate-200 bg-white"
          >
            <table className="w-full text-sm">
              <thead className="border-b border-slate-200 bg-slate-50">
                <tr>
                  <th className="px-4 py-3 text-left font-semibold text-slate-900">Instrument</th>
                  <th className="px-4 py-3 text-left font-semibold text-slate-900">
                    Official Feed
                  </th>
                  <th className="px-4 py-3 text-left font-semibold text-slate-900">Shadow Feed</th>
                  <th className="px-4 py-3 text-right font-semibold text-slate-900">Delta</th>
                  <th className="px-4 py-3 text-right font-semibold text-slate-900">Delta %</th>
                  <th className="px-4 py-3 text-left font-semibold text-slate-900">Severity</th>
                  <th className="px-4 py-3 text-left font-semibold text-slate-900">Detected At</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {filtered.map((event) => (
                  <tr
                    key={event.id}
                    data-testid={`parity-event-row-${event.id}`}
                    className="hover:bg-slate-50"
                  >
                    <td className="px-4 py-3 font-medium text-slate-900">{event.instrument}</td>
                    <td className="px-4 py-3 font-mono text-xs text-slate-600">
                      {event.feed_id_official}
                    </td>
                    <td className="px-4 py-3 font-mono text-xs text-slate-600">
                      {event.feed_id_shadow}
                    </td>
                    <td className="px-4 py-3 text-right text-slate-700">{event.delta}</td>
                    <td className="px-4 py-3 text-right text-slate-700">
                      {event.delta_pct.toFixed(2)}%
                    </td>
                    <td className="px-4 py-3">
                      <span
                        className={`inline-flex items-center rounded-full px-2.5 py-1 text-xs font-medium ring-1 ring-inset ${
                          PARITY_SEVERITY_BADGE_CLASSES[event.severity] ??
                          "bg-slate-100 text-slate-800 ring-slate-600/20"
                        }`}
                      >
                        {PARITY_SEVERITY_LABELS[event.severity] ?? event.severity}
                      </span>
                    </td>
                    <td className="px-4 py-3 text-xs text-slate-500">
                      {new Date(event.detected_at).toLocaleString()}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </div>
  );
});
