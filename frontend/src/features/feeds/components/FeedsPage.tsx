/**
 * FeedsPage — paginated registry of all data feeds with name search.
 *
 * Purpose:
 *   Render the /feeds page (M30). Operators can browse the registry, search
 *   by feed name or provider, and page through results without a full reload.
 *   The FeedHealthDashboard is rendered above the list as the canonical
 *   health surface (per M30 acceptance criteria).
 *
 * Responsibilities:
 *   - Fetch a paginated feed list via feedsApi.listFeeds().
 *   - Provide client-side search across name + provider for the current page.
 *   - Provide Prev / Next pagination controls (cursor-style without full reload).
 *   - Surface loading, error, and empty states.
 *   - Honor AbortSignal teardown via TanStack Query.
 *
 * Does NOT:
 *   - Mutate feed configuration (read-only surface in M30).
 *   - Compute derived health state — delegates to FeedHealthDashboard.
 *
 * Acceptance:
 *   - Pagination changes do NOT trigger a full page reload (TanStack Query keeps
 *     the page mounted).
 *   - Search filters apply instantly without a network round-trip.
 */

import { memo, useCallback, useEffect, useId, useMemo, useState } from "react";
import { useQuery, keepPreviousData } from "@tanstack/react-query";
import { feedsApi } from "../api";
import { feedsLogger } from "../logger";
import { FEEDS_DEFAULT_PAGE_SIZE } from "../constants";
import type { FeedResponse } from "@/types/feeds";
import { FeedHealthDashboard } from "./FeedHealthDashboard";

interface FeedsPageProps {
  /** Optional override of the default page size (used in tests). */
  pageSize?: number;
}

export const FeedsPage = memo(function FeedsPage({
  pageSize = FEEDS_DEFAULT_PAGE_SIZE,
}: FeedsPageProps) {
  const correlationId = useId();
  const [offset, setOffset] = useState(0);
  const [search, setSearch] = useState("");

  useEffect(() => {
    feedsLogger.pageMount("FeedsPage", correlationId);
    return () => feedsLogger.pageUnmount("FeedsPage", correlationId);
  }, [correlationId]);

  const { data, isLoading, isFetching, error, refetch } = useQuery({
    queryKey: ["feeds", "list", { limit: pageSize, offset }],
    queryFn: ({ signal }) => feedsApi.listFeeds({ limit: pageSize, offset }, correlationId, signal),
    placeholderData: keepPreviousData,
  });

  const feeds = useMemo<readonly FeedResponse[]>(() => data?.feeds ?? [], [data]);
  const totalCount = data?.total_count ?? 0;

  const filtered = useMemo(() => {
    const needle = search.trim().toLowerCase();
    if (!needle) return feeds;
    return feeds.filter(
      (f) => f.name.toLowerCase().includes(needle) || f.provider.toLowerCase().includes(needle),
    );
  }, [feeds, search]);

  const handlePrev = useCallback(() => {
    setOffset((prev) => Math.max(0, prev - pageSize));
  }, [pageSize]);

  const handleNext = useCallback(() => {
    setOffset((prev) => {
      const next = prev + pageSize;
      return next < totalCount ? next : prev;
    });
  }, [pageSize, totalCount]);

  const canPrev = offset > 0;
  const canNext = offset + pageSize < totalCount;
  const pageStart = totalCount === 0 ? 0 : offset + 1;
  const pageEnd = Math.min(offset + pageSize, totalCount);

  return (
    <div data-testid="feeds-page" className="mx-auto max-w-5xl space-y-6">
      <div>
        <h1 className="text-xl font-semibold text-slate-900">Feed Operations</h1>
        <p className="mt-1 text-sm text-slate-500">
          Monitor data feed registry, health, and connectivity.
        </p>
      </div>

      <FeedHealthDashboard />

      <section aria-label="Feed registry" className="space-y-3">
        <div className="flex items-center justify-between gap-3">
          <h2 className="text-base font-semibold text-slate-800">Feed Registry</h2>
          <input
            data-testid="feeds-search-input"
            type="search"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Search by name or provider…"
            aria-label="Search feeds"
            className="w-64 rounded-md border border-slate-300 px-3 py-1.5 text-sm text-slate-700 focus:border-emerald-500 focus:outline-none focus:ring-1 focus:ring-emerald-500"
          />
        </div>

        {isLoading ? (
          <div
            data-testid="feeds-loading"
            role="status"
            className="flex items-center justify-center py-12"
          >
            <p className="text-sm text-slate-500">Loading feeds…</p>
          </div>
        ) : error ? (
          <div
            data-testid="feeds-error"
            role="alert"
            className="rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700"
          >
            <p className="font-medium">Failed to load feeds</p>
            <p className="mt-1">{error instanceof Error ? error.message : "Unknown error."}</p>
            <button
              type="button"
              onClick={() => refetch()}
              className="mt-2 rounded-md bg-red-600 px-3 py-1.5 text-sm text-white hover:bg-red-700"
            >
              Retry
            </button>
          </div>
        ) : filtered.length === 0 ? (
          <div data-testid="feeds-empty" className="py-12 text-center text-sm text-slate-500">
            {search ? "No feeds match your search." : "No feeds registered."}
          </div>
        ) : (
          <ul
            data-testid="feeds-list"
            className="divide-y divide-slate-100 rounded-lg border border-slate-200 bg-white"
          >
            {filtered.map((feed) => (
              <li
                key={feed.id}
                data-testid={`feeds-row-${feed.id}`}
                className="flex items-center justify-between px-4 py-3 text-sm"
              >
                <div className="min-w-0">
                  <p className="font-medium text-slate-900">{feed.name}</p>
                  <p className="mt-0.5 text-xs text-slate-500">
                    {feed.provider} · {feed.is_active ? "active" : "inactive"}
                    {feed.is_quarantined ? " · quarantined" : ""}
                  </p>
                </div>
                <code className="ml-3 truncate font-mono text-xs text-slate-500">{feed.id}</code>
              </li>
            ))}
          </ul>
        )}

        <div className="flex items-center justify-between text-xs text-slate-500">
          <span data-testid="feeds-page-summary">
            {totalCount === 0 ? "0 feeds" : `Showing ${pageStart}–${pageEnd} of ${totalCount}`}
            {isFetching ? " (updating…)" : ""}
          </span>
          <div className="flex gap-2">
            <button
              data-testid="feeds-prev-button"
              type="button"
              onClick={handlePrev}
              disabled={!canPrev}
              className="rounded-md border border-slate-300 px-3 py-1 text-sm font-medium text-slate-700 disabled:cursor-not-allowed disabled:opacity-50"
            >
              Previous
            </button>
            <button
              data-testid="feeds-next-button"
              type="button"
              onClick={handleNext}
              disabled={!canNext}
              className="rounded-md border border-slate-300 px-3 py-1 text-sm font-medium text-slate-700 disabled:cursor-not-allowed disabled:opacity-50"
            >
              Next
            </button>
          </div>
        </div>
      </section>
    </div>
  );
});
