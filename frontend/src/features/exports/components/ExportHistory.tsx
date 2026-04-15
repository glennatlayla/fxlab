/**
 * ExportHistory — displays prior export jobs for an object.
 *
 * Purpose:
 *   Shows a table of prior exports for a run or object, with status badges,
 *   metadata, and download links for completed exports. Supports filtering
 *   by object_id and handles loading/error states.
 *
 * Responsibilities:
 *   - Fetch exports via GET /exports?object_id=... with retry.
 *   - Render table with Type, Status, Requested By, Created At, Download columns.
 *   - Show status badges with EXPORT_STATUS_CLASSES styling.
 *   - Enable download link only for complete exports with artifact_uri.
 *   - Handle loading, error, and empty states.
 *   - Propagate correlation_id for distributed tracing.
 *
 * Does NOT:
 *   - Contain business logic unrelated to export history.
 *   - Know about specific export types or formats.
 *
 * Dependencies:
 *   - exportsApi for API calls.
 *   - exportsLogger for structured logging.
 *   - EXPORT_STATUS_CLASSES, EXPORT_TYPE_LABELS.
 *
 * Props:
 *   objectId: The object ID to filter exports by (e.g., run ID).
 *
 * Example:
 *   <ExportHistory objectId="run-abc123" />
 */

