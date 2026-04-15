/**
 * Audit feature Zod schemas and TypeScript types.
 *
 * Purpose:
 *   Define validated schemas for the Audit Explorer feature (M30),
 *   mirroring backend contracts for audit event records and paginated
 *   explorer responses.
 *
 * Responsibilities:
 *   - Zod schemas for runtime validation of audit API responses.
 *   - TypeScript types inferred from Zod schemas via z.infer.
 *
 * Does NOT:
 *   - Contain business logic, rendering, or I/O.
 *   - Import from component or service layers.
 *
 * Dependencies:
 *   - zod for schema validation.
 *
 * Example:
 *   import { AuditExplorerResponseSchema, type AuditExplorerResponse } from "@/types/audit";
 *   const parsed = AuditExplorerResponseSchema.safeParse(response.data);
 */

import { z } from "zod";

// ---------------------------------------------------------------------------
// Audit event record
// ---------------------------------------------------------------------------

/**
 * Individual audit event record — mirrors backend AuditEventRecord contract.
 *
 * Represents a single audited action: actor performing action on resource.
 * object_id and object_type may be empty strings for non-resource events.
 * correlation_id tracks distributed tracing; may be empty for local events.
 * event_metadata is a flexible dict capturing domain-specific event detail.
 */
export const AuditEventRecordSchema = z.object({
  id: z.string().min(1, "Audit event ID is required"),
  actor: z.string().min(1, "Actor name is required"),
  action: z.string().min(1, "Action type is required"),
  object_id: z.string().default(""),
  object_type: z.string().default(""),
  correlation_id: z.string().default(""),
  event_metadata: z.record(z.string(), z.unknown()).default({}),
  created_at: z.string().datetime({ offset: true }),
});

export type AuditEventRecord = z.infer<typeof AuditEventRecordSchema>;

// ---------------------------------------------------------------------------
// Audit explorer response
// ---------------------------------------------------------------------------

/**
 * Paginated audit explorer response — mirrors backend AuditExplorerResponse contract.
 *
 * Contains a page of audit events, pagination cursor, total event count,
 * and generation timestamp (server time; used to sync client state).
 *
 * next_cursor is empty string ("") when no further pages exist.
 */
export const AuditExplorerResponseSchema = z.object({
  events: z.array(AuditEventRecordSchema).default([]),
  next_cursor: z.string().default(""),
  total_count: z.number().int().nonnegative(),
  generated_at: z.string().datetime({ offset: true }),
});

export type AuditExplorerResponse = z.infer<typeof AuditExplorerResponseSchema>;
