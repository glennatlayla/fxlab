/**
 * Domain types for the Run Monitor feature (M26).
 *
 * Purpose:
 *   TypeScript interfaces mirroring the backend Pydantic contracts in
 *   `libs/contracts/research.py` and `libs/contracts/models.py`.
 *   Used across the runs feature for type safety.
 *
 * Does NOT:
 *   - Contain runtime validation (see run.schemas.ts for Zod).
 *   - Contain business logic or UI rendering.
 *
 * Dependencies:
 *   - None (pure type definitions).
 */

// ---------------------------------------------------------------------------
// Enums
// ---------------------------------------------------------------------------

/** Run type — mirrors backend RunType enum. */
export type RunType = "research" | "optimization";

/** Run lifecycle status — mirrors backend RunStatus enum. */
export type RunStatus = "pending" | "running" | "complete" | "failed" | "cancelled";

/**
 * Named constants for run status values.
 *
 * Use these instead of string literals to ensure single-source-of-truth
 * for status comparisons across components and services.
 */
export const RUN_STATUS = {
  PENDING: "pending" as const,
  RUNNING: "running" as const,
  COMPLETE: "complete" as const,
  FAILED: "failed" as const,
  CANCELLED: "cancelled" as const,
} satisfies Record<string, RunStatus>;

/** Terminal run statuses where polling should stop. */
export const TERMINAL_RUN_STATUSES: readonly RunStatus[] = [
  RUN_STATUS.COMPLETE,
  RUN_STATUS.FAILED,
  RUN_STATUS.CANCELLED,
] as const;

/** Trial lifecycle status. */
export type TrialStatus = "pending" | "running" | "completed" | "failed";

// ---------------------------------------------------------------------------
// Run record — returned by GET /runs/{run_id}
// ---------------------------------------------------------------------------

/**
 * Run record as returned by the backend API.
 *
 * Maps to `ResearchRunResponse` Pydantic model plus live progress fields.
 */
export interface RunRecord {
  /** ULID primary key. */
  id: string;
  /** ULID of the strategy build this run executes. */
  strategy_build_id: string;
  /** Whether this is a research or optimization run. */
  run_type: RunType;
  /** Current lifecycle status. */
  status: RunStatus;
  /** Run configuration (parameters, seeds, etc.). */
  config: Record<string, unknown>;
  /** URI to download completed results (null until complete). */
  result_uri: string | null;
  /** User ID who initiated the run. */
  created_by: string;
  /** ISO-8601 timestamp. */
  created_at: string;
  /** ISO-8601 timestamp. */
  updated_at: string;
  /** When the run began executing (null if still pending). */
  started_at: string | null;
  /** When the run finished (null until terminal). */
  completed_at: string | null;

  // ── Live progress fields (populated by backend during execution) ──

  /** Total number of trials planned for this run. */
  trial_count?: number;
  /** Number of trials completed so far. */
  completed_trials?: number;
  /** Parameters of the currently executing trial (null if idle). */
  current_trial_params?: Record<string, unknown> | null;
  /** Error message if status is "failed". */
  error_message?: string | null;
  /** Cancellation reason if status is "cancelled". */
  cancellation_reason?: string | null;
  /** Override watermark metadata if strategy build has active override (§8.2). */
  override_watermarks?: OverrideWatermark[];
  /** Preflight rejection details if run failed preflight (§8.3). */
  preflight_results?: PreflightResult[];
}

// ---------------------------------------------------------------------------
// Trial record — returned inside run detail or trial list
// ---------------------------------------------------------------------------

/** Single trial within a run. */
export interface TrialRecord {
  /** ULID primary key. */
  id: string;
  /** ULID of the parent run. */
  run_id: string;
  /** Zero-based trial index within the run. */
  trial_index: number;
  /** Trial lifecycle status. */
  status: TrialStatus;
  /** Trial parameter values. */
  parameters: Record<string, unknown>;
  /** Seed value for reproducibility. */
  seed?: number;
  /** Performance metrics (sharpe, drawdown, pnl, etc.). */
  metrics: Record<string, number> | null;
  /** Fold-specific metrics for cross-validation runs. */
  fold_metrics?: Record<string, Record<string, number>>;
  /** Objective value (the metric being optimized). */
  objective_value?: number | null;
  /** ISO-8601 timestamp. */
  created_at: string;
  /** ISO-8601 timestamp. */
  updated_at: string;
}

// ---------------------------------------------------------------------------
// Blocker / preflight types — Section 8.3
// ---------------------------------------------------------------------------

/**
 * Blocker detail record from backend.
 * Mirrors `BlockerDetail` Pydantic model in research.py.
 */
export interface BlockerDetail {
  /** Blocker code (e.g., "PREFLIGHT_FAILED", "MATERIAL_AMBIGUITY"). */
  code: string;
  /** Human-readable message. */
  message: string;
  /** Owner email or team responsible for resolving. */
  blocker_owner: string;
  /** Recommended next action. */
  next_step: string;
  /** Additional context. */
  metadata: Record<string, unknown>;
}

