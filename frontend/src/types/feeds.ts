/**
 * Feeds feature Zod schemas and TypeScript types.
 *
 * Purpose:
 *   Define validated schemas for the Phase 3 Feed Registry, feed health,
 *   anomaly and parity responses. Mirrors backend Pydantic contracts in
 *   libs/contracts/feed.py and libs/contracts/feed_health.py.
 *
 * Responsibilities:
 *   - Zod schemas for runtime validation of API responses.
 *   - TypeScript types inferred from Zod schemas via z.infer.
 *   - Enum values for connectivity status, feed health status, anomaly types.
 *
 * Does NOT:
 *   - Contain business logic, rendering, or I/O.
 *   - Import from component or service layers.
 *
 * Dependencies:
 *   - zod for schema validation.
 *
 * Example:
 *   import { FeedListResponseSchema, type FeedListResponse } from "@/types/feeds";
 *   const parsed = FeedListResponseSchema.safeParse(response.data);
 */

import { z } from "zod";

// ---------------------------------------------------------------------------
// Enums
// ---------------------------------------------------------------------------

/** Connectivity test status — mirrors libs.contracts.feed.ConnectivityStatus. */
export const ConnectivityStatus = {
  OK: "ok",
  FAILED: "failed",
  TIMEOUT: "timeout",
} as const;
export type ConnectivityStatus = (typeof ConnectivityStatus)[keyof typeof ConnectivityStatus];
export const ConnectivityStatusSchema = z.enum(["ok", "failed", "timeout"]);

/** Feed health status — mirrors libs.contracts.feed_health.FeedHealthStatus. */
export const FeedHealthStatus = {
  HEALTHY: "healthy",
  DEGRADED: "degraded",
  QUARANTINED: "quarantined",
  OFFLINE: "offline",
} as const;
export type FeedHealthStatus = (typeof FeedHealthStatus)[keyof typeof FeedHealthStatus];
export const FeedHealthStatusSchema = z.enum(["healthy", "degraded", "quarantined", "offline"]);

/** Anomaly classification — mirrors libs.contracts.feed_health.AnomalyType. */
export const AnomalyType = {
  GAP: "gap",
  SPIKE: "spike",
  STALE: "stale",
  DUPLICATE: "duplicate",
  OUT_OF_ORDER: "out_of_order",
} as const;
export type AnomalyType = (typeof AnomalyType)[keyof typeof AnomalyType];
export const AnomalyTypeSchema = z.enum(["gap", "spike", "stale", "duplicate", "out_of_order"]);

// ---------------------------------------------------------------------------
// Feed core
// ---------------------------------------------------------------------------

/** Feed registry record — mirrors FeedResponse. */
export const FeedResponseSchema = z.object({
  id: z.string().min(1),
  name: z.string().min(1),
  provider: z.string().min(1),
  config: z.record(z.string(), z.unknown()),
  is_active: z.boolean(),
  is_quarantined: z.boolean(),
  created_at: z.string().datetime({ offset: true }),
  updated_at: z.string().datetime({ offset: true }),
});
export type FeedResponse = z.infer<typeof FeedResponseSchema>;

/** Configuration version entry — mirrors FeedConfigVersion. */
export const FeedConfigVersionSchema = z.object({
  version: z.number().int().min(1),
  config: z.record(z.string(), z.unknown()),
  created_at: z.string().datetime({ offset: true }),
  created_by: z.string().min(1),
  change_summary: z.string().nullable().optional(),
});
export type FeedConfigVersion = z.infer<typeof FeedConfigVersionSchema>;

/** Connectivity test result — mirrors FeedConnectivityResult. */
export const FeedConnectivityResultSchema = z.object({
  id: z.string().min(1),
  feed_id: z.string().min(1),
  tested_at: z.string().datetime({ offset: true }),
  status: ConnectivityStatusSchema,
  latency_ms: z.number().int().nonnegative().nullable().optional(),
  error_message: z.string().nullable().optional(),
});
export type FeedConnectivityResult = z.infer<typeof FeedConnectivityResultSchema>;

/** Feed detail aggregate — mirrors FeedDetailResponse. */
export const FeedDetailResponseSchema = z.object({
  feed: FeedResponseSchema,
  version_history: z.array(FeedConfigVersionSchema).default([]),
  connectivity_tests: z.array(FeedConnectivityResultSchema).default([]),
});
export type FeedDetailResponse = z.infer<typeof FeedDetailResponseSchema>;

/** Paginated feed list response — mirrors FeedListResponse. */
export const FeedListResponseSchema = z.object({
  feeds: z.array(FeedResponseSchema),
  total_count: z.number().int().nonnegative(),
  limit: z.number().int().min(1),
  offset: z.number().int().nonnegative(),
});
export type FeedListResponse = z.infer<typeof FeedListResponseSchema>;

// ---------------------------------------------------------------------------
// Feed health & anomalies
// ---------------------------------------------------------------------------

/** Anomaly record — mirrors libs.contracts.feed_health.Anomaly. */
export const AnomalySchema = z.object({
  id: z.string().min(1),
  feed_id: z.string().min(1),
  anomaly_type: AnomalyTypeSchema,
  detected_at: z.string().datetime({ offset: true }),
  start_time: z.string().datetime({ offset: true }),
  end_time: z.string().datetime({ offset: true }).nullable().optional(),
  severity: z.string().min(1),
  message: z.string(),
  metadata: z.record(z.string(), z.string()).default({}),
});
export type Anomaly = z.infer<typeof AnomalySchema>;

/** Per-feed health report — mirrors FeedHealthReport. */
export const FeedHealthReportSchema = z.object({
  feed_id: z.string().min(1),
  status: FeedHealthStatusSchema,
  last_update: z.string().datetime({ offset: true }),
  recent_anomalies: z.array(AnomalySchema).default([]),
  quarantine_reason: z.string().nullable().optional(),
});
export type FeedHealthReport = z.infer<typeof FeedHealthReportSchema>;

/** Feed health list response — mirrors FeedHealthListResponse. */
export const FeedHealthListResponseSchema = z.object({
  feeds: z.array(FeedHealthReportSchema).default([]),
  generated_at: z.string().datetime({ offset: true }),
});
export type FeedHealthListResponse = z.infer<typeof FeedHealthListResponseSchema>;

// ---------------------------------------------------------------------------
// Parity
// ---------------------------------------------------------------------------

/** Parity issue — mirrors libs.contracts.feed_health.ParityIssue. */
export const ParityIssueSchema = z.object({
  id: z.string().min(1),
  feed_a_id: z.string().min(1),
  feed_b_id: z.string().min(1),
  symbol: z.string().min(1),
  detected_at: z.string().datetime({ offset: true }),
  discrepancy_type: z.string().min(1),
  message: z.string(),
  resolved: z.boolean(),
});
export type ParityIssue = z.infer<typeof ParityIssueSchema>;

export const ParityIssueListSchema = z.array(ParityIssueSchema);
