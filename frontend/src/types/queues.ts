/**
 * Queues feature Zod schemas and TypeScript types.
 *
 * Purpose:
 *   Define validated schemas for the M30 Operator Dashboard queue monitoring,
 *   queue snapshots, and contention analysis responses. Mirrors backend
 *   Pydantic contracts in libs/contracts/queues.py.
 *
 * Responsibilities:
 *   - Zod schemas for runtime validation of API responses.
 *   - TypeScript types inferred from Zod schemas via z.infer.
 *   - Enum values for queue class identifiers.
 *
 * Does NOT:
 *   - Contain business logic, rendering, or I/O.
 *   - Import from component or service layers.
 *
 * Dependencies:
 *   - zod for schema validation.
 *
 * Example:
 *   import { QueueListResponseSchema, type QueueListResponse } from "@/types/queues";
 *   const parsed = QueueListResponseSchema.safeParse(response.data);
 */

import { z } from "zod";

// ---------------------------------------------------------------------------
// Queue snapshot — single point-in-time observation of a queue
// ---------------------------------------------------------------------------

/**
 * Single queue snapshot record.
 *
 * Mirrors QueueSnapshotResponse from backend contracts.
 * Represents a point-in-time observation of a queue's depth, contention,
 * and metadata.
 */
export const QueueSnapshotSchema = z.object({
  id: z.string().min(1),
  queue_name: z.string().min(1),
  timestamp: z.string().datetime({ offset: true }),
  depth: z.number().int().nonnegative(),
  contention_score: z.number().min(0).max(100),
  metadata: z.record(z.string(), z.unknown()).default({}),
  created_at: z.string().datetime({ offset: true }),
});
export type QueueSnapshot = z.infer<typeof QueueSnapshotSchema>;

// ---------------------------------------------------------------------------
// Queue contention — current queue state and contention metrics
// ---------------------------------------------------------------------------

/**
 * Queue contention and load metrics for a specific queue class.
 *
 * Mirrors QueueContentionResponse from backend contracts.
 * Provides the authoritative contention score, depth, running job count,
 * and failed job count for a queue class.
 */
export const QueueContentionSchema = z.object({
  queue_class: z.string().min(1),
  depth: z.number().int().nonnegative(),
  running: z.number().int().nonnegative(),
  failed: z.number().int().nonnegative(),
  contention_score: z.number().min(0).max(100),
  generated_at: z.string().datetime({ offset: true }),
});
export type QueueContention = z.infer<typeof QueueContentionSchema>;

// ---------------------------------------------------------------------------
// Queue list response — all queues in the system
// ---------------------------------------------------------------------------

/**
 * Complete queue list with all snapshots.
 *
 * Mirrors QueueListResponse from backend contracts.
 * The UI MUST treat this as the authoritative source of queue state at
 * the reported timestamp.
 */
export const QueueListResponseSchema = z.object({
  queues: z.array(QueueSnapshotSchema).default([]),
  generated_at: z.string().datetime({ offset: true }),
});
export type QueueListResponse = z.infer<typeof QueueListResponseSchema>;
