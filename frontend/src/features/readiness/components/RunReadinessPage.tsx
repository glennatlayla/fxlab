/**
 * RunReadinessPage — container for readiness report viewer (M28).
 *
 * Purpose:
 *   Fetch and display the readiness report for a backtest run.
 *   Orchestrates all readiness sub-components and manages state
 *   for report generation and promotion submission.
 *
 * Responsibilities:
 *   - Fetch readiness report via TanStack Query.
 *   - Render loading, error, and success states.
 *   - Classify errors for user-facing messages.
 *   - Wire generate report and promotion callbacks.
 *   - Log page lifecycle events.
 *   - Conditionally render BlockerSummary for grade F.
 *   - Conditionally render OverrideWatermarkBanner.
 *   - Conditionally render PromotionButton (absent for grade F).
 *
 * Does NOT:
 *   - Contain business logic beyond error classification.
 *   - Own routing (parent page provides runId).
 *
 * Dependencies:
 *   - readinessApi from ../api.
 *   - readinessLogger from ../logger.
 *   - All readiness sub-components.
 *   - @tanstack/react-query for data fetching.
 *   - @/auth/useAuth for scope checks.
 *
 * Example:
 *   <RunReadinessPage runId="01HRUN..." />
 */

import { useEffect, useState, useCallback, useId } from "react";
import { useQuery } from "@tanstack/react-query";
import { readinessApi } from "../api";
import { readinessLogger } from "../logger";
import {
  ReadinessNotFoundError,
  ReadinessAuthError,
  ReadinessGenerationError,
  ReadinessValidationError,
} from "../errors";
import { useAuth } from "@/auth/useAuth";
import type { RunReadinessPageProps } from "../types";
import { FeatureErrorBoundary } from "@/components/FeatureErrorBoundary";
import { ReadinessViewer } from "./ReadinessViewer";
import { ScoringBreakdown } from "./ScoringBreakdown";
import { HoldoutStatusCard } from "./HoldoutStatusCard";
import { RegimeConsistencyTable } from "./RegimeConsistencyTable";
import { BlockerSummary } from "./BlockerSummary";
import { ReportHistory } from "./ReportHistory";
import { OverrideWatermarkBanner } from "./OverrideWatermarkBanner";
import { PromotionButton } from "./PromotionButton";

/**
 * Classify an error for a user-facing message.
 *
 * Args:
 *   error: The caught error.
 *
 * Returns:
 *   Human-readable error message string.
 */
function getErrorMessage(error: unknown): string {
  if (error instanceof ReadinessNotFoundError) {
    return "No readiness report found for this run. It may have been deleted or the run ID is incorrect.";
  }
  if (error instanceof ReadinessAuthError) {
    if (error.statusCode === 401) {
      return "Your session has expired. Please log in again to view this report.";
    }
    return "You do not have permission to view this readiness report.";
  }
  if (error instanceof Error) {
    return error.message;
  }
  return "An unexpected error occurred.";
}

/**
 * Render the readiness report page.
 *
 * Args:
 *   runId: ULID of the run.
 */
