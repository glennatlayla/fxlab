/**
 * Readiness feature barrel export.
 *
 * Re-exports all public components, types, API, errors, and constants
 * for the Readiness Report Viewer feature (M28).
 */

// Components
export { RunReadinessPage } from "./components/RunReadinessPage";
export { ReadinessViewer } from "./components/ReadinessViewer";
export { GradeBadge } from "./components/GradeBadge";
export { ScoringBreakdown } from "./components/ScoringBreakdown";
export { HoldoutStatusCard } from "./components/HoldoutStatusCard";
export { RegimeConsistencyTable } from "./components/RegimeConsistencyTable";
export { BlockerSummary } from "./components/BlockerSummary";
export { ReportHistory } from "./components/ReportHistory";
export { OverrideWatermarkBanner } from "./components/OverrideWatermarkBanner";
export { PromotionButton } from "./components/PromotionButton";

// API
export { readinessApi } from "./api";

// Errors
export {
  ReadinessError,
  ReadinessNotFoundError,
  ReadinessAuthError,
  ReadinessValidationError,
  ReadinessNetworkError,
  ReadinessGenerationError,
  isTransientError,
} from "./errors";

// Logger
export { readinessLogger } from "./logger";

// Types
export type {
  RunReadinessPageProps,
  ReadinessViewerProps,
  GradeBadgeProps,
  ScoringBreakdownProps,
  HoldoutStatusCardProps,
  RegimeConsistencyTableProps,
  BlockerSummaryProps,
  ReportHistoryProps,
  OverrideWatermarkBannerProps,
  PromotionButtonProps,
} from "./types";

// Constants
export {
  GRADE_BADGE_CLASSES,
  GRADE_INTERPRETATION,
  GRADE_THRESHOLDS,
  DIMENSION_CONFIG,
  OVERRIDE_WATERMARK_CLASSES,
  BLOCKER_SEVERITY_CLASSES,
} from "./constants";
