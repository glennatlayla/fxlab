/**
 * Exports feature Zod schemas and TypeScript types.
 *
 * Purpose:
 *   Define validated schemas for export job lifecycle, export list,
 *   and export download responses. Mirrors backend contracts in
 *   libs/contracts/export.py.
 *
 * Responsibilities:
 *   - Zod schemas for runtime validation of API responses.
 *   - TypeScript types inferred from Zod schemas via z.infer.
 *   - Enum values for export type and status.
 *
 * Does NOT:
 *   - Contain business logic, rendering, or I/O.
 *   - Import from component or service layers.
 *
 * Dependencies:
 *   - zod for schema validation.
 *
 * Example:
 *   import { ExportJobResponseSchema, type ExportJobResponse } from "@/types/exports";
 *   const parsed = ExportJobResponseSchema.safeParse(response.data);
 */

import { z } from "zod";

// ---------------------------------------------------------------------------
// Enums
// ---------------------------------------------------------------------------

/** Export type classification — mirrors backend ExportType. */
export const ExportType = {
  TRADES: "trades",
  RUNS: "runs",
  ARTIFACTS: "artifacts",
} as const;
export type ExportType = (typeof ExportType)[keyof typeof ExportType];
export const ExportTypeSchema = z.enum(["trades", "runs", "artifacts"]);

/** Export job status — mirrors backend ExportStatus. */
export const ExportStatus = {
  PENDING: "pending",
  PROCESSING: "processing",
  COMPLETE: "complete",
  FAILED: "failed",
} as const;
export type ExportStatus = (typeof ExportStatus)[keyof typeof ExportStatus];
export const ExportStatusSchema = z.enum(["pending", "processing", "complete", "failed"]);

// ---------------------------------------------------------------------------
// Export job response
// ---------------------------------------------------------------------------

/** Override watermark metadata in an export. */
export const OverrideWatermarkSchema = z.record(z.string(), z.unknown());
export type OverrideWatermark = z.infer<typeof OverrideWatermarkSchema>;

/** Export job response — mirrors ExportJobResponse. */
export const ExportJobResponseSchema = z.object({
  id: z.string().min(1),
  export_type: ExportTypeSchema,
  object_id: z.string().min(1),
  status: ExportStatusSchema,
  artifact_uri: z.string().nullable().optional(),
  requested_by: z.string().min(1),
  created_at: z.string().datetime({ offset: true }),
  updated_at: z.string().datetime({ offset: true }),
  override_watermark: OverrideWatermarkSchema.nullable().optional(),
});
export type ExportJobResponse = z.infer<typeof ExportJobResponseSchema>;

// ---------------------------------------------------------------------------
// Export list response
// ---------------------------------------------------------------------------

/** List response for exports — mirrors ExportListResponse. */
export const ExportListResponseSchema = z.object({
  exports: z.array(ExportJobResponseSchema),
  total_count: z.number().int().nonnegative(),
});
export type ExportListResponse = z.infer<typeof ExportListResponseSchema>;
