/**
 * Readiness report types — TypeScript contracts for M28.
 *
 * Purpose:
 *   Define all data shapes for the readiness evaluation surface:
 *   reports, grades, blockers, scoring dimensions, holdout evaluation,
 *   regime consistency, and override watermarks.
 *
 * Responsibilities:
 *   - Type safety for readiness API responses.
 *   - Zod validation schemas for runtime parsing.
 *   - Grade-level type narrowing for conditional rendering.
 *
 * Does NOT:
 *   - Contain rendering logic.
 *   - Import component-layer code.
 *
 * Dependencies:
 *   - zod for runtime validation.
 */

import { z } from "zod";

// ---------------------------------------------------------------------------
// Grade enum — A through F per Phase 2 §8.4
// ---------------------------------------------------------------------------

/**
 * Readiness grade per Phase 2 §8.4 scoring methodology.
 *
 * Determined by the minimum sub-score across six dimensions.
 * Grade F blocks all promotion workflows.
 */
export const ReadinessGrade = {
  A: "A",
  B: "B",
  C: "C",
  D: "D",
  F: "F",
} as const;

export type ReadinessGrade = (typeof ReadinessGrade)[keyof typeof ReadinessGrade];

// ---------------------------------------------------------------------------
// Blocker detail
// ---------------------------------------------------------------------------

/**
 * A single blocker preventing production promotion.
 *
 * Blocker copy must be actionable for non-technical users.
 * Owners are team names or role identifiers, not emails.
 */
export interface ReadinessBlocker {
  /** Machine-readable blocker code (e.g., "HOLDOUT_FAIL"). */
  code: string;
  /** Human-readable blocker description. */
  message: string;
  /** Team or role responsible for resolution. */
  blocker_owner: string;
  /** Concrete action to resolve this blocker. */
  next_step: string;
  /** Blocker severity. */
  severity: "critical" | "high" | "medium" | "low";
  /** Optional additional context. */
  metadata?: Record<string, unknown>;
}

// ---------------------------------------------------------------------------
// Scoring evidence — per-dimension breakdown
// ---------------------------------------------------------------------------

/**
 * Scoring evidence for a single readiness dimension.
 *
 * Six dimensions per Phase 2 §8.4:
 *   oos_stability, drawdown, trade_count,
 *   holdout_pass, regime_consistency, parameter_stability
 */
export interface ScoringDimension {
  /** Dimension key (e.g., "oos_stability"). */
  dimension: string;
  /** Human-readable dimension label. */
  label: string;
  /** Normalized score 0-100. */
  score: number;
  /** Weight in overall grade (0-1). */
  weight: number;
  /** Grade F threshold for this dimension. */
  threshold: number;
  /** Whether this dimension passes. */
  passed: boolean;
  /** Supporting details / explanation. */
  details: string | null;
}

// ---------------------------------------------------------------------------
// Holdout evaluation
// ---------------------------------------------------------------------------

/** Holdout evaluation status for a backtest run. */
export interface HoldoutEvaluation {
  /** Whether holdout was evaluated. */
  evaluated: boolean;
  /** Whether holdout passed (Sharpe > 0, no contamination). */
  passed: boolean;
  /** Holdout period start date (ISO-8601). */
  start_date: string | null;
  /** Holdout period end date (ISO-8601). */
  end_date: string | null;
  /** Whether contamination was detected. */
  contamination_detected: boolean;
  /** Holdout Sharpe ratio. */
  sharpe_ratio: number | null;
}

// ---------------------------------------------------------------------------
// Regime consistency
// ---------------------------------------------------------------------------

/** Per-regime Sharpe ratio with pass/fail. */
export interface RegimeConsistencyEntry {
  /** Regime label (e.g., "bull", "bear", "sideways"). */
  regime: string;
  /** Sharpe ratio for this regime. */
  sharpe_ratio: number;
  /** Whether this regime passes (Sharpe > 0). */
  passed: boolean;
  /** Number of trades in this regime. */
  trade_count: number;
}

// ---------------------------------------------------------------------------
// Override watermark
// ---------------------------------------------------------------------------

/** Override watermark indicating an active governance override. */
export interface OverrideWatermark {
  /** Override ID. */
  override_id: string;
  /** Whether the override is currently active. */
  is_active: boolean;
  /** Override type. */
  override_type: "blocker_waiver" | "grade_override";
  /** Rationale for the override. */
  rationale: string;
  /** Evidence link URI. */
  evidence_link: string | null;
  /** ISO-8601 creation timestamp. */
  created_at: string;
}

