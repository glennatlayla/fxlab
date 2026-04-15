/**
 * RunResultsPage — container component for the Results Explorer.
 *
 * Purpose:
 *   Page-level component that fetches the RunChartsPayload for a given
 *   run ID and orchestrates all Results Explorer sub-components.
 *   Wraps each section in FeatureErrorBoundary for fault isolation.
 *
 * Responsibilities:
 *   - Fetch run chart data via resultsApi.getRunCharts.
 *   - Manage loading, error, and success states.
 *   - Manage download lifecycle with AbortController and loading state.
 *   - Wrap each section in FeatureErrorBoundary for crash isolation.
 *   - Log page lifecycle events (mount, unmount).
 *   - Classify errors for user-friendly messaging.
 *   - Render EquityView, TradeBlotter, TrialSummaryTable, etc.
 *   - Show SamplingBanner and TradesTruncatedBanner when applicable.
 *
 * Does NOT:
 *   - Parse route params (receives runId as a prop).
 *   - Implement chart rendering (delegates to child components).
 *   - Handle auth (apiClient interceptors handle that).
 *
 * Dependencies:
 *   - RunResultsPageProps from ../types.
 *   - resultsApi for data fetching and downloads.
 *   - useChartEngine for engine selection.
 *   - FeatureErrorBoundary for section-level crash isolation.
 *   - resultsLogger for structured logging.
 *   - ResultsNotFoundError, ResultsDownloadError for error classification.
 *   - All Results Explorer child components.
 *
 * Error conditions:
 *   - API fetch failure → error state with classification.
 *   - Child render crash → FeatureErrorBoundary catches per section.
 *   - Download failure → toast or inline error (non-blocking).
 */

import { useState, useCallback, useRef, useEffect, memo } from "react";
import { useQuery } from "@tanstack/react-query";
import { resultsApi } from "../api";
import { useChartEngine } from "@/hooks/useChartEngine";
import { TOP_N_TRIALS } from "@/types/results";
import type { RunResultsPageProps } from "../types";
import type { TradeBlotterFilters } from "@/types/results";
import { FeatureErrorBoundary } from "@/components/FeatureErrorBoundary";
import { ResultsNotFoundError, ResultsAuthError, ResultsDownloadError } from "../errors";
import { BLOB_REVOKE_DELAY_MS } from "../constants";
import { resultsLogger } from "../logger";
import { EquityView } from "./EquityView";
import { SamplingBanner } from "./SamplingBanner";
import { TradesTruncatedBanner } from "./TradesTruncatedBanner";
import { TradeBlotter } from "./TradeBlotter";
import { TrialSummaryTable } from "./TrialSummaryTable";
import { CandidateComparisonTable } from "./CandidateComparisonTable";
import { SegmentedPerformanceBar } from "./SegmentedPerformanceBar";

/**
 * Classify an error into a user-friendly message.
 *
 * Args:
 *   error: The error to classify.
 *
 * Returns:
 *   A human-readable error message.
 */
function getErrorMessage(error: unknown): string {
  if (error instanceof ResultsNotFoundError) {
    return "This run was not found. It may have been deleted or the ID is incorrect.";
  }
  if (error instanceof ResultsAuthError) {
    return error.statusCode === 401
      ? "Your session has expired. Please log in again."
      : "You do not have permission to view this run.";
  }
  if (error instanceof Error) {
    return error.message;
  }
  return "An unexpected error occurred.";
}

/**
 * Render the run results page.
 *
 * Args:
 *   runId: ULID of the run to display results for.
 *
 * Returns:
 *   Results Explorer page element with all sub-components.
 *
 * Example:
 *   <RunResultsPage runId="01HRUN0000000000000000001" />
 */