export function RunReadinessPage({ runId }: RunReadinessPageProps) {
  const { hasScope } = useAuth();
  // Stable correlation ID for structured logging — ties all API calls
  // and log events from this page instance together.
  const correlationId = useId();
  const [isGenerating, setIsGenerating] = useState(false);
  const [generateError, setGenerateError] = useState<string | null>(null);
  const [isSubmittingPromotion, setIsSubmittingPromotion] = useState(false);
  const [promotionError, setPromotionError] = useState<string | null>(null);

  // Log page lifecycle with correlation ID for trace linking.
  useEffect(() => {
    readinessLogger.pageMount(runId, correlationId);
    return () => readinessLogger.pageUnmount(runId, correlationId);
  }, [runId, correlationId]);

  // Fetch readiness report.
  const {
    data: report,
    isLoading,
    error,
    refetch,
  } = useQuery({
    queryKey: ["readiness", runId],
    queryFn: () => readinessApi.getReadinessReport(runId, correlationId),
  });

  // Generate readiness report.
  const handleGenerate = useCallback(async () => {
    setIsGenerating(true);
    setGenerateError(null);
    try {
      await readinessApi.generateReadinessReport(runId, correlationId);
      await refetch();
    } catch (err) {
      const msg =
        err instanceof ReadinessGenerationError
          ? "Failed to generate readiness report. Please try again."
          : err instanceof ReadinessAuthError
            ? "You do not have permission to generate reports."
            : err instanceof ReadinessValidationError
              ? "The server returned an invalid report. Please contact support."
              : err instanceof Error
                ? err.message
                : "An unexpected error occurred.";
      setGenerateError(msg);
    } finally {
      setIsGenerating(false);
    }
  }, [runId, correlationId, refetch]);

  // Submit for promotion.
  const handlePromotionSubmit = useCallback(
    async (rationale: string, targetStage: string) => {
      setIsSubmittingPromotion(true);
      setPromotionError(null);
      try {
        await readinessApi.submitForPromotion(runId, rationale, targetStage, correlationId);
        await refetch();
      } catch (err) {
        const msg =
          err instanceof ReadinessAuthError
            ? "You do not have permission to submit promotions."
            : err instanceof ReadinessValidationError
              ? "The server returned an invalid response. Please contact support."
              : err instanceof Error
                ? err.message
                : "An unexpected error occurred during promotion submission.";
        setPromotionError(msg);
      } finally {
        setIsSubmittingPromotion(false);
      }
    },
    [runId, correlationId, refetch],
  );

  // Loading state.
  if (isLoading) {
    return (
      <div
        data-testid="readiness-loading"
        role="status"
        aria-label="Loading readiness report"
        className="flex h-64 items-center justify-center"
      >
        <div className="h-8 w-8 animate-spin rounded-full border-4 border-slate-300 border-t-slate-700" />
      </div>
    );
  }

  // Error state.
  if (error) {
    return (
      <div
        data-testid="readiness-error"
        role="alert"
        className="rounded-lg border border-red-200 bg-red-50 p-6"
      >
        <h2 className="text-lg font-semibold text-red-800">Unable to load readiness report</h2>
        <p className="mt-2 text-sm text-red-700">{getErrorMessage(error)}</p>
        <button
          type="button"
          onClick={() => refetch()}
          className="mt-4 rounded-md bg-red-100 px-3 py-1.5 text-sm font-medium text-red-700 hover:bg-red-200"
        >
          Try Again
        </button>
      </div>
    );
  }

  if (!report) return null;

  const canWrite = hasScope("runs:write");

  return (
    <div data-testid="run-readiness-page" className="space-y-6">
      {/* Override watermark — rendered above everything when active */}
      {report.override_watermark && (
        <FeatureErrorBoundary featureName="Override Watermark">
          <OverrideWatermarkBanner watermark={report.override_watermark} />
        </FeatureErrorBoundary>
      )}

      {/* Readiness overview: grade badge, score, policy version */}
      <FeatureErrorBoundary featureName="Readiness Viewer">
        <ReadinessViewer
          grade={report.grade}
          score={report.score}
          policyVersion={report.policy_version}
          assessedAt={report.assessed_at}
          assessor={report.assessor}
        />
      </FeatureErrorBoundary>

      {/* Generate report button */}
      <div className="flex items-center gap-3">
        <button
          type="button"
          disabled={isGenerating || !canWrite}
          onClick={handleGenerate}
          className="inline-flex items-center gap-2 rounded-md bg-slate-700 px-4 py-2 text-sm font-medium text-white hover:bg-slate-800 disabled:cursor-not-allowed disabled:opacity-50"
          aria-label="Generate readiness report"
        >
          {isGenerating ? "Generating..." : "Generate Report"}
        </button>
        {!canWrite && <span className="text-xs text-slate-400">Requires runs:write scope</span>}
      </div>

      {generateError && (
        <div
          data-testid="generate-error-banner"
          role="alert"
          className="rounded-lg border border-red-200 bg-red-50 px-4 py-2 text-sm text-red-700"
        >
          {generateError}
        </div>
      )}

      {/* Blockers — only for grade F */}
      {report.grade === "F" && report.blockers.length > 0 && (
        <FeatureErrorBoundary featureName="Blocker Summary">
          <BlockerSummary blockers={report.blockers} />
        </FeatureErrorBoundary>
      )}

      {/* Scoring breakdown */}
      <FeatureErrorBoundary featureName="Scoring Breakdown">
        <ScoringBreakdown dimensions={report.dimensions} />
      </FeatureErrorBoundary>

      {/* Holdout evaluation */}
      <FeatureErrorBoundary featureName="Holdout Status">
        <HoldoutStatusCard holdout={report.holdout} />
      </FeatureErrorBoundary>

      {/* Regime consistency */}
      {report.regime_consistency.length > 0 && (
        <FeatureErrorBoundary featureName="Regime Consistency">
          <RegimeConsistencyTable entries={report.regime_consistency} />
        </FeatureErrorBoundary>
      )}

      {/* Promotion button — absent for grade F (AC-3) */}
      <PromotionButton
        grade={report.grade}
        hasPendingPromotion={report.has_pending_promotion}
        runId={runId}
        onSubmit={handlePromotionSubmit}
        isSubmitting={isSubmittingPromotion}
      />

      {promotionError && (
        <div
          data-testid="promotion-error-banner"
          role="alert"
          className="rounded-lg border border-red-200 bg-red-50 px-4 py-2 text-sm text-red-700"
        >
          {promotionError}
        </div>
      )}

      {/* Report history */}
      {report.report_history.length > 0 && (
        <FeatureErrorBoundary featureName="Report History">
          <ReportHistory entries={report.report_history} />
        </FeatureErrorBoundary>
      )}
    </div>
  );
}
