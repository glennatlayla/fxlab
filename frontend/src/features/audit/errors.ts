/**
 * Audit feature error hierarchy — typed exceptions per CLAUDE.md §9.
 *
 * Purpose:
 *   Domain-specific error types for the Audit Explorer feature (M30).
 *   Enables precise error handling, retry classification, and user-facing
 *   error messages.
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
 *   import { AuditAuthError, isTransientAuditError } from "@/features/audit/errors";
 *   if (isTransientAuditError(err)) { // retry }
 */

// ---------------------------------------------------------------------------
// Base error
// ---------------------------------------------------------------------------

/**
 * Base error for all audit feature errors.
 *
 * Carries entityId for correlation (audit event ID or "list" for collection ops).
 */
export class AuditError extends Error {
  constructor(
    message: string,
    public readonly entityId: string,
    public readonly cause?: unknown,
  ) {
    super(message);
    this.name = "AuditError";
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
export class AuditNotFoundError extends AuditError {
  constructor(entityId: string, cause?: unknown) {
    super(`Audit event not found: ${entityId}`, entityId, cause);
    this.name = "AuditNotFoundError";
  }
}

// ---------------------------------------------------------------------------
// Auth errors
// ---------------------------------------------------------------------------

/** Authentication or authorization failure (HTTP 401/403). */
export class AuditAuthError extends AuditError {
  constructor(
    entityId: string,
    public readonly statusCode: 401 | 403,
    cause?: unknown,
  ) {
    const reason = statusCode === 401 ? "Authentication required" : "Permission denied";
    super(`${reason} for audit operation (entity ${entityId})`, entityId, cause);
    this.name = "AuditAuthError";
  }

  override toJSON(): Record<string, unknown> {
    return { ...super.toJSON(), statusCode: this.statusCode };
  }
}

// ---------------------------------------------------------------------------
// Validation
// ---------------------------------------------------------------------------

/** Zod schema validation failure on API response. */
export class AuditValidationError extends AuditError {
  constructor(
    entityId: string,
    public readonly issues: unknown[],
    cause?: unknown,
  ) {
    super(`Audit schema validation failed (${issues.length} issue(s))`, entityId, cause);
    this.name = "AuditValidationError";
  }

  override toJSON(): Record<string, unknown> {
    return { ...super.toJSON(), issueCount: this.issues.length };
  }
}

// ---------------------------------------------------------------------------
// Network
// ---------------------------------------------------------------------------

/** Network or server error during audit API call. */
export class AuditNetworkError extends AuditError {
  constructor(
    entityId: string,
    public readonly statusCode?: number,
    cause?: unknown,
  ) {
    const statusInfo = statusCode ? ` (status: ${statusCode})` : "";
    super(`Network error in audit operation${statusInfo}`, entityId, cause);
    this.name = "AuditNetworkError";
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
export function isTransientAuditError(error: unknown): boolean {
  if (error instanceof AuditNotFoundError) return false;
  if (error instanceof AuditAuthError) return false;
  if (error instanceof AuditValidationError) return false;
  if (error instanceof AuditNetworkError) {
    const code = error.statusCode;
    if (!code) return true; // Network-level failure (no response)
    return code === 429 || code >= 500;
  }
  return false;
}
