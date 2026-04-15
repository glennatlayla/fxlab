/**
 * Public API for the runs feature (M26).
 *
 * Re-exports hooks, API service, and key components for use by
 * page-level components and other features.
 */

export { runsApi } from "./api";
export { RUN_STATUS } from "@/types/run";
export {
  calculateNextInterval,
  isTerminalStatus,
  isStaleData,
  shouldStopPolling,
  deriveOptimizationMetrics,
  validateResultUri,
  validateUlid,
  safeParseDateMs,
  safeJsonStringify,
} from "./services/RunMonitorService";
export { RunLogger } from "./services/RunLogger";
export type { RunLogEvent, RunLogEventType } from "./services/RunLogger";
export type { TrialListResponse, TrialListParams } from "./api";
export { useRunPolling } from "./useRunPolling";
export type { UseRunPollingResult } from "./useRunPolling";
export { useRunSubmission } from "./useRunSubmission";
export type { UseRunSubmissionResult } from "./useRunSubmission";
export { RunDetailView } from "./components/RunDetailView";
export { RunStatusBadge } from "./components/RunStatusBadge";
export { RunProgressBar } from "./components/RunProgressBar";
export { StaleDataIndicator } from "./components/StaleDataIndicator";
export { OptimizationProgress } from "./components/OptimizationProgress";
export { OverrideWatermarkBadge } from "./components/OverrideWatermarkBadge";
export { PreflightFailureDisplay } from "./components/PreflightFailureDisplay";
export { TrialDetailModal } from "./components/TrialDetailModal";
export { RunTerminalState } from "./components/RunTerminalState";
