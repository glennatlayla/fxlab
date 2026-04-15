/**
 * ExportCenter — export job creator and status monitor.
 *
 * Purpose:
 *   Allows operators to trigger a new export job for a run, select format,
 *   preview metadata (run_id, schema_version, override watermarks), monitor
 *   processing status, and download the completed artifact.
 *
 * Responsibilities:
 *   - Render format selector (CSV, JSON, Parquet).
 *   - Display metadata preview with run_id and override watermarks.
 *   - POST /exports on button click (non-retryable).
 *   - Poll GET /exports/{id} until status is complete or failed.
 *   - Show spinner while processing, download button when complete.
 *   - Propagate correlation_id for distributed tracing.
 *
 * Does NOT:
 *   - Contain business logic unrelated to export UI.
 *   - Know about TradingResults or other features.
 *
 * Dependencies:
 *   - exportsApi for API calls.
 *   - exportsLogger for structured logging.
 *   - EXPORT_STATUS_CLASSES, EXPORT_POLL_INTERVAL_MS.
 *
 * Props:
 *   runId: The run ID to export.
 *   overrideWatermarks: Optional array of watermark IDs applied to this export.
 *
 * Example:
 *   <ExportCenter runId="run-abc123" overrideWatermarks={["wm-001"]} />
 */

import { useState, useEffect, useRef } from "react";
import { exportsApi } from "../api";
import { EXPORT_STATUS_CLASSES, EXPORT_POLL_INTERVAL_MS } from "../index";
import type { ExportJobResponse, ExportStatus } from "@/types/exports";

export interface ExportCenterProps {
  runId: string;
  overrideWatermarks?: string[];
}

const EXPORT_SCHEMA_VERSION = "1.0";

/**
 * Poll the export status until it reaches a terminal state (complete or failed).
 *
 * Args:
 *   exportId: The export job ID to poll.
 *   onStatusChange: Callback invoked each time status changes.
 *   signal: AbortSignal for cancellation.
 *
 * Returns:
 *   The final ExportJobResponse (complete or failed).
 */
async function pollExportStatus(
  exportId: string,
  onStatusChange: (job: ExportJobResponse) => void,
  signal?: AbortSignal,
): Promise<ExportJobResponse> {
  const startTime = Date.now();
  const correlationId = `poll-${exportId}-${startTime}`;

  // eslint-disable-next-line no-constant-condition
  while (true) {
    if (signal?.aborted) {
      throw new DOMException("Polling aborted", "AbortError");
    }

    try {
      const job = await exportsApi.getExport(exportId, correlationId, signal);
      onStatusChange(job);

      if (job.status === "complete" || job.status === "failed") {
        return job;
      }

      // Wait before next poll
      await new Promise((resolve) => {
        const timer = setTimeout(resolve, EXPORT_POLL_INTERVAL_MS);
        signal?.addEventListener("abort", () => clearTimeout(timer), { once: true });
      });
    } catch (err) {
      if (err instanceof DOMException && err.name === "AbortError") {
        throw err;
      }
      // On transient error, retry the poll
      throw err;
    }
  }
}

/**
 * Export job status enum for local state machine.
 */
type ExportUIState = "idle" | "processing" | "complete" | "error";

/**
 * ExportCenter component.
 */
