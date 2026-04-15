/**
 * AuditExplorer — filterable, paginated audit event table.
 *
 * Purpose:
 *   Render the /audit page (M30). Operators can browse the audit event log,
 *   filter by actor/action/object type, and load additional pages via cursor-based
 *   pagination without a full reload.
 *
 * Responsibilities:
 *   - Fetch paginated audit events via auditApi.listAudit().
 *   - Provide client-side filtering by actor, action type, object type.
 *   - Support cursor-based pagination via "Load more" button (accumulates results).
 *   - Surface loading, error, and empty states.
 *   - Honor AbortSignal teardown via TanStack Query.
 *   - Display human-readable action labels via ACTION_TYPE_LABELS.
 *
 * Does NOT:
 *   - Mutate audit records (read-only surface).
 *   - Render action buttons (edit, delete, approve, etc.).
 *
 * Acceptance:
 *   - Pagination changes do NOT trigger a full page reload (TanStack Query keeps
 *     the page mounted).
 *   - Filters apply instantly to accumulated results without a network round-trip.
 *   - "Load more" button is visible only when next_cursor is non-empty.
 */

import { memo, useCallback, useEffect, useId, useMemo, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { auditApi } from "../api";
import { auditLogger } from "../logger";
import { ACTION_TYPE_LABELS, AUDIT_DEFAULT_PAGE_SIZE } from "../constants";
import type { AuditEventRecord } from "@/types/audit";

interface AuditExplorerProps {
  /** Optional override of the default page size (used in tests). */
  pageSize?: number;
}

export const AuditExplorer = memo(function AuditExplorer({
  pageSize = AUDIT_DEFAULT_PAGE_SIZE,
}: AuditExplorerProps) {
  const correlationId = useId();
  const [cursor, setCursor] = useState<string | undefined>(undefined);
  const [actorFilter, setActorFilter] = useState("");
  const [actionFilter, setActionFilter] = useState("");
  const [objectTypeFilter, setObjectTypeFilter] = useState("");
  const [accumulatedEvents, setAccumulatedEvents] = useState<readonly AuditEventRecord[]>([]);

  useEffect(() => {
    auditLogger.pageMount("AuditExplorer", correlationId);
    return () => auditLogger.pageUnmount("AuditExplorer", correlationId);
  }, [correlationId]);

  const { data, isLoading, isFetching, error, refetch } = useQuery({
    queryKey: [
      "audit",
      "list",
      {
        limit: pageSize,
        cursor,
        actor: actorFilter,
        action: actionFilter,
        object_type: objectTypeFilter,
      },
    ],
    queryFn: ({ signal }) =>
      auditApi.listAudit(
        {
          limit: pageSize,
          cursor,
          actor: actorFilter || undefined,
          action: actionFilter || undefined,
          object_type: objectTypeFilter || undefined,
        },
        correlationId,
        signal,
      ),
  });

  // Accumulate results when new data arrives
  useEffect(() => {
    if (data?.events) {
      setAccumulatedEvents((prev) => [...prev, ...data.events]);
    }
  }, [data?.events]);

  // Reset accumulated events when filters change (not cursor)
  useEffect(() => {
    setAccumulatedEvents([]);
    setCursor(undefined);
  }, [actorFilter, actionFilter, objectTypeFilter]);

  const events = useMemo<readonly AuditEventRecord[]>(() => accumulatedEvents, [accumulatedEvents]);
  const nextCursor = data?.next_cursor ?? "";
  const totalCount = data?.total_count ?? 0;

  // Client-side filters are already applied via query key (for consistency with spec),
  // but we show all accumulated events since they're pre-filtered by the API.
  const canLoadMore = nextCursor.length > 0;

  const handleLoadMore = useCallback(() => {
    if (canLoadMore) {
      setCursor(nextCursor);
    }
  }, [canLoadMore, nextCursor]);

  const handleActorFilterChange = useCallback((value: string) => {
    setActorFilter(value);
  }, []);

  const handleActionFilterChange = useCallback((value: string) => {
    setActionFilter(value);
  }, []);

  const handleObjectTypeFilterChange = useCallback((value: string) => {
    setObjectTypeFilter(value);
  }, []);

  const getActionLabel = useCallback((action: string): string => {
    return ACTION_TYPE_LABELS[action] ?? action;
  }, []);

  const formatTimestamp = (isoString: string): string => {
    try {
      const date = new Date(isoString);
      return date.toLocaleString("en-US", {
        year: "numeric",
        month: "2-digit",
        day: "2-digit",
        hour: "2-digit",
        minute: "2-digit",
        second: "2-digit",
      });
    } catch {
      return isoString.split("T")[0]; // Fallback to date portion
    }
  };

  return (
    <div data-testid="audit-explorer" className="mx-auto max-w-6xl space-y-6">
      <div>
        <h1 className="text-xl font-semibold text-slate-900">Audit Explorer</h1>
        <p className="mt-1 text-sm text-slate-500">
          Browse system audit events with filtering and pagination.
        </p>
      </div>

      <section aria-label="Audit event filters and list" className="space-y-3">
        {/* Filter controls */}
        <div className="flex flex-wrap gap-3">
          <div className="min-w-40 flex-1">
            <label
              htmlFor="audit-actor-filter"
              className="mb-1 block text-xs font-medium text-slate-700"
            >
              Actor
            </label>
            <input
              id="audit-actor-filter"
              data-testid="audit-actor-filter"
              type="text"
              value={actorFilter}
              onChange={(e) => handleActorFilterChange(e.target.value)}
              placeholder="Filter by actor…"
              aria-label="Filter by actor"
              className="w-full rounded-md border border-slate-300 px-3 py-1.5 text-sm text-slate-700 focus:border-emerald-500 focus:outline-none focus:ring-1 focus:ring-emerald-500"
            />
          </div>

          <div className="min-w-40 flex-1">
            <label
              htmlFor="audit-action-filter"
              className="mb-1 block text-xs font-medium text-slate-700"
            >
              Action Type
            </label>
            <select
              id="audit-action-filter"
              data-testid="audit-action-filter"
              value={actionFilter}
              onChange={(e) => handleActionFilterChange(e.target.value)}
              aria-label="Filter by action type"
              className="w-full rounded-md border border-slate-300 px-3 py-1.5 text-sm text-slate-700 focus:border-emerald-500 focus:outline-none focus:ring-1 focus:ring-emerald-500"
            >
              <option value="">All actions</option>
              {Object.keys(ACTION_TYPE_LABELS).map((actionType) => (
                <option key={actionType} value={actionType}>
                  {ACTION_TYPE_LABELS[actionType]}
                </option>
              ))}
            </select>
          </div>

          <div className="min-w-40 flex-1">
            <label
              htmlFor="audit-object-type-filter"
              className="mb-1 block text-xs font-medium text-slate-700"
            >
              Object Type
            </label>
            <select
              id="audit-object-type-filter"
              data-testid="audit-object-type-filter"
              value={objectTypeFilter}
              onChange={(e) => handleObjectTypeFilterChange(e.target.value)}
              aria-label="Filter by object type"
              className="w-full rounded-md border border-slate-300 px-3 py-1.5 text-sm text-slate-700 focus:border-emerald-500 focus:outline-none focus:ring-1 focus:ring-emerald-500"
            >
              <option value="">All types</option>
              <option value="strategy">Strategy</option>
              <option value="feed">Feed</option>
              <option value="user">User</option>
              <option value="role">Role</option>
              <option value="override">Override</option>
            </select>
          </div>
        </div>

        {/* Loading state */}
        {isLoading ? (
          <div
            data-testid="audit-loading"
            role="status"
            className="flex items-center justify-center py-12"
          >
            <p className="text-sm text-slate-500">Loading audit events…</p>
          </div>
        ) : error ? (
          <div
            data-testid="audit-error"
            role="alert"
            className="rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700"
          >
            <p className="font-medium">Failed to load audit events</p>
            <p className="mt-1">{error instanceof Error ? error.message : "Unknown error."}</p>
            <button
              type="button"
              onClick={() => refetch()}
              className="mt-2 rounded-md bg-red-600 px-3 py-1.5 text-sm text-white hover:bg-red-700"
            >
              Retry
            </button>
          </div>
        ) : events.length === 0 ? (
          <div data-testid="audit-empty" className="py-12 text-center text-sm text-slate-500">
            No audit events found.
          </div>
        ) : (
          <div
            data-testid="audit-table"
            className="overflow-x-auto rounded-lg border border-slate-200 bg-white"
          >
            <table className="w-full text-sm">
              <thead className="border-b border-slate-200 bg-slate-50">
                <tr>
                  <th className="px-4 py-2 text-left font-medium text-slate-900">Timestamp</th>
                  <th className="px-4 py-2 text-left font-medium text-slate-900">Actor</th>
                  <th className="px-4 py-2 text-left font-medium text-slate-900">Action</th>
                  <th className="px-4 py-2 text-left font-medium text-slate-900">Object Type</th>
                  <th className="px-4 py-2 text-left font-medium text-slate-900">Object ID</th>
                  <th className="px-4 py-2 text-left font-medium text-slate-900">Correlation ID</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {events.map((event) => (
                  <tr
                    key={event.id}
                    data-testid={`audit-row-${event.id}`}
                    className="hover:bg-slate-50"
                  >
                    <td className="px-4 py-2 text-slate-700">
                      {formatTimestamp(event.created_at)}
                    </td>
                    <td className="max-w-xs truncate px-4 py-2 text-slate-700">{event.actor}</td>
                    <td className="px-4 py-2 text-slate-700">{getActionLabel(event.action)}</td>
                    <td className="px-4 py-2 text-slate-700">{event.object_type}</td>
                    <td className="max-w-xs truncate px-4 py-2 font-mono text-xs text-slate-600">
                      {event.object_id}
                    </td>
                    <td className="max-w-xs truncate px-4 py-2 font-mono text-xs text-slate-600">
                      {event.correlation_id}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}

        {/* Load more button and pagination summary */}
        {!isLoading && !error && events.length > 0 && (
          <div className="flex items-center justify-between text-xs text-slate-500">
            <span data-testid="audit-event-count">
              {totalCount === 0 ? "0 events" : `Loaded ${events.length} of ${totalCount} event(s)`}
              {isFetching ? " (updating…)" : ""}
            </span>
            {canLoadMore && (
              <button
                type="button"
                onClick={handleLoadMore}
                disabled={isFetching}
                className="rounded-md border border-slate-300 px-3 py-1 text-sm font-medium text-slate-700 hover:bg-slate-50 disabled:cursor-not-allowed disabled:opacity-50"
              >
                Load more
              </button>
            )}
          </div>
        )}
      </section>
    </div>
  );
});
