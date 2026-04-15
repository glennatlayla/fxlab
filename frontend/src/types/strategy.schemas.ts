/**
 * Zod runtime schemas for strategy domain types.
 *
 * Purpose:
 *   Validate API responses at runtime to catch malformed data before it
 *   enters the component tree. TypeScript types only protect at compile time;
 *   these schemas protect at runtime against deserialization errors,
 *   API contract violations, and data corruption.
 *
 * Responsibilities:
 *   - Define Zod schemas that mirror TypeScript interfaces in strategy.ts.
 *   - Provide runtime validation for API responses in strategy/api.ts.
 *   - Reject malformed or missing fields early.
 *
 * Does NOT:
 *   - Contain business logic.
 *   - Validate user input (form validation is in components).
 *   - Enforce nested payload structure (draft_payload accepts unknown objects).
 *
 * Usage:
 *   const response = await apiClient.post("/strategies/draft/autosave", payload);
 *   const validated = DraftAutosaveResponseSchema.parse(response.data);
 */

import { z } from "zod";

/**
 * Schema for POST /strategies/draft/autosave response.
 *
 * Maps to DraftAutosaveResponse interface.
 *   autosave_id: Server-assigned ULID for this autosave record.
 *   saved_at: Server-side ISO 8601 timestamp.
 */
export const DraftAutosaveResponseSchema = z.object({
  autosave_id: z.string(),
  saved_at: z.string(),
});

/**
 * Schema for GET /strategies/draft/autosave/latest response.
 *
 * Maps to DraftAutosaveRecord interface.
 * Validates the complete autosave record needed for session recovery.
 *
 *   draft_payload: Accepts any object (does not enforce StrategyDraftFormData shape).
 *   This allows partial payloads and future extensions.
 */
export const DraftAutosaveRecordSchema = z.object({
  id: z.string(),
  user_id: z.string(),
  draft_payload: z.any(),
  form_step: z.string(),
  session_id: z.string(),
  client_ts: z.string(),
  created_at: z.string(),
  updated_at: z.string(),
});
