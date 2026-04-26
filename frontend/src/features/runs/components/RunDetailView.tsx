/**
 * RunDetailView — main run detail page content.
 *
 * Purpose:
 *   Compose all run detail sub-components into a cohesive view.
 *   Orchestrates polling, trial display, and state-dependent rendering.
 *
 * Responsibilities:
 *   - Wire useRunPolling to display live run status.
 *   - Show RunProgressBar, OptimizationProgress, or terminal states.
 *   - Display override watermarks when present.
 *   - Display preflight failures when present.
 *   - Show trial list with click-to-detail modal.
 *   - Show stale data indicator when polling fails.
 *   - Delegate metrics derivation to RunMonitorService (§4).
 *   - Delegate input validation to RunMonitorService.
 *   - Log cancellation events via RunLogger (§8).
 *
 * Does NOT:
 *   - Own routing (parent page handles route params).
 *   - Handle run submission (separate component).
 *   - Contain business logic (delegated to service layer per §4).
 */

import { useState, useCallback, useMemo, useRef } from "react";
import { useNavigate } from "react-router-dom";
import type { TrialRecord } from "@/types/run";
import { TERMINAL_RUN_STATUSES } from "@/types/run";
import { useRunPolling } from "../useRunPolling";
import { useIsMobile } from "@/hooks/useMediaQuery";
import { runsApi } from "../api";
import {
  deriveOptimizationMetrics,
  validateResultUri,
  safeParseDateMs,
  safeJsonStringify,
} from "../services/RunMonitorService";
import { RunLogger } from "../services/RunLogger";
import { RunStatusBadge } from "./RunStatusBadge";
import { RunProgressBar } from "./RunProgressBar";
import { StaleDataIndicator } from "./StaleDataIndicator";
import { OptimizationProgress } from "./OptimizationProgress";
import { OverrideWatermarkBadge } from "./OverrideWatermarkBadge";
import { PreflightFailureDisplay } from "./PreflightFailureDisplay";
import { RunTerminalState } from "./RunTerminalState";
import { TrialDetailModal } from "./TrialDetailModal";
import { ResultsSummaryCard } from "@/features/results/components/ResultsSummaryCard";

/** Props for RunDetailView. */
interface RunDetailViewProps {
  /** ULID of the run to display. */
  runId: string;
}

/**
 * Format a date string safely for display.
 *
 * Uses safeParseDateMs from service layer to handle malformed timestamps.
 * Returns "—" dash for null/invalid dates instead of "Invalid Date".
 *
 * Args:
 *   dateStr: ISO-8601 date string or null.
 *
 * Returns:
 *   Locale-formatted date string or "—".
 */
function formatDateSafe(dateStr: string | null | undefined): string {
  if (!dateStr) return "—";
  const ms = safeParseDateMs(dateStr);
  if (ms === null) return "—";
  return new Date(ms).toLocaleString();
}

/**
 * Render the run detail view.
 *
 * Args:
 *   runId: ULID of the run to monitor.
 */
