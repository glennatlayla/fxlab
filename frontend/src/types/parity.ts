/**
 * Parity feature Zod schemas and TypeScript types.
 *
 * Purpose:
 *   Define validated schemas for the Phase 3 Parity Dashboard. Mirrors
 *   backend contracts for parity events, instrument summaries, and parity
 *   responses.
 *
 * Responsibilities:
 *   - Zod schemas for runtime validation of parity API responses.
 *   - TypeScript types inferred from Zod schemas via z.infer.
 *   - Enum values for parity event severity levels.
 *
 * Does NOT:
 *   - Contain business logic, rendering, or I/O.
 *   - Import from component or service layers.
 *
 * Dependencies:
 *   - zod for schema validation.
 *
 * Example:
 *   import { ParityEventListSchema, type ParityEventList } from "@/types/parity";
 *   const parsed = ParityEventListSchema.safeParse(response.data);
 */

import { z } from "zod";

// ---------------------------------------------------------------------------
// Enums
// ---------------------------------------------------------------------------

/** Parity event severity — mirrors backend ParityEventSeverity. */
export const ParityEventSeverity = {
  INFO: "INFO",
  WARNING: "WARNING",
  CRITICAL: "CRITICAL",
} as const;
export type ParityEventSeverity = (typeof ParityEventSeverity)[keyof typeof ParityEventSeverity];
export const ParityEventSeveritySchema = z.enum(["INFO", "WARNING", "CRITICAL"]);

// ---------------------------------------------------------------------------
// Parity events
// ---------------------------------------------------------------------------

/**
 * Parity event — detected discrepancy between official and shadow feed.
 *
 * Mirrors backend ParityEvent model.
 */
export const ParityEventSchema = z.object({
  id: z.string().min(1),
  feed_id_official: z.string().min(1),
  feed_id_shadow: z.string().min(1),
  instrument: z.string().min(1),
  timestamp: z.string().datetime({ offset: true }),
  delta: z.number(),
  delta_pct: z.number(),
  severity: ParityEventSeveritySchema,
  detected_at: z.string().datetime({ offset: true }),
});
export type ParityEvent = z.infer<typeof ParityEventSchema>;

/**
 * Paginated parity events list response.
 *
 * Mirrors backend ParityEventList model.
 */
export const ParityEventListSchema = z.object({
  events: z.array(ParityEventSchema),
  total_count: z.number().int().nonnegative(),
  generated_at: z.string().datetime({ offset: true }),
});
export type ParityEventList = z.infer<typeof ParityEventListSchema>;

// ---------------------------------------------------------------------------
// Parity summary
// ---------------------------------------------------------------------------

/**
 * Summary of parity events by instrument.
 *
 * Mirrors backend ParityInstrumentSummary model.
 */
export const ParityInstrumentSummarySchema = z.object({
  instrument: z.string().min(1),
  event_count: z.number().int().nonnegative(),
  critical_count: z.number().int().nonnegative(),
  warning_count: z.number().int().nonnegative(),
  info_count: z.number().int().nonnegative(),
  worst_severity: z.string(), // Can be empty string if no events
});
export type ParityInstrumentSummary = z.infer<typeof ParityInstrumentSummarySchema>;

/**
 * Overall parity summary response.
 *
 * Mirrors backend ParitySummaryResponse model.
 */
export const ParitySummaryResponseSchema = z.object({
  summaries: z.array(ParityInstrumentSummarySchema),
  total_event_count: z.number().int().nonnegative(),
  generated_at: z.string().datetime({ offset: true }),
});
export type ParitySummaryResponse = z.infer<typeof ParitySummaryResponseSchema>;
