/**
 * Results Explorer feature barrel export (M27).
 *
 * Re-exports all public components, hooks, types, API service,
 * error types, logger, and constants for the Results Explorer feature.
 */

// API service
export { resultsApi } from "./api";

// Error types and classifier
export {
  ResultsError,
  ResultsNotFoundError,
  ResultsAuthError,
  ResultsValidationError,
  ResultsNetworkError,
  ResultsDownloadError,
  isTransientError,
} from "./errors";

// Structured logger
export { resultsLogger } from "./logger";

// Constants
export {
  EQUITY_CHART_HEIGHT,
  DRAWDOWN_CHART_HEIGHT,
  COLOR_EQUITY_LINE,
  COLOR_DRAWDOWN_STROKE,
  COLOR_DRAWDOWN_FILL,
  TRADE_BLOTTER_ROW_HEIGHT,
  TRADE_BLOTTER_VIEWPORT_HEIGHT,
  TRADE_BLOTTER_OVERSCAN,
  TRIAL_TABLE_ROW_HEIGHT,
  TRIAL_TABLE_VIEWPORT_HEIGHT,
  TRIAL_TABLE_OVERSCAN,
  CANDIDATE_TABLE_ROW_HEIGHT,
  CANDIDATE_TABLE_VIEWPORT_HEIGHT,
  CANDIDATE_TABLE_OVERSCAN,
  API_MAX_RETRIES,
  API_RETRY_BASE_DELAY_MS,
  API_JITTER_FACTOR,
  DOWNLOAD_TIMEOUT_MS,
  BLOB_REVOKE_DELAY_MS,
  EXPORT_BLOB_MIME_TYPE,
} from "./constants";

// Components
export { RunResultsPage } from "./components/RunResultsPage";
export { EquityView } from "./components/EquityView";
export { EquityCurve } from "./components/EquityCurve";
export { DrawdownCurve } from "./components/DrawdownCurve";
export { TradeBlotter } from "./components/TradeBlotter";
export { TrialSummaryTable } from "./components/TrialSummaryTable";
export { CandidateComparisonTable } from "./components/CandidateComparisonTable";
export { SegmentedPerformanceBar } from "./components/SegmentedPerformanceBar";
export { SamplingBanner } from "./components/SamplingBanner";
export { TradesTruncatedBanner } from "./components/TradesTruncatedBanner";
export { DownloadDataButton } from "./components/DownloadDataButton";

// Type exports
export type {
  RunResultsPageProps,
  EquityCurveProps,
  DrawdownCurveProps,
  SegmentedPerformanceBarProps,
  RegimeOverlayProps,
  TradeBlotterProps,
  TrialSummaryTableProps,
  CandidateComparisonTableProps,
  SamplingBannerProps,
  TradesTruncatedBannerProps,
  DownloadDataButtonProps,
  EquityViewProps,
} from "./types";
