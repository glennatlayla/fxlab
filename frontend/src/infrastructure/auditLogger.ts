/**
 * Client-side audit logger for strategy lifecycle events.
 *
 * Purpose:
 *   Log governance-relevant events (strategy creation, submission, approval actions)
 *   to the backend audit endpoint for regulatory compliance and governance auditing.
 *
 * Responsibilities:
 *   - Fire-and-forget POST to /audit/events.
 *   - Include actor (user ID), timestamp, correlation ID, event type, and optional metadata.
 *   - Never block user actions or navigation (async, non-throwing).
 *   - Gracefully degrade on network failures.
 *
 * Does NOT:
 *   - Replace server-side audit logging (this is defense in depth).
 *   - Store audit events locally or queue them on failure.
 *   - Require successful delivery (best-effort only).
 *   - Validate caller-provided metadata (accepts any Record<string, unknown>).
 *
 * Dependencies:
 *   - @/api/client: Pre-configured Axios instance with auth injection.
 *
 * Error handling:
 *   All errors are caught and logged to console.warn but not thrown.
 *   Failures do not block user workflow.
 *
 * Example usage:
 *   import { logAuditEvent } from "@/infrastructure/auditLogger";
 *
 *   // Send audit event with just event and actor
 *   await logAuditEvent("strategy.draft_created", userId);
 *
 *   // Send audit event with metadata
 *   await logAuditEvent("strategy.submitted", userId, {
 *     draft_id: "draft-123",
 *     strategy_name: "Golden Crossover",
 *   });
 */

import { apiClient } from "@/api/client";

/**
 * Enumeration of audit event types supported by the backend.
 *
 * Categories:
 *   - strategy.* : Strategy lifecycle events
 *   - auth.* : Authentication and session events
 */
export type AuditEventType =
  | "strategy.draft_created"
  | "strategy.draft_autosaved"
  | "strategy.draft_restored"
  | "strategy.draft_discarded"
  | "strategy.submitted"
  | "strategy.approved"
  | "strategy.rejected"
  | "auth.login"
  | "auth.logout"
  | "auth.session_restored";

/**
 * Internal shape of an audit event sent to the backend.
 *
 * All timestamps are ISO 8601.
 * The correlationId allows tracing an event across distributed systems.
 */
interface AuditEvent {
  /** Type of event that occurred. */
  event: AuditEventType;
  /** ULID or UUID of the user who triggered the event. */
  actor: string;
  /** ISO 8601 timestamp when the event was logged (client time). */
  timestamp: string;
  /** UUID for distributed tracing correlation. */
  correlationId: string;
  /** Optional domain-specific metadata. */
  metadata?: Record<string, unknown>;
}

/**
 * Log an audit event to the backend.
 *
 * This function is fire-and-forget: it sends the event asynchronously
 * and returns a resolved Promise even if the backend call fails. Failures
 * are logged locally for troubleshooting but do not propagate to the caller.
 *
 * Args:
 *   event: Type of event (must be one of AuditEventType union).
 *   actor: ULID or UUID of the user who triggered the event.
 *   metadata: Optional object with domain-specific context (draft ID, strategy name, etc.).
 *
 * Returns:
 *   A Promise that resolves to void. Never rejects; failures are logged only.
 *
 * Raises:
 *   Never. All errors are caught and logged to console.warn.
 *
 * Example:
 *   await logAuditEvent("strategy.draft_created", "user-123");
 *   await logAuditEvent("strategy.submitted", userId, { draft_id: "d-456" });
 */
export async function logAuditEvent(
  event: AuditEventType,
  actor: string,
  metadata?: Record<string, unknown>,
): Promise<void> {
  const auditEvent: AuditEvent = {
    event,
    actor,
    timestamp: new Date().toISOString(),
    correlationId: crypto.randomUUID(),
    ...(metadata && { metadata }),
  };

  try {
    await apiClient.post("/audit/events", auditEvent);
  } catch (error) {
    // Fire-and-forget: log locally but never block user flow.
    // This ensures a failed audit endpoint does not prevent strategy
    // operations or degrade the user experience.
    console.warn("[AuditLogger] Failed to send audit event", {
      event: auditEvent.event,
      actor: auditEvent.actor,
      error: error instanceof Error ? error.message : String(error),
    });
  }
}