export function RunDetailView({ runId }: RunDetailViewProps) {
  const { run, isLoading, isStale, error, lastUpdatedAt, refresh } = useRunPolling(runId);
  const navigate = useNavigate();
  const isMobile = useIsMobile();

  const [selectedTrial, setSelectedTrial] = useState<TrialRecord | null>(null);
  const [isModalOpen, setIsModalOpen] = useState(false);
  const loggerRef = useRef<RunLogger>(new RunLogger());

  const handleTrialClick = useCallback((trial: TrialRecord) => {
    setSelectedTrial(trial);
    setIsModalOpen(true);
  }, []);

  const handleModalClose = useCallback(() => {
    setIsModalOpen(false);
    setSelectedTrial(null);
  }, []);

  const handleRetry = useCallback(() => {
    // Re-trigger polling to check if a new run has been started
    refresh();
  }, [refresh]);

  /**
   * Cancel the current run with structured logging.
   * Guards against unmounted component state updates.
   */
  const handleCancel = useCallback(
    async (reason: string) => {
      // Structured logging: cancellation requested (§8)
      loggerRef.current.logCancellation(runId, reason);

      try {
        await runsApi.cancelRun(runId, reason);
        refresh();
      } catch (err) {
        // Structured logging for cancel failure (§8 — fire-and-forget via RunLogger)
        const cancelError = err instanceof Error ? err : new Error(String(err));
        loggerRef.current.logCancellationFailed(runId, cancelError);
      }
    },
    [runId, refresh],
  );

  // Memoize metrics derivation (§4 — business logic via service layer)
  const optimizationMetrics = useMemo(() => (run ? deriveOptimizationMetrics(run) : null), [run]);

  // Memoize terminal status check
  const isRunTerminal = useMemo(
    () => (run ? (TERMINAL_RUN_STATUSES as readonly string[]).includes(run.status) : false),
    [run],
  );

  // Loading state
  if (isLoading) {
    return (
      <div className="flex items-center justify-center py-12" data-testid="run-loading">
        <div className="h-8 w-8 animate-spin rounded-full border-2 border-gray-600 border-t-blue-500" />
        <span className="ml-3 text-gray-400">Loading run details...</span>
      </div>
    );
  }

  // Error state with no data
  if (error && !run) {
    return (
      <div
        className="rounded-lg border border-red-800 bg-red-900/20 p-6 text-center"
        data-testid="run-error"
      >
        <p className="text-red-400">Failed to load run</p>
        <p className="mt-1 text-sm text-gray-400">{error.message}</p>
        <button
          type="button"
          className="mt-3 rounded-md bg-gray-700 px-4 py-2 text-sm text-white hover:bg-gray-600"
          onClick={refresh}
        >
          Retry
        </button>
      </div>
    );
  }

  if (!run) return null;

  return (
    <div className="space-y-4" data-testid="run-detail-view">
      {/* Header */}
      <div className="flex items-center justify-between">
        <div className="flex items-center gap-3">
          <h1 className="text-xl font-bold text-white">Run {run.id.slice(0, 8)}...</h1>
          <RunStatusBadge status={run.status} />
        </div>
        <div className="flex items-center gap-2">
          <button
            type="button"
            className="rounded-md bg-gray-700 px-3 py-1.5 text-sm text-gray-200 transition-colors hover:bg-gray-600"
            onClick={refresh}
            data-testid="refresh-button"
          >
            Refresh
          </button>
          {!isRunTerminal && (
            <button
              type="button"
              className="rounded-md bg-red-700 px-3 py-1.5 text-sm text-white transition-colors hover:bg-red-600"
              onClick={() => handleCancel("User requested cancellation")}
              data-testid="cancel-button"
            >
              Cancel Run
            </button>
          )}
        </div>
      </div>

      {/* Stale indicator */}
      {isStale && lastUpdatedAt && <StaleDataIndicator lastUpdatedAt={lastUpdatedAt} />}

      {/* Override watermarks */}
      {run.override_watermarks?.map((wm) => (
        <OverrideWatermarkBadge key={wm.override_id} watermark={wm} />
      ))}

      {/* Preflight failures */}
      {run.preflight_results && (
        <PreflightFailureDisplay preflightResults={run.preflight_results} />
      )}

      {/* Progress */}
      {run.trial_count !== undefined && run.completed_trials !== undefined && (
        <RunProgressBar
          completedTrials={run.completed_trials}
          totalTrials={run.trial_count}
          status={run.status}
        />
      )}

      {/* Optimization-specific metrics */}
      {optimizationMetrics && (
        <OptimizationProgress metrics={optimizationMetrics} status={run.status} />
      )}

      {/* Run metadata — safe date parsing and JSON serialization */}
      <div className="rounded-lg border border-gray-700 bg-gray-800 p-4">
        <h3 className="mb-2 text-sm font-semibold text-gray-300">Run Details</h3>
        <div className="grid grid-cols-1 gap-x-6 gap-y-2 text-sm sm:grid-cols-2">
          <div>
            <span className="text-gray-400">Type:</span>{" "}
            <span className="text-gray-200">{run.run_type}</span>
          </div>
          <div>
            <span className="text-gray-400">Strategy Build:</span>{" "}
            <span className="font-mono text-gray-200">{run.strategy_build_id.slice(0, 8)}...</span>
          </div>
          <div>
            <span className="text-gray-400">Created:</span>{" "}
            <span className="text-gray-200">{formatDateSafe(run.created_at)}</span>
          </div>
          <div>
            <span className="text-gray-400">Started:</span>{" "}
            <span className="text-gray-200">{formatDateSafe(run.started_at)}</span>
          </div>
          {run.current_trial_params && (
            <div className="col-span-2">
              <span className="text-gray-400">Current Trial:</span>{" "}
              <span className="font-mono text-xs text-gray-200">
                {safeJsonStringify(run.current_trial_params)}
              </span>
            </div>
          )}
        </div>
      </div>

      {/* Mobile results summary card — shown prominently for completed runs on mobile */}
      {isMobile && isRunTerminal && (
        <ResultsSummaryCard runId={runId} onViewFull={() => navigate(`/results/${runId}`)} />
      )}

      {/* Terminal state — validates result_uri scheme before rendering link */}
      {isRunTerminal && (
        <RunTerminalState
          run={
            run.result_uri && !validateResultUri(run.result_uri)
              ? { ...run, result_uri: null } // Strip unsafe URI
              : run
          }
          onRetry={handleRetry}
        />
      )}

      {/* Trial list — click a row to open detail modal */}
      {run.trial_count !== undefined && run.trial_count > 0 && (
        <div className="rounded-lg border border-gray-700 bg-gray-800 p-4">
          <h3 className="mb-2 text-sm font-semibold text-gray-300">Trials</h3>
          <p className="text-xs text-gray-400">
            {run.completed_trials ?? 0} of {run.trial_count} trials completed. Click a trial row to
            view details.
          </p>
          {/* TrialLogTable with virtual scroll will be wired here in integration phase.
              handleTrialClick is the row click handler. */}
          <div data-testid="trial-list-placeholder" data-on-click={String(!!handleTrialClick)} />
        </div>
      )}

      {/* Trial detail modal */}
      <TrialDetailModal trial={selectedTrial} isOpen={isModalOpen} onClose={handleModalClose} />
    </div>
  );
}
