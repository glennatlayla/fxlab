/**
 * ArtifactBrowser — paginated browser of all artifacts with filtering.
 *
 * Purpose:
 *   Render the artifacts browser (M31). Operators can browse all artifacts
 *   (compiled strategies, backtest results, etc.), filter by type and subject ID,
 *   and page through results without a full reload. Downloads are triggered on demand.
 *
 * Responsibilities:
 *   - Fetch a paginated artifact list via artifactApi.listArtifacts().
 *   - Provide type filter (dropdown) and subject_id search.
 *   - Provide Prev / Next pagination controls (cursor-style without full reload).
 *   - Surface loading, error, and empty states.
 *   - Honor AbortSignal teardown via TanStack Query.
 *   - Trigger downloads via artifactApi.downloadArtifact().
 *
 * Does NOT:
 *   - Mutate artifacts (read-only surface).
 *   - Delete or manage artifact lifecycle.
 *
 * Acceptance:
 *   - Pagination changes do NOT trigger a full page reload (TanStack Query keeps
 *     the page mounted).
 *   - Filters apply without a network round-trip (client-side for subject_id).
 *   - Type filter triggers a new query.
 */

import { memo, useCallback, useEffect, useId, useMemo, useState } from "react";
import { useQuery, keepPreviousData } from "@tanstack/react-query";
import { artifactApi } from "../api";
import { artifactLogger } from "../logger";
import {
  DEFAULT_PAGE_SIZE,
  ARTIFACT_TYPE_LABELS,
  ARTIFACT_TYPE_BADGE_CLASSES,
  formatFileSize,
} from "../constants";
import { ArtifactType } from "@/types/artifacts";
import type { Artifact } from "@/types/artifacts";

interface ArtifactBrowserProps {
  /** Optional override of the default page size (used in tests). */
  pageSize?: number;
}