// ---------------------------------------------------------------------------
// Report history entry
// ---------------------------------------------------------------------------

/** A historical readiness report entry. */
export interface ReadinessReportHistoryEntry {
  /** Report ID. */
  report_id: string;
  /** Grade at time of assessment. */
  grade: ReadinessGrade;
  /** Overall score 0-100. */
  score: number;
  /** ISO-8601 timestamp of assessment. */
  assessed_at: string;
  /** Policy version used. */
  policy_version: string;
  /** Who/what triggered the assessment. */
  assessor: string;
}

// ---------------------------------------------------------------------------
// Full readiness report payload
// ---------------------------------------------------------------------------

/** Complete readiness report for a backtest run. */
export interface ReadinessReportPayload {
  /** ULID of the assessed run. */
  run_id: string;
  /** Overall readiness grade (A-F). */
  grade: ReadinessGrade;
  /** Overall readiness score 0-100. */
  score: number;
  /** Policy version used for this assessment. */
  policy_version: string;
  /** Per-dimension scoring breakdown. */
  dimensions: ScoringDimension[];
  /** Blockers preventing promotion (non-empty when grade is F). */
  blockers: ReadinessBlocker[];
  /** Holdout evaluation status. */
  holdout: HoldoutEvaluation;
  /** Per-regime consistency entries. */
  regime_consistency: RegimeConsistencyEntry[];
  /** Override watermark if an active override applies. */
  override_watermark: OverrideWatermark | null;
  /** ISO-8601 timestamp of assessment. */
  assessed_at: string;
  /** Who/what performed the assessment. */
  assessor: string;
  /** Whether a pending promotion request exists for this run. */
  has_pending_promotion: boolean;
  /** Historical report entries (reverse chronological). */
  report_history: ReadinessReportHistoryEntry[];
}

// ---------------------------------------------------------------------------
// Zod schemas for runtime validation
// ---------------------------------------------------------------------------

export const ReadinessBlockerSchema = z.object({
  code: z.string(),
  message: z.string(),
  blocker_owner: z.string(),
  next_step: z.string(),
  severity: z.enum(["critical", "high", "medium", "low"]),
  metadata: z.record(z.string(), z.unknown()).optional(),
});

export const ScoringDimensionSchema = z.object({
  dimension: z.string(),
  label: z.string(),
  score: z.number().min(0).max(100),
  weight: z.number().min(0).max(1),
  threshold: z.number().min(0).max(100),
  passed: z.boolean(),
  details: z.string().nullable(),
});

export const HoldoutEvaluationSchema = z.object({
  evaluated: z.boolean(),
  passed: z.boolean(),
  start_date: z.string().nullable(),
  end_date: z.string().nullable(),
  contamination_detected: z.boolean(),
  sharpe_ratio: z.number().nullable(),
});

export const RegimeConsistencyEntrySchema = z.object({
  regime: z.string(),
  sharpe_ratio: z.number(),
  passed: z.boolean(),
  trade_count: z.number().int(),
});

export const OverrideWatermarkSchema = z.object({
  override_id: z.string(),
  is_active: z.boolean(),
  override_type: z.enum(["blocker_waiver", "grade_override"]),
  rationale: z.string(),
  evidence_link: z.string().nullable(),
  created_at: z.string(),
});

export const ReportHistoryEntrySchema = z.object({
  report_id: z.string(),
  grade: z.enum(["A", "B", "C", "D", "F"]),
  score: z.number().min(0).max(100),
  assessed_at: z.string(),
  policy_version: z.string(),
  assessor: z.string(),
});

export const ReadinessReportPayloadSchema = z.object({
  run_id: z.string(),
  grade: z.enum(["A", "B", "C", "D", "F"]),
  score: z.number().min(0).max(100),
  policy_version: z.string(),
  dimensions: z.array(ScoringDimensionSchema),
  blockers: z.array(ReadinessBlockerSchema),
  holdout: HoldoutEvaluationSchema,
  regime_consistency: z.array(RegimeConsistencyEntrySchema),
  override_watermark: OverrideWatermarkSchema.nullable(),
  assessed_at: z.string(),
  assessor: z.string(),
  has_pending_promotion: z.boolean(),
  report_history: z.array(ReportHistoryEntrySchema),
});

/** Schema for promotion submission response — validates server response. */
export const PromotionResponseSchema = z.object({
  promotion_id: z.string(),
});