import { useEffect, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { exportsApi } from "../api";
import { exportsLogger, EXPORT_STATUS_CLASSES, EXPORT_TYPE_LABELS } from "../index";
import type { ExportJobResponse, ExportStatus } from "@/types/exports";

export interface ExportHistoryProps {
  objectId: string;
}

/**
 * Format a date string to a human-readable format.
 */
function formatDate(isoString: string): string {
  const date = new Date(isoString);
  return new Intl.DateTimeFormat("en-US", {
    month: "short",
    day: "numeric",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  }).format(date);
}

/**
 * ExportHistory component.
 */
export function ExportHistory({ objectId }: ExportHistoryProps) {
  const correlationIdRef = useRef<string>(`export-history-${Date.now()}`);
  const [isRetrying, setIsRetrying] = useState(false);

  const {
    data: listResponse,
    error,
    isLoading,
    refetch,
  } = useQuery({
    queryKey: ["exports", { object_id: objectId }],
    queryFn: async ({ signal }) => {
      return exportsApi.listExports({ object_id: objectId }, correlationIdRef.current, signal);
    },
    staleTime: 10000, // 10 seconds
  });

  useEffect(() => {
    const correlationId = correlationIdRef.current;
    exportsLogger.pageMount("ExportHistory", correlationId);
    return () => {
      exportsLogger.pageUnmount("ExportHistory", correlationId);
    };
  }, []);

  const handleRetry = async () => {
    setIsRetrying(true);
    try {
      await refetch();
    } finally {
      setIsRetrying(false);
    }
  };

  // Loading state
  if (isLoading) {
    return (
      <div
        className="flex items-center justify-center rounded-lg border border-slate-200 bg-white p-12"
        data-testid="export-history-loading"
      >
        <svg className="h-6 w-6 animate-spin text-slate-600" fill="none" viewBox="0 0 24 24">
          <circle
            className="opacity-25"
            cx="12"
            cy="12"
            r="10"
            stroke="currentColor"
            strokeWidth="4"
          />
          <path
            className="opacity-75"
            fill="currentColor"
            d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"
          />
        </svg>
        <span className="ml-3 text-sm text-slate-600">Loading exports...</span>
      </div>
    );
  }

  // Error state
  if (error) {
    return (
      <div
        className="rounded-lg border border-red-200 bg-red-50 p-4"
        data-testid="export-history-error"
      >
        <div className="flex items-start gap-3">
          <svg
            className="mt-0.5 h-5 w-5 flex-shrink-0 text-red-600"
            fill="currentColor"
            viewBox="0 0 20 20"
          >
            <path
              fillRule="evenodd"
              d="M10 18a8 8 0 100-16 8 8 0 000 16zM8.707 7.293a1 1 0 00-1.414 1.414L8.586 10l-1.293 1.293a1 1 0 101.414 1.414L10 11.414l1.293 1.293a1 1 0 001.414-1.414L11.414 10l1.293-1.293a1 1 0 00-1.414-1.414L10 8.586 8.707 7.293z"
              clipRule="evenodd"
            />
          </svg>
          <div className="flex-1">
            <p className="text-sm font-medium text-red-800">Failed to load exports</p>
            <p className="mt-1 text-sm text-red-700">
              {error instanceof Error ? error.message : "An unexpected error occurred"}
            </p>
            <button
              onClick={handleRetry}
              disabled={isRetrying}
              data-testid="export-history-retry-button"
              className="mt-3 inline-flex items-center gap-1 rounded-md bg-red-600 px-3 py-1.5 text-sm font-medium text-white hover:bg-red-700 focus:outline-none focus:ring-2 focus:ring-red-500 focus:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-50"
            >
              {isRetrying ? (
                <>
                  <svg className="h-4 w-4 animate-spin" fill="none" viewBox="0 0 24 24">
                    <circle
                      className="opacity-25"
                      cx="12"
                      cy="12"
                      r="10"
                      stroke="currentColor"
                      strokeWidth="4"
                    />
                    <path
                      className="opacity-75"
                      fill="currentColor"
                      d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"
                    />
                  </svg>
                </>
              ) : (
                "Retry"
              )}
            </button>
          </div>
        </div>
      </div>
    );
  }

  // Empty state
  if (!listResponse || listResponse.exports.length === 0) {
    return (
      <div
        className="rounded-lg border border-slate-200 bg-slate-50 p-12 text-center"
        data-testid="export-history-empty"
      >
        <svg
          className="mx-auto h-12 w-12 text-slate-400"
          fill="none"
          stroke="currentColor"
          viewBox="0 0 24 24"
        >
          <path
            strokeLinecap="round"
            strokeLinejoin="round"
            strokeWidth={1.5}
            d="M9 12h6m-6 4h6m2 5H7a2 2 0 01-2-2V5a2 2 0 012-2h5.586a1 1 0 01.707.293l5.414 5.414a1 1 0 01.293.707V19a2 2 0 01-2 2z"
          />
        </svg>
        <p className="mt-4 text-sm font-medium text-slate-900">No exports yet</p>
        <p className="mt-2 text-sm text-slate-600">
          Create an export to download trade data and metadata.
        </p>
      </div>
    );
  }

  // Table view
  return (
    <div
      className="overflow-x-auto rounded-lg border border-slate-200 bg-white"
      data-testid="export-history-table"
    >
      <table className="w-full divide-y divide-slate-200">
        <thead className="bg-slate-50">
          <tr>
            <th
              className="px-6 py-3 text-left text-sm font-semibold text-slate-900"
              data-testid="export-history-header-type"
            >
              Type
            </th>
            <th
              className="px-6 py-3 text-left text-sm font-semibold text-slate-900"
              data-testid="export-history-header-status"
            >
              Status
            </th>
            <th
              className="px-6 py-3 text-left text-sm font-semibold text-slate-900"
              data-testid="export-history-header-requested-by"
            >
              Requested By
            </th>
            <th
              className="px-6 py-3 text-left text-sm font-semibold text-slate-900"
              data-testid="export-history-header-created-at"
            >
              Created
            </th>
            <th className="px-6 py-3 text-left text-sm font-semibold text-slate-900">Action</th>
          </tr>
        </thead>
        <tbody className="divide-y divide-slate-200">
          {listResponse.exports.map((exportJob: ExportJobResponse) => (
            <tr
              key={exportJob.id}
              className="hover:bg-slate-50"
              data-testid={`export-history-row-${exportJob.id}`}
            >
              <td className="px-6 py-4 text-sm text-slate-900">
                {EXPORT_TYPE_LABELS[exportJob.export_type]}
              </td>
              <td className="px-6 py-4 text-sm">
                <span
                  className={`inline-flex items-center rounded-full px-3 py-1 text-xs font-medium ring-1 ring-inset ${EXPORT_STATUS_CLASSES[exportJob.status as ExportStatus]}`}
                  data-testid={`export-status-badge-${exportJob.id}`}
                >
                  {exportJob.status.charAt(0).toUpperCase() + exportJob.status.slice(1)}
                </span>
              </td>
              <td className="px-6 py-4 text-sm text-slate-700">{exportJob.requested_by}</td>
              <td className="px-6 py-4 text-sm text-slate-600">
                {formatDate(exportJob.created_at)}
              </td>
              <td className="px-6 py-4 text-sm">
                {exportJob.status === "complete" && exportJob.artifact_uri ? (
                  <a
                    href={exportJob.artifact_uri}
                    download
                    data-testid={`export-download-link-${exportJob.id}`}
                    className="inline-flex items-center gap-1 font-medium text-blue-600 hover:text-blue-700"
                  >
                    <svg className="h-4 w-4" fill="none" stroke="currentColor" viewBox="0 0 24 24">
                      <path
                        strokeLinecap="round"
                        strokeLinejoin="round"
                        strokeWidth={2}
                        d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-4l-4 4m0 0l-4-4m4 4V4"
                      />
                    </svg>
                    Download
                  </a>
                ) : (
                  <span className="text-slate-400">—</span>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
