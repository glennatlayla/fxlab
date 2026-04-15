/**
 * Queues feature error hierarchy — typed exceptions per CLAUDE.md §9.
 *
 * Purpose:
 *   Domain-specific error types for the Queues feature (queue snapshots,
 *   contention analysis). Enables precise error handling, retry classification,
 *   and user-facing error messages.
 *
 * Responsibilities:
 *   - Define error classes for not-found, auth, validation, network failures.
 *   - Classify transient vs permanent errors for retry logic.
 *   - Provide toJSON() for Sentry structured context.
 *
 * Does NOT:
 *   - Contain business logic or UI rendering.
 *   - Import component-layer code.
 *
 * Dependencies:
 *   - None (pure error types).
 *
 * Example:
 *   import { QueuesAuthError, isTransientQueuesError } from "@/features/queues/errors";
 *   if (isTransientQueuesError(err)) { // retry }
 */

// ---------------------------------------------------------------------------
// Base error
// ---------------------------------------------------------------------------

/**
 * Base error for all queues feature errors.
 *
 * Carries entityId for correlation across the feature (queue class, "list"
 * for collection operations).
 */
export class QueuesError extends Error {
  constructor(
    message: string,
    public readonly entityId: string,
    public readonly cause?: unknown,
  ) {
    super(message);
    this.name = "QueuesError";
  }

  /** Serialize for Sentry structured context. */
  toJSON(): Record<string, unknown> {
    return {
      name: this.name,
      message: this.message,
      entityId: this.entityId,
      cause: this.cause instanceof Error ? this.cause.message : this.cause,
    };
  }
}

// ---------------------------------------------------------------------------
// Not found
// ---------------------------------------------------------------------------

/** Entity does not exist (HTTP 404). */
export class QueuesNotFoundError extends QueuesError {
  constructor(entityId: string, cause?: unknown) {
    super(`Queues entity not found: ${entityId}`, entityId, cause);
    this.name = "QueuesNotFoundError";
  }
}

// ---------------------------------------------------------------------------
// Auth errors
// ---------------------------------------------------------------------------

/** Authentication or authorization failure (HTTP 401/403). */
export class QueuesAuthError extends QueuesError {
  constructor(
    entityId: string,
    public readonly statusCode: 401 | 403,
    cause?: unknown,
  ) {
    const reason = statusCode === 401 ? "Authentication required" : "Permission denied";
    super(`${reason} for queues operation (entity ${entityId})`, entityId, cause);
    this.name = "QueuesAuthError";
  }

  override toJSON(): Record<string, unknown> {
    return { ...super.toJSON(), statusCode: this.statusCode };
  }
}

// ---------------------------------------------------------------------------
// Validation
// ---------------------------------------------------------------------------

/** Zod schema validation failure on API response. */
export class QueuesValidationError extends QueuesError {
  constructor(
    entityId: string,
    public readonly issues: unknown[],
    cause?: unknown,
  ) {
    super(`Queues schema validation failed (${issues.length} issue(s))`, entityId, cause);
    this.name = "QueuesValidationError";
  }

  override toJSON(): Record<string, unknown> {
    return { ...super.toJSON(), issueCount: this.issues.length };
  }
}

// ---------------------------------------------------------------------------
// Network
// ---------------------------------------------------------------------------

/** Network or server error during queues API call. */
export class QueuesNetworkError extends QueuesError {
  constructor(
    entityId: string,
    public readonly statusCode?: number,
    cause?: unknown,
  ) {
    const statusInfo = statusCode ? ` (status: ${statusCode})` : "";
    super(`Network error in queues operation${statusInfo}`, entityId, cause);
    this.name = "QueuesNetworkError";
  }

  override toJSON(): Record<string, unknown> {
    return { ...super.toJSON(), statusCode: this.statusCode };
  }
}

// ---------------------------------------------------------------------------
// Transient classification
// ---------------------------------------------------------------------------

/**
 * Determine if an error is transient and eligible for retry.
 *
 * Per CLAUDE.md §9: retry on network timeouts, 429, 5xx.
 * Do NOT retry on 400, 401, 403, 404, 409.
 */
export function isTransientQueuesError(error: unknown): boolean {
  if (error instanceof QueuesNotFoundError) return false;
  if (error instanceof QueuesAuthError) return false;
  if (error instanceof QueuesValidationError) return false;
  if (error instanceof QueuesNetworkError) {
    const code = error.statusCode;
    if (!code) return true; // Network-level failure (no response)
    return code === 429 || code >= 500;
  }
  return false;
}