/** Preflight validation result — wraps blocker details. */
export interface PreflightResult {
  /** Whether preflight passed. */
  passed: boolean;
  /** List of blockers (empty if passed). */
  blockers: BlockerDetail[];
  /** ISO-8601 timestamp when preflight ran. */
  checked_at: string;
}

// ---------------------------------------------------------------------------
// Override watermark — Section 8.2
// ---------------------------------------------------------------------------

/** Override watermark metadata attached to runs under active overrides. */
export interface OverrideWatermark {
  /** Override request ULID. */
  override_id: string;
  /** Who approved the override. */
  approved_by: string;
  /** ISO-8601 timestamp of approval. */
  approved_at: string;
  /** Override reason/justification. */
  reason: string;
  /** Whether the override has been revoked. */
  revoked: boolean;
  /** ISO-8601 timestamp of revocation (null if still active). */
  revoked_at?: string | null;
}

// ---------------------------------------------------------------------------
// Optimization metrics — live progress display
// ---------------------------------------------------------------------------

/** Aggregated optimization progress metrics. */
export interface OptimizationMetrics {
  /** Total trials planned. */
  totalTrials: number;
  /** Trials completed so far. */
  completedTrials: number;
  /** Best objective value found so far. */
  bestObjectiveValue: number | null;
  /** Trial index of the best trial. */
  bestTrialIndex: number | null;
  /** Trials completed per minute (rolling average). */
  trialsPerMinute: number;
}

// ---------------------------------------------------------------------------
// Run submission payloads
// ---------------------------------------------------------------------------

/** Payload for POST /runs/research. */
export interface ResearchRunSubmission {
  /** ULID of the strategy build to execute. */
  strategy_build_id: string;
  /** Run configuration (timeframe, instrument, date range, etc.). */
  config: Record<string, unknown>;
}

/** Payload for POST /runs/optimize. */
export interface OptimizationRunSubmission {
  /** ULID of the strategy build to execute. */
  strategy_build_id: string;
  /** Optimization parameters (objective, search space, max trials). */
  config: Record<string, unknown>;
  /** Maximum number of trials to run. */
  max_trials: number;
}

// ---------------------------------------------------------------------------
// Polling configuration constants — Section 8.1
// ---------------------------------------------------------------------------

/** Initial polling interval in milliseconds (2 seconds per spec §8.1). */
export const INITIAL_POLL_INTERVAL_MS = 2_000;

/** Maximum polling interval cap in milliseconds (30 seconds per spec §8.1). */
export const MAX_POLL_INTERVAL_MS = 30_000;

/** Backoff multiplier for exponential polling. */
export const POLL_BACKOFF_MULTIPLIER = 2;

/**
 * Threshold in milliseconds after which the UI should show a stale-data
 * indicator following a poll failure (5 seconds per spec §8.1).
 */
export const STALE_INDICATOR_THRESHOLD_MS = 5_000;

// ---------------------------------------------------------------------------
// Blocker code registry — Section 8.3 plain-language copy
// ---------------------------------------------------------------------------

/** Registry entry for a known blocker code. */
export interface BlockerCodeEntry {
  /** Human-readable plain language copy. */
  plainLanguage: string;
  /** Key for the recommended next step action. */
  nextStepKey: string;
  /** Description of what the next step entails. */
  nextStepDescription: string;
}

/** Known blocker codes from spec §8.3. */
export const BLOCKER_CODE_REGISTRY: Record<string, BlockerCodeEntry> = {
  MATERIAL_AMBIGUITY: {
    plainLanguage: "This strategy has unresolved ambiguity that would materially change results.",
    nextStepKey: "resolve_uncertainty",
    nextStepDescription: "Open the uncertainty ledger and resolve flagged items.",
  },
  HOLDOUT_CONTAMINATED: {
    plainLanguage: "This strategy's holdout window has already been used and cannot be re-used.",
    nextStepKey: "designate_new_holdout",
    nextStepDescription: "Designate a new holdout window for this strategy build.",
  },
  DATASET_UNCERTIFIED: {
    plainLanguage: "One or more required datasets are not certified.",
    nextStepKey: "view_certification",
    nextStepDescription: "Open the data certification page for the blocked dataset.",
  },
  PREFLIGHT_FAILED: {
    plainLanguage: "Pre-run validation did not pass.",
    nextStepKey: "view_preflight",
    nextStepDescription: "Review the preflight report for specific rejection reasons.",
  },
  PENDING_APPROVAL: {
    plainLanguage: "This action is waiting for approver review.",
    nextStepKey: "view_approval",
    nextStepDescription: "Open the approval request to check its status.",
  },
  SEPARATION_OF_DUTIES: {
    plainLanguage: "The person who submitted this request cannot also approve it.",
    nextStepKey: "contact_approver",
    nextStepDescription: "A different approver must act on this request.",
  },
  OVERRIDE_REQUIRED: {
    plainLanguage: "A governance gate blocks this action.",
    nextStepKey: "request_override",
    nextStepDescription: "Submit an override request with evidence link and rationale.",
  },
  READINESS_GRADE_F: {
    plainLanguage: "This strategy did not meet minimum readiness thresholds.",
    nextStepKey: "view_readiness_breakdown",
    nextStepDescription: "Review the scoring breakdown and address the failing dimensions.",
  },
} as const;