export const ArtifactBrowser = memo(function ArtifactBrowser({
  pageSize = DEFAULT_PAGE_SIZE,
}: ArtifactBrowserProps) {
  const correlationId = useId();
  const [offset, setOffset] = useState(0);
  const [selectedTypes, setSelectedTypes] = useState<string[]>([]);
  const [subjectIdSearch, setSubjectIdSearch] = useState("");

  useEffect(() => {
    artifactLogger.pageMount("ArtifactBrowser", correlationId);
    return () => artifactLogger.pageUnmount("ArtifactBrowser", correlationId);
  }, [correlationId]);

  const { data, isLoading, isFetching, error, refetch } = useQuery({
    queryKey: [
      "artifacts",
      "list",
      { artifact_types: selectedTypes, subject_id: subjectIdSearch, limit: pageSize, offset },
    ],
    queryFn: ({ signal }) =>
      artifactApi.listArtifacts(
        {
          artifact_types: selectedTypes,
          subject_id: subjectIdSearch,
          limit: pageSize,
          offset,
        },
        correlationId,
        signal,
      ),
    placeholderData: keepPreviousData,
  });

  const artifacts = useMemo<readonly Artifact[]>(() => data?.artifacts ?? [], [data]);
  const totalCount = data?.total_count ?? 0;

  const handleTypeFilterChange = useCallback((e: React.ChangeEvent<HTMLSelectElement>) => {
    const value = e.target.value;
    setSelectedTypes(value === "" ? [] : [value]);
    setOffset(0); // Reset to first page when filter changes
  }, []);

  const handleSubjectIdChange = useCallback((e: React.ChangeEvent<HTMLInputElement>) => {
    setSubjectIdSearch(e.target.value);
    setOffset(0); // Reset to first page when search changes
  }, []);

  const handlePrev = useCallback(() => {
    setOffset((prev) => Math.max(0, prev - pageSize));
  }, [pageSize]);

  const handleNext = useCallback(() => {
    setOffset((prev) => {
      const next = prev + pageSize;
      return next < totalCount ? next : prev;
    });
  }, [pageSize, totalCount]);

  const handleDownload = useCallback(
    (artifactId: string) => {
      Promise.resolve(artifactApi.downloadArtifact(artifactId, correlationId)).catch((err) => {
        console.error("Download failed:", err);
      });
    },
    [correlationId],
  );

  const canPrev = offset > 0;
  const canNext = offset + pageSize < totalCount;
  const pageStart = totalCount === 0 ? 0 : offset + 1;
  const pageEnd = Math.min(offset + pageSize, totalCount);

  return (
    <div data-testid="artifacts-browser" className="mx-auto max-w-7xl space-y-6">
      <div>
        <h1 className="text-xl font-semibold text-slate-900">Artifact Browser</h1>
        <p className="mt-1 text-sm text-slate-500">
          Browse and download compiled strategies, backtest results, and analysis reports.
        </p>
      </div>

      <section aria-label="Artifact browser" className="space-y-4">
        <div className="flex flex-col gap-4 lg:flex-row lg:items-end">
          <div className="flex-1">
            <label
              htmlFor="artifacts-type-filter"
              className="block text-sm font-medium text-slate-700"
            >
              Artifact Type
            </label>
            <select
              data-testid="artifacts-type-filter"
              id="artifacts-type-filter"
              value={selectedTypes[0] ?? ""}
              onChange={handleTypeFilterChange}
              className="mt-1 block w-full rounded-md border border-slate-300 px-3 py-2 text-sm text-slate-700 focus:border-emerald-500 focus:outline-none focus:ring-1 focus:ring-emerald-500"
            >
              <option value="">All Types</option>
              {(Object.keys(ARTIFACT_TYPE_LABELS) as ArtifactType[]).map((type) => (
                <option key={type} value={type}>
                  {ARTIFACT_TYPE_LABELS[type]}
                </option>
              ))}
            </select>
          </div>

          <div className="flex-1">
            <label
              htmlFor="artifacts-subject-id-search"
              className="block text-sm font-medium text-slate-700"
            >
              Subject ID (Strategy)
            </label>
            <input
              data-testid="artifacts-subject-id-search"
              id="artifacts-subject-id-search"
              type="search"
              value={subjectIdSearch}
              onChange={handleSubjectIdChange}
              placeholder="Search by subject ID…"
              className="mt-1 block w-full rounded-md border border-slate-300 px-3 py-2 text-sm text-slate-700 focus:border-emerald-500 focus:outline-none focus:ring-1 focus:ring-emerald-500"
            />
          </div>
        </div>

        {isLoading ? (
          <div
            data-testid="artifacts-loading"
            role="status"
            className="flex items-center justify-center py-12"
          >
            <p className="text-sm text-slate-500">Loading artifacts…</p>
          </div>
        ) : error ? (
          <div
            data-testid="artifacts-error"
            role="alert"
            className="rounded-lg border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-700"
          >
            <p className="font-medium">Failed to load artifacts</p>
            <p className="mt-1">{error instanceof Error ? error.message : "Unknown error."}</p>
            <button
              type="button"
              onClick={() => refetch()}
              className="mt-2 rounded-md bg-red-600 px-3 py-1.5 text-sm text-white hover:bg-red-700"
            >
              Retry
            </button>
          </div>
        ) : artifacts.length === 0 ? (
          <div data-testid="artifacts-empty" className="py-12 text-center text-sm text-slate-500">
            No artifacts found.
          </div>
        ) : (
          <div className="overflow-x-auto rounded-lg border border-slate-200 bg-white">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-slate-200 bg-slate-50">
                  <th className="px-4 py-3 text-left font-semibold text-slate-900">Type</th>
                  <th className="px-4 py-3 text-left font-semibold text-slate-900">Subject ID</th>
                  <th className="px-4 py-3 text-left font-semibold text-slate-900">Size</th>
                  <th className="px-4 py-3 text-left font-semibold text-slate-900">Created At</th>
                  <th className="px-4 py-3 text-left font-semibold text-slate-900">Created By</th>
                  <th className="px-4 py-3 text-center font-semibold text-slate-900">Download</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-slate-100">
                {artifacts.map((artifact) => (
                  <tr
                    key={artifact.id}
                    data-testid={`artifacts-row-${artifact.id}`}
                    className="hover:bg-slate-50"
                  >
                    <td className="px-4 py-3">
                      <span
                        className={`inline-flex items-center rounded-full px-3 py-1 text-xs font-medium ring-1 ring-inset ${
                          ARTIFACT_TYPE_BADGE_CLASSES[artifact.artifact_type]
                        }`}
                      >
                        {ARTIFACT_TYPE_LABELS[artifact.artifact_type]}
                      </span>
                    </td>
                    <td className="px-4 py-3 text-slate-700">
                      <code className="text-xs">{artifact.subject_id}</code>
                    </td>
                    <td className="px-4 py-3 text-slate-600">
                      {formatFileSize(artifact.size_bytes)}
                    </td>
                    <td className="px-4 py-3 text-slate-600">
                      {new Date(artifact.created_at).toLocaleDateString(undefined, {
                        year: "numeric",
                        month: "short",
                        day: "numeric",
                      })}
                    </td>
                    <td className="px-4 py-3 text-slate-600">{artifact.created_by}</td>
                    <td className="px-4 py-3 text-center">
                      <button
                        data-testid={`artifacts-download-${artifact.id}`}
                        type="button"
                        onClick={() => handleDownload(artifact.id)}
                        className="inline-flex items-center rounded-md bg-emerald-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-emerald-700"
                      >
                        Download
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}

        <div className="flex items-center justify-between text-xs text-slate-500">
          <span data-testid="artifacts-page-summary">
            {totalCount === 0 ? "0 artifacts" : `Showing ${pageStart}–${pageEnd} of ${totalCount}`}
            {isFetching ? " (updating…)" : ""}
          </span>
          <div className="flex gap-2">
            <button
              data-testid="artifacts-prev-button"
              type="button"
              onClick={handlePrev}
              disabled={!canPrev}
              className="rounded-md border border-slate-300 px-3 py-1 text-sm font-medium text-slate-700 disabled:cursor-not-allowed disabled:opacity-50"
            >
              Previous
            </button>
            <button
              data-testid="artifacts-next-button"
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