export function ExportCenter({ runId, overrideWatermarks }: ExportCenterProps) {
  const [selectedFormat, setSelectedFormat] = useState<"csv" | "json" | "parquet">("csv");
  const [uiState, setUiState] = useState<ExportUIState>("idle");
  const [currentExport, setCurrentExport] = useState<ExportJobResponse | null>(null);
  const [error, setError] = useState<Error | null>(null);
  const abortControllerRef = useRef<AbortController | null>(null);
  const correlationIdRef = useRef<string>(`export-center-${Date.now()}`);

  // Cleanup on unmount
  useEffect(() => {
    return () => {
      abortControllerRef.current?.abort();
    };
  }, []);

  const handleExport = async () => {
    abortControllerRef.current = new AbortController();
    setError(null);
    setUiState("processing");
    setCurrentExport(null);

    try {
      // Create export job (no retry per CLAUDE.md §9)
      const job = await exportsApi.createExport(
        "runs",
        runId,
        correlationIdRef.current,
        abortControllerRef.current.signal,
      );
      setCurrentExport(job);

      // Poll until terminal state
      const finalJob = await pollExportStatus(
        job.id,
        (updated) => setCurrentExport(updated),
        abortControllerRef.current.signal,
      );

      if (finalJob.status === "complete") {
        setUiState("complete");
      } else {
        setError(new Error("Export failed"));
        setUiState("error");
      }
    } catch (err) {
      if (err instanceof DOMException && err.name === "AbortError") {
        return;
      }
      const errorMsg = err instanceof Error ? err.message : "Unknown error";
      setError(new Error(errorMsg));
      setUiState("error");
    }
  };

  const handleDownload = () => {
    if (currentExport?.id) {
      exportsApi.downloadExport(currentExport.id, correlationIdRef.current);
    }
  };

  const isExporting = uiState === "processing";
  const isComplete = uiState === "complete" && currentExport?.status === "complete";

  return (
    <div className="space-y-6 rounded-lg border border-slate-200 bg-white p-6 shadow-sm">
      <div>
        <h3 className="text-lg font-semibold text-slate-900">Export Run Data</h3>
        <p className="mt-1 text-sm text-slate-600">
          Export trade data and run metadata in your preferred format.
        </p>
      </div>

      {/* Metadata Preview */}
      <div
        className="rounded-md border border-slate-200 bg-slate-50 p-4"
        data-testid="export-metadata-preview"
      >
        <h4 className="text-sm font-medium text-slate-900">Export Metadata</h4>
        <dl className="mt-3 grid grid-cols-2 gap-4 text-sm">
          <div>
            <dt className="text-slate-600">Run ID</dt>
            <dd className="mt-1 font-mono text-slate-900">{runId}</dd>
          </div>
          <div>
            <dt className="text-slate-600">Schema Version</dt>
            <dd className="mt-1 font-mono text-slate-900" data-testid="export-schema-version">
              {EXPORT_SCHEMA_VERSION}
            </dd>
          </div>
          {overrideWatermarks && overrideWatermarks.length > 0 && (
            <div className="col-span-2">
              <dt className="text-slate-600">Override Watermarks</dt>
              <dd className="mt-2 space-y-1" data-testid="export-override-watermarks">
                {overrideWatermarks.map((wm) => (
                  <div
                    key={wm}
                    className="mr-2 inline-block rounded bg-blue-100 px-2 py-1 text-xs font-medium text-blue-800"
                  >
                    {wm}
                  </div>
                ))}
              </dd>
            </div>
          )}
        </dl>
      </div>

      {/* Format Selector */}
      <div data-testid="export-format-selector">
        <label className="block text-sm font-medium text-slate-900">Export Format</label>
        <div className="mt-3 flex gap-4">
          {["csv", "json", "parquet"].map((fmt) => (
            <label key={fmt} className="flex items-center gap-2">
              <input
                type="radio"
                name="export-format"
                value={fmt}
                checked={selectedFormat === fmt}
                onChange={(e) => setSelectedFormat(e.target.value as "csv" | "json" | "parquet")}
                disabled={isExporting}
                className="h-4 w-4"
              />
              <span className="text-sm text-slate-700">
                {fmt === "csv" ? "CSV (ZIP)" : fmt === "json" ? "JSON" : "Parquet"}
              </span>
            </label>
          ))}
        </div>
      </div>

      {/* Export Button / Status */}
      <div className="flex items-center gap-3">
        <button
          type="button"
          onClick={handleExport}
          disabled={isExporting || isComplete}
          data-testid="export-button"
          className="inline-flex items-center gap-2 rounded-md bg-blue-600 px-4 py-2 text-sm font-medium text-white hover:bg-blue-700 focus:outline-none focus:ring-2 focus:ring-blue-500 focus:ring-offset-2 disabled:cursor-not-allowed disabled:opacity-50"
        >
          {isExporting ? (
            <>
              <svg
                className="h-4 w-4 animate-spin"
                fill="none"
                viewBox="0 0 24 24"
                aria-hidden="true"
              >
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
              <span>Exporting...</span>
            </>
          ) : (
            <span>Export</span>
          )}
        </button>

        {isExporting && (
          <div
            className="flex items-center gap-2 text-sm text-amber-700"
            data-testid="export-progress-spinner"
          >
            <svg
              className="h-4 w-4 animate-spin"
              fill="none"
              viewBox="0 0 24 24"
              aria-hidden="true"
            >
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
            <span>{currentExport?.status === "processing" ? "Processing..." : "Pending..."}</span>
          </div>
        )}

        {isComplete && currentExport?.artifact_uri && (
          <button
            type="button"
            onClick={handleDownload}
            data-testid="export-download-button"
            className="inline-flex items-center gap-2 rounded-md bg-emerald-600 px-4 py-2 text-sm font-medium text-white hover:bg-emerald-700 focus:outline-none focus:ring-2 focus:ring-emerald-500 focus:ring-offset-2"
          >
            <svg
              className="h-4 w-4"
              fill="none"
              stroke="currentColor"
              viewBox="0 0 24 24"
              aria-hidden="true"
            >
              <path
                strokeLinecap="round"
                strokeLinejoin="round"
                strokeWidth={2}
                d="M4 16v1a3 3 0 003 3h10a3 3 0 003-3v-1m-4-4l-4 4m0 0l-4-4m4 4V4"
              />
            </svg>
            <span>Download</span>
          </button>
        )}
      </div>

      {/* Status Badge */}
      {currentExport && (
        <div className="flex items-center gap-2 text-sm">
          <span className="text-slate-600">Status:</span>
          <span
            className={`inline-flex items-center rounded-full px-3 py-1 text-xs font-medium ring-1 ring-inset ${EXPORT_STATUS_CLASSES[currentExport.status as ExportStatus]}`}
          >
            {currentExport.status.charAt(0).toUpperCase() + currentExport.status.slice(1)}
          </span>
        </div>
      )}

      {/* Error Message */}
      {error && (
        <div
          className="rounded-md border border-red-200 bg-red-50 p-3 text-sm text-red-700"
          data-testid="export-error-message"
        >
          {error.message}
        </div>
      )}
    </div>
  );
}
