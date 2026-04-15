/**
 * Diagnostics feature Zod schemas and TypeScript types.
 *
 * Purpose:
 *   Define validated schemas for the Phase 3 DiagnosticsShell endpoints:
 *   GET /health, GET /health/dependencies, GET /health/diagnostics.
 *   Mirrors backend Pydantic contracts in libs/contracts/observability.py
 *   and services/api/routes/health.py.
 *
 * Responsibilities:
 *   - Zod schemas for runtime validation of API responses.
 *   - TypeScript types inferred from Zod schemas via z.infer.
 *   - Enum values for dependency status.
 *
 * Does NOT:
 *   - Contain business logic, rendering, or I/O.
 *   - Import from component or service layers.
 *
 * Dependencies:
 *   - zod for schema validation.
 *
 * Example:
 *   import { DependencyHealthResponseSchema, type DependencyHealthResponse } from "@/types/diagnostics";
 *   const parsed = DependencyHealthResponseSchema.safeParse(response.data);
 */

import { z } from "zod";

// ---------------------------------------------------------------------------
// Enums
// ---------------------------------------------------------------------------

/** Dependency reachability status — mirrors libs.contracts.observability.DependencyStatus. */
export const DependencyStatus = {
  OK: "OK",
  DEGRADED: "DEGRADED",
  DOWN: "DOWN",
} as const;
export type DependencyStatus = (typeof DependencyStatus)[keyof typeof DependencyStatus];
export const DependencyStatusSchema = z.enum(["OK", "DEGRADED", "DOWN"]);

// ---------------------------------------------------------------------------
// Service health (GET /health)
// ---------------------------------------------------------------------------

/** Service health response — mirrors /health endpoint. */
export const ServiceHealthSchema = z.object({
  status: z.string().min(1),
  service: z.string().min(1),
  version: z.string().optional(),
  components: z.record(z.string(), z.unknown()).optional(),
});
export type ServiceHealth = z.infer<typeof ServiceHealthSchema>;

// ---------------------------------------------------------------------------
// Dependency health (GET /health/dependencies)
// ---------------------------------------------------------------------------

/** Single dependency health check — mirrors DependencyHealthRecord. */
export const DependencyHealthRecordSchema = z.object({
  name: z.string().min(1),
  status: DependencyStatusSchema,
  latency_ms: z.number().nonnegative().default(0),
  detail: z.string().default(""),
});
export type DependencyHealthRecord = z.infer<typeof DependencyHealthRecordSchema>;

/** Aggregate dependency health — mirrors DependencyHealthResponse. */
export const DependencyHealthResponseSchema = z.object({
  dependencies: z.array(DependencyHealthRecordSchema).default([]),
  overall_status: z.string().default(""),
  generated_at: z.string().datetime({ offset: true }),
});
export type DependencyHealthResponse = z.infer<typeof DependencyHealthResponseSchema>;

// ---------------------------------------------------------------------------
// Diagnostics snapshot (GET /health/diagnostics)
// ---------------------------------------------------------------------------

/** Platform operational counts — mirrors DiagnosticsSnapshot. */
export const DiagnosticsSnapshotSchema = z.object({
  queue_contention_count: z.number().int().nonnegative(),
  feed_health_count: z.number().int().nonnegative(),
  parity_critical_count: z.number().int().nonnegative(),
  certification_blocked_count: z.number().int().nonnegative(),
  generated_at: z.string().datetime({ offset: true }),
});
export type DiagnosticsSnapshot = z.infer<typeof DiagnosticsSnapshotSchema>;
