/**
 * Zod runtime schemas for run domain types.
 *
 * Purpose:
 *   Validate API responses at runtime to catch malformed data before it
 *   enters the component tree. TypeScript types only protect at compile time;
 *   these schemas protect at runtime against deserialization errors,
 *   API contract violations, and data corruption.
 *
 * Responsibilities:
 *   - Define Zod schemas mirroring TypeScript interfaces in run.ts.
 *   - Provide runtime validation for all run-related API responses.
 *   - Reject malformed or missing fields early with clear error messages.
 *
 * Does NOT:
 *   - Contain business logic.
 *   - Validate user input (form validation is in components).
 *   - Enforce config/parameters internal structure (accepts unknown objects).
 *
 * Dependencies:
 *   - zod
 *
 * Usage:
 *   const response = await apiClient.get(`/runs/${runId}`);
 *   const validated = RunRecordSchema.parse(response.data);
 */

import { z } from "zod";

// ---------------------------------------------------------------------------
// Enum schemas
// ---------------------------------------------------------------------------

/** Runtime validation for RunType values. */
export const RunTypeSchema = z.enum(["research", "optimization"]);

/** Runtime validation for RunStatus values. */
export const RunStatusSchema = z.enum(["pending", "running", "complete", "failed", "cancelled"]);

/** Runtime validation for TrialStatus values. */
export const TrialStatusSchema = z.enum(["pending", "running", "completed", "failed"]);

// ---------------------------------------------------------------------------
// Blocker / Preflight schemas — Section 8.3
// ---------------------------------------------------------------------------

/**
 * Schema for BlockerDetail records from backend.
 *
 * Validates blocker code, message, owner, and next-step fields.
 * Metadata accepts any object to support future extensions.
 */
export const BlockerDetailSchema = z.object({
  code: z.string(),
  message: z.string(),
  blocker_owner: z.string(),
  next_step: z.string(),
  metadata: z.record(z.string(), z.unknown()),
});

/**
 * Schema for PreflightResult records.
 *
 * Validates the pass/fail flag, blocker list, and timestamp.
 */
export const PreflightResultSchema = z.object({
  passed: z.boolean(),
  blockers: z.array(BlockerDetailSchema),
  checked_at: z.string(),
});

// ---------------------------------------------------------------------------
// Override watermark schema — Section 8.2
// ---------------------------------------------------------------------------

/**
 * Schema for OverrideWatermark metadata attached to runs under active overrides.
 *
 * Validates approval chain fields and revocation status.
 */
export const OverrideWatermarkSchema = z.object({
  override_id: z.string(),
  approved_by: z.string(),
  approved_at: z.string(),
  reason: z.string(),
  revoked: z.boolean(),
  revoked_at: z.string().nullable().optional(),
});

// ---------------------------------------------------------------------------
// Trial record schema
// ---------------------------------------------------------------------------

/**
 * Schema for a single trial within a run.
 *
 * Validates trial identity, status, parameters, and metrics.
 * Parameters and metrics are typed as records to support any strategy schema.
 */
export const TrialRecordSchema = z.object({
  id: z.string(),
  run_id: z.string(),
  trial_index: z.number().int().nonnegative(),
  status: TrialStatusSchema,
  parameters: z.record(z.string(), z.unknown()),
  seed: z.number().int().optional(),
  metrics: z.record(z.string(), z.number()).nullable(),
  fold_metrics: z.record(z.string(), z.record(z.string(), z.number())).optional(),
  objective_value: z.number().nullable().optional(),
  created_at: z.string(),
  updated_at: z.string(),
});

// ---------------------------------------------------------------------------
// Run record schema — returned by GET /runs/{run_id}
// ---------------------------------------------------------------------------

/**
 * Schema for RunRecord as returned by the backend API.
 *
 * Validates all core fields plus optional live-progress fields that are
 * populated during execution. Config accepts any object to support both
 * research and optimization run configurations.
 */
export const RunRecordSchema = z.object({
  id: z.string(),
  strategy_build_id: z.string(),
  run_type: RunTypeSchema,
  status: RunStatusSchema,
  config: z.record(z.string(), z.unknown()),
  result_uri: z.string().nullable(),
  created_by: z.string(),
  created_at: z.string(),
  updated_at: z.string(),
  started_at: z.string().nullable(),
  completed_at: z.string().nullable(),

  // Live progress fields — optional, populated during execution
  trial_count: z.number().int().nonnegative().optional(),
  completed_trials: z.number().int().nonnegative().optional(),
  current_trial_params: z.record(z.string(), z.unknown()).nullable().optional(),
  error_message: z.string().nullable().optional(),
  cancellation_reason: z.string().nullable().optional(),
  override_watermarks: z.array(OverrideWatermarkSchema).optional(),
  preflight_results: z.array(PreflightResultSchema).optional(),
});

// ---------------------------------------------------------------------------
// Trial list response schema
// ---------------------------------------------------------------------------

/**
 * Schema for paginated trial list response.
 *
 * Validates the array of trials and pagination metadata.
 */
export const TrialListResponseSchema = z.object({
  trials: z.array(TrialRecordSchema),
  total: z.number().int().nonnegative(),
  offset: z.number().int().nonnegative(),
  limit: z.number().int().positive(),
});

// ---------------------------------------------------------------------------
// Run submission response schemas
// ---------------------------------------------------------------------------

/**
 * Schema for POST /runs/research and POST /runs/optimize responses.
 *
 * Backend returns the created run record on successful submission.
 */
export const RunSubmissionResponseSchema = RunRecordSchema;

// ---------------------------------------------------------------------------
// Inferred types (for consumers that want schema-derived types)
// ---------------------------------------------------------------------------

export type RunRecordParsed = z.infer<typeof RunRecordSchema>;
export type TrialRecordParsed = z.infer<typeof TrialRecordSchema>;
export type TrialListResponseParsed = z.infer<typeof TrialListResponseSchema>;
