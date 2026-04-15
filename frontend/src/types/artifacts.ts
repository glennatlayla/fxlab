/**
 * Artifacts feature Zod schemas and TypeScript types.
 *
 * Purpose:
 *   Define validated schemas for artifact query responses and downloads.
 *   Mirrors backend Pydantic contracts in the artifacts module.
 *
 * Responsibilities:
 *   - Zod schemas for runtime validation of API responses.
 *   - TypeScript types inferred from Zod schemas via z.infer.
 *   - Enum values for artifact types.
 *
 * Does NOT:
 *   - Contain business logic, rendering, or I/O.
 *   - Import from component or service layers.
 *
 * Dependencies:
 *   - zod for schema validation.
 *
 * Example:
 *   import { ArtifactQueryResponseSchema, type ArtifactQueryResponse } from "@/types/artifacts";
 *   const parsed = ArtifactQueryResponseSchema.safeParse(response.data);
 */

import { z } from "zod";

// ---------------------------------------------------------------------------
// Enums
// ---------------------------------------------------------------------------

/** Artifact type enumeration — mirrors backend ArtifactType. */
export const ArtifactType = {
  COMPILED_STRATEGY: "compiled_strategy",
  BACKTEST_RESULT: "backtest_result",
  OPTIMIZATION_RESULT: "optimization_result",
  HOLDOUT_RESULT: "holdout_result",
  READINESS_REPORT: "readiness_report",
  EXPORT_BUNDLE: "export_bundle",
} as const;
export type ArtifactType = (typeof ArtifactType)[keyof typeof ArtifactType];
export const ArtifactTypeSchema = z.enum([
  "compiled_strategy",
  "backtest_result",
  "optimization_result",
  "holdout_result",
  "readiness_report",
  "export_bundle",
]);

// ---------------------------------------------------------------------------
// Artifact core
// ---------------------------------------------------------------------------

/** Artifact record — mirrors backend Artifact model. */
export const ArtifactSchema = z.object({
  id: z.string().min(1),
  artifact_type: ArtifactTypeSchema,
  subject_id: z.string().min(1),
  storage_path: z.string().min(1),
  size_bytes: z.number().int().nonnegative(),
  created_at: z.string().datetime({ offset: true }),
  created_by: z.string().min(1),
  metadata: z.record(z.string(), z.string()).default({}),
});
export type Artifact = z.infer<typeof ArtifactSchema>;

/** Paginated artifact query response — mirrors backend ArtifactQueryResponse. */
export const ArtifactQueryResponseSchema = z.object({
  artifacts: z.array(ArtifactSchema),
  total_count: z.number().int().nonnegative(),
  limit: z.number().int().min(1),
  offset: z.number().int().nonnegative(),
});
export type ArtifactQueryResponse = z.infer<typeof ArtifactQueryResponseSchema>;
