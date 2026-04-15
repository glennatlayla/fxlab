/**
 * Readiness feature component prop types.
 *
 * Purpose:
 *   Define TypeScript interfaces for all Readiness component props.
 *   Keeps prop definitions separate from components for testability.
 *
 * Dependencies:
 *   - Types from @/types/readiness.
 */

import type {
  ReadinessGrade,
  ReadinessBlocker,
  ScoringDimension,
  HoldoutEvaluation,
  RegimeConsistencyEntry,
  OverrideWatermark,
  ReadinessReportHistoryEntry,
} from "@/types/readiness";

/** Props for RunReadinessPage container. */
export interface RunReadinessPageProps {
  /** ULID of the run to display readiness for. */
  runId: string;
}

/** Props for ReadinessViewer. */
export interface ReadinessViewerProps {
  /** Overall readiness grade (A-F). */
  grade: ReadinessGrade;
  /** Overall readiness score (0-100). */
  score: number;
  /** Policy version used for this assessment. */
  policyVersion: string;
  /** ISO-8601 timestamp of assessment. */
  assessedAt: string;
  /** Who/what performed the assessment. */
  assessor: string;
}

/** Props for GradeBadge. */
export interface GradeBadgeProps {
  /** Readiness grade to render. */
  grade: ReadinessGrade;
  /** Optional size variant. */
  size?: "sm" | "md" | "lg";
}

/** Props for ScoringBreakdown. */
export interface ScoringBreakdownProps {
  /** Per-dimension scoring data. */
  dimensions: ScoringDimension[];
}

/** Props for HoldoutStatusCard. */
export interface HoldoutStatusCardProps {
  /** Holdout evaluation data. */
  holdout: HoldoutEvaluation;
}

/** Props for RegimeConsistencyTable. */
export interface RegimeConsistencyTableProps {
  /** Per-regime consistency entries. */
  entries: RegimeConsistencyEntry[];
}

/** Props for BlockerSummary — only rendered when grade is F. */
export interface BlockerSummaryProps {
  /** List of blockers preventing promotion. */
  blockers: ReadinessBlocker[];
}

/** Props for ReportHistory. */
export interface ReportHistoryProps {
  /** Historical report entries (reverse chronological). */
  entries: ReadinessReportHistoryEntry[];
}

/** Props for OverrideWatermarkBanner. */
export interface OverrideWatermarkBannerProps {
  /** Override watermark metadata. */
  watermark: OverrideWatermark;
}

/** Props for PromotionButton. */
export interface PromotionButtonProps {
  /** Current readiness grade — button is absent (not rendered) for F. */
  grade: ReadinessGrade;
  /** Whether a pending promotion already exists. */
  hasPendingPromotion: boolean;
  /** Run ID for the promotion request. */
  runId: string;
  /** Callback when promotion is submitted. */
  onSubmit: (rationale: string, targetStage: string) => void;
  /** Whether submission is in progress. */
  isSubmitting?: boolean;
}
