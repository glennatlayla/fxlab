/**
 * Component prop interfaces for the Run Monitor feature (M26).
 *
 * Purpose:
 *   Define TypeScript prop interfaces for all M26 presentational and
 *   container components. Keeping props in a dedicated file prevents
 *   circular imports between components and simplifies testing.
 *
 * Responsibilities:
 *   - Define props for RunPage, RunStatusBadge, OptimizationProgress,
 *     TrialDetailModal, PreflightFailureDisplay, OverrideWatermarkBadge,
 *     RunSubmissionForm, TrialLogTable, and StaleDataIndicator.
 *
 * Does NOT:
 *   - Contain implementations or rendering logic.
 *   - Contain domain types (those live in @/types/run.ts).
 *   - Contain API types (those live in ./api.ts).
 *
 * Dependencies:
 *   - @/types/run for domain types.
 */

import type {
  RunRecord,
  RunStatus,
  TrialRecord,
  BlockerDetail,
  PreflightResult,
  OverrideWatermark,
  OptimizationMetrics,
  ResearchRunSubmission,
  OptimizationRunSubmission,
} from "@/types/run";

// ---------------------------------------------------------------------------
// RunStatusBadge — displays run status as a coloured pill
// ---------------------------------------------------------------------------

/** Props for the RunStatusBadge component. */
export interface RunStatusBadgeProps {
  /** Current run lifecycle status. */
  status: RunStatus;
  /** Optional additional CSS class names. */
  className?: string;
}

// ---------------------------------------------------------------------------
// StaleDataIndicator — renders "data stale as of X" warning
// ---------------------------------------------------------------------------

/** Props for the StaleDataIndicator component. */
export interface StaleDataIndicatorProps {
  /** ISO-8601 timestamp of the last successful poll. */
  lastUpdatedAt: string;
  /** Optional additional CSS class names. */
  className?: string;
}

// ---------------------------------------------------------------------------
// OptimizationProgress — trial gauge, best trial, trials-per-minute
// ---------------------------------------------------------------------------

/** Props for the OptimizationProgress component. */
export interface OptimizationProgressProps {
  /** Aggregated optimization metrics for the run. */
  metrics: OptimizationMetrics;
  /** Current run status (controls whether progress is animating). */
  status: RunStatus;
  /** Optional additional CSS class names. */
  className?: string;
}

// ---------------------------------------------------------------------------
// TrialLogTable — virtual-scrolled trial list (TanStack Virtual)
// ---------------------------------------------------------------------------

/** Props for the TrialLogTable component. */
export interface TrialLogTableProps {
  /** ULID of the parent run (for fetching trial pages). */
  runId: string;
  /** Array of trial records to display. */
  trials: TrialRecord[];
  /** Total number of trials (for virtual scroll sizing). */
  totalTrials: number;
  /** Callback when a trial row is clicked (opens TrialDetailModal). */
  onTrialClick: (trial: TrialRecord) => void;
  /** Whether more trials are being loaded (shows loading row at bottom). */
  isLoadingMore: boolean;
  /** Callback to load more trials when scroll reaches threshold. */
  onLoadMore: () => void;
  /** Optional additional CSS class names. */
  className?: string;
}

// ---------------------------------------------------------------------------
// TrialDetailModal — full trial information overlay
// ---------------------------------------------------------------------------

/** Props for the TrialDetailModal component. */
export interface TrialDetailModalProps {
  /** Trial record to display (null to close modal). */
  trial: TrialRecord | null;
  /** Whether the modal is open. */
  isOpen: boolean;
  /** Callback to close the modal. */
  onClose: () => void;
}

// ---------------------------------------------------------------------------
// PreflightFailureDisplay — structured rejection reasons
// ---------------------------------------------------------------------------

/** Props for the PreflightFailureDisplay component. */
export interface PreflightFailureDisplayProps {
  /** Preflight results containing blocker details. */
  preflightResults: PreflightResult[];
  /**
   * Optional callback when a blocker next-step action is clicked.
   * Receives the blocker detail and the registry next-step key string.
   * Parent is responsible for routing/logging — no console.warn in this component.
   */
  onNextStep?: (blocker: BlockerDetail, nextStepKey: string) => void;
  /** Optional additional CSS class names. */
  className?: string;
}

// ---------------------------------------------------------------------------
// BlockerCard — single blocker within preflight display
// ---------------------------------------------------------------------------

/** Props for the BlockerCard component. */
export interface BlockerCardProps {
  /** Blocker detail record from backend. */
  blocker: BlockerDetail;
  /** Callback when the next-step action is clicked. */
  onNextStepClick: (blocker: BlockerDetail) => void;
}

// ---------------------------------------------------------------------------
// OverrideWatermarkBadge — amber warning per spec §8.2
// ---------------------------------------------------------------------------

/**
 * Props for the OverrideWatermarkBadge component.
 *
 * Per spec §8.2: badge must be ≥16px, amber/warning colour, and
 * visible on run cards when the strategy build has an active override.
 */
export interface OverrideWatermarkBadgeProps {
  /** Override watermark metadata. */
  watermark: OverrideWatermark;
  /** Optional additional CSS class names. */
  className?: string;
}

// ---------------------------------------------------------------------------
// RunSubmissionForm — form for submitting research/optimization runs
// ---------------------------------------------------------------------------

/** Props for the RunSubmissionForm component. */
export interface RunSubmissionFormProps {
  /** ULID of the strategy build to execute. */
  strategyBuildId: string;
  /** Callback on successful research run submission. */
  onResearchSubmit: (payload: ResearchRunSubmission) => Promise<void>;
  /** Callback on successful optimization run submission. */
  onOptimizationSubmit: (payload: OptimizationRunSubmission) => Promise<void>;
  /** Whether a submission is currently in progress. */
  isSubmitting: boolean;
  /** Error from the most recent submission attempt (null on success). */
  submissionError: Error | null;
  /** Optional additional CSS class names. */
  className?: string;
}

// ---------------------------------------------------------------------------
// RunHeader — top section of run detail page
// ---------------------------------------------------------------------------

/** Props for the RunHeader component. */
export interface RunHeaderProps {
  /** Current run record. */
  run: RunRecord;
  /** Whether the data shown may be stale. */
  isStale: boolean;
  /** ISO-8601 timestamp of the last successful poll. */
  lastUpdatedAt: string | null;
  /** Callback to trigger a manual refresh. */
  onRefresh: () => void;
  /** Callback to cancel the run (only shown for non-terminal runs). */
  onCancel: (reason: string) => void;
}

// ---------------------------------------------------------------------------
// RunTerminalState — displayed when run reaches a terminal status
// ---------------------------------------------------------------------------

/** Props for the RunTerminalState component. */
export interface RunTerminalStateProps {
  /** Current run record (must be in a terminal status). */
  run: RunRecord;
  /** Callback to retry a failed run. */
  onRetry: () => void;
}

// ---------------------------------------------------------------------------
// RunProgressBar — trial completion progress indicator
// ---------------------------------------------------------------------------

/** Props for the RunProgressBar component. */
export interface RunProgressBarProps {
  /** Number of completed trials. */
  completedTrials: number;
  /** Total number of trials planned. */
  totalTrials: number;
  /** Current run status (controls animation and colour). */
  status: RunStatus;
  /** Optional additional CSS class names. */
  className?: string;
}