export const RunResultsPage = memo(function RunResultsPage({ runId }: RunResultsPageProps) {
  // -------------------------------------------------------------------------
  // Data fetching
  // -------------------------------------------------------------------------

  const {
    data: payload,
    isLoading,
    error,
  } = useQuery({
    queryKey: ["runCharts", runId],
    queryFn: () => resultsApi.getRunCharts(runId),
  });

  const engine = useChartEngine(payload?.equity_curve.length ?? 0);

  // -------------------------------------------------------------------------
  // Filter state
  // -------------------------------------------------------------------------

  const [tradeFilters, setTradeFilters] = useState<TradeBlotterFilters>({
    symbol: null,
    side: null,
    fold_index: null,
    regime: null,
  });

  // -------------------------------------------------------------------------
  // Download lifecycle with AbortController
  // -------------------------------------------------------------------------

  const [isDownloading, setIsDownloading] = useState(false);
  const [downloadError, setDownloadError] = useState<string | null>(null);
  const abortControllerRef = useRef<AbortController | null>(null);

  const handleDownload = useCallback(async () => {
    // Abort any in-flight download before starting a new one.
    if (abortControllerRef.current) {
      abortControllerRef.current.abort();
    }

    const controller = new AbortController();
    abortControllerRef.current = controller;
    setIsDownloading(true);
    setDownloadError(null);

    try {
      const blob = await resultsApi.downloadExportBundle(runId, controller.signal);
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = `run-${runId}-export.zip`;
      link.click();
      // Revoke after a generous delay to let the browser complete the save dialog.
      setTimeout(() => URL.revokeObjectURL(url), BLOB_REVOKE_DELAY_MS);
    } catch (err) {
      if (err instanceof ResultsDownloadError && err.reason === "abort") {
        // User-initiated cancellation — not an error.
        return;
      }
      const message = err instanceof Error ? err.message : "Download failed";
      setDownloadError(message);
    } finally {
      setIsDownloading(false);
      if (abortControllerRef.current === controller) {
        abortControllerRef.current = null;
      }
    }
  }, [runId]);

  // -------------------------------------------------------------------------
  // Lifecycle logging and cleanup
  // -------------------------------------------------------------------------

  useEffect(() => {
    resultsLogger.pageMount(runId);
    return () => {
      resultsLogger.pageUnmount(runId);
      // Abort any in-flight download on unmount.
      abortControllerRef.current?.abort();
    };
  }, [runId]);

  // -------------------------------------------------------------------------
  // Loading state
  // -------------------------------------------------------------------------

  if (isLoading) {
    return (
      <div
        data-testid="results-loading"
        role="status"
        aria-label="Loading results"
        className="flex h-96 items-center justify-center"
      >
        <div className="flex items-center gap-3 text-slate-500">
          <svg className="h-5 w-5 animate-spin" fill="none" viewBox="0 0 24 24" aria-hidden="true">
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
          Loading results...
        </div>
      </div>
    );
  }

  // -------------------------------------------------------------------------
  // Error state with classification
  // -------------------------------------------------------------------------

  if (error || !payload) {
    return (
      <div
        data-testid="results-error"
        role="alert"
        className="flex h-96 items-center justify-center"
      >
        <div className="text-center">
          <p className="text-lg font-medium text-red-600">Failed to load results</p>
          <p className="mt-1 text-sm text-slate-500">{getErrorMessage(error)}</p>
        </div>
      </div>
    );
  }

  // -------------------------------------------------------------------------
  // Success state
  // -------------------------------------------------------------------------

  return (
    <div data-testid="run-results-page" className="space-y-6 p-6">
      {/* Page header */}
      <div className="flex items-center justify-between">
        <h1 className="text-xl font-semibold text-slate-900">Run Results</h1>
        <span className="text-xs text-slate-400">v{payload.export_schema_version}</span>
      </div>

      {/* Download error banner */}
      {downloadError && (
        <div
          data-testid="download-error-banner"
          role="alert"
          className="rounded-md border border-red-200 bg-red-50 px-4 py-3 text-sm text-red-800"
        >
          Download failed: {downloadError}
        </div>
      )}

      {/* Banners */}
      <SamplingBanner
        samplingApplied={payload.sampling_applied}
        rawPointCount={payload.raw_equity_point_count}
        displayedPointCount={payload.equity_curve.length}
      />
      <TradesTruncatedBanner
        tradesTruncated={payload.trades_truncated}
        totalTradeCount={payload.total_trade_count}
        onDownload={handleDownload}
      />

      {/* Equity + drawdown charts — isolated error boundary */}
      <FeatureErrorBoundary featureName="Equity View">
        <section>
          <h2 className="mb-3 text-sm font-semibold uppercase tracking-wide text-slate-500">
            Equity Curve
          </h2>
          <EquityView data={payload} engine={engine} />
        </section>
      </FeatureErrorBoundary>

      {/* Segment performance — isolated error boundary */}
      {(payload.fold_performance.length > 0 || payload.regime_performance.length > 0) && (
        <FeatureErrorBoundary featureName="Segment Performance">
          <section>
            <h2 className="mb-3 text-sm font-semibold uppercase tracking-wide text-slate-500">
              Segment Performance
            </h2>
            <SegmentedPerformanceBar
              foldPerformance={payload.fold_performance}
              regimePerformance={payload.regime_performance}
            />
          </section>
        </FeatureErrorBoundary>
      )}

      {/* Trade blotter — isolated error boundary */}
      <FeatureErrorBoundary featureName="Trade Blotter">
        <section>
          <h2 className="mb-3 text-sm font-semibold uppercase tracking-wide text-slate-500">
            Trade Blotter
          </h2>
          <TradeBlotter
            trades={payload.trades}
            tradesTruncated={payload.trades_truncated}
            totalTradeCount={payload.total_trade_count}
            filters={tradeFilters}
            onFiltersChange={setTradeFilters}
            onDownload={handleDownload}
            isDownloading={isDownloading}
          />
        </section>
      </FeatureErrorBoundary>

      {/* Trial summary — isolated error boundary */}
      {payload.trial_summaries.length > 0 && (
        <FeatureErrorBoundary featureName="Trial Summary">
          <section>
            <h2 className="mb-3 text-sm font-semibold uppercase tracking-wide text-slate-500">
              Trial Summary
            </h2>
            <TrialSummaryTable
              trials={payload.trial_summaries}
              topN={TOP_N_TRIALS}
              onTrialClick={(_trialId) => {
                // Future: navigate to trial detail or open modal (M28+)
              }}
              onDownload={handleDownload}
              isDownloading={isDownloading}
            />
          </section>
        </FeatureErrorBoundary>
      )}

      {/* Candidate comparison — isolated error boundary */}
      {payload.candidate_metrics.length > 0 && (
        <FeatureErrorBoundary featureName="Candidate Comparison">
          <section>
            <h2 className="mb-3 text-sm font-semibold uppercase tracking-wide text-slate-500">
              Candidate Comparison
            </h2>
            <CandidateComparisonTable
              candidates={payload.candidate_metrics}
              onDownload={handleDownload}
              isDownloading={isDownloading}
            />
          </section>
        </FeatureErrorBoundary>
      )}
    </div>
  );
});
