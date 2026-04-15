/**
 * Governance feature error hierarchy — typed exceptions per CLAUDE.md §9.
 *
 * Purpose:
 *   Domain-specific error types for the Governance Workflows feature
 *   (approvals, overrides, promotions). Enables precise error handling,
 *   retry classification, and user-facing error messages.
 *
 * Responsibilities:
 *   - Define error classes for not-found, auth, validation, network,
 *     and separation-of-duties failures.
 *   - Classify transient vs permanent errors for retry logic.
 *   - Provide toJSON() for Sentry error reporting.
 *
 * Does NOT:
 *   - Contain business logic or UI rendering.
 *   - Import component-layer code.
 *
 * Dependencies:
 *   - None (pure error types).
 *
 * Example:
 *   import { GovernanceAuthError, isTransientError } from "@/features/governance/errors";
 *   if (isTransientError(err)) { // retry }
 */

// ---------------------------------------------------------------------------
// Base error
// ---------------------------------------------------------------------------

/**
 * Base error for all governance feature errors.
 *
 * Carries entityId for correlation across the feature (approval ID,
 * override ID, or promotion ID depending on context).
 */
export class GovernanceError extends Error {
  constructor(
    message: string,
    public readonly entityId: string,
    public readonly cause?: unknown,
  ) {
    super(message);
    this.name = "GovernanceError";
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
export class GovernanceNotFoundError extends GovernanceError {
  constructor(entityId: string, cause?: unknown) {
    super(`Governance entity not found: ${entityId}`, entityId, cause);
    this.name = "GovernanceNotFoundError";
  }
}

// ---------------------------------------------------------------------------
// Auth errors
// ---------------------------------------------------------------------------

/** Authentication or authorization failure (HTTP 401/403). */
export class GovernanceAuthError extends GovernanceError {
  constructor(
    entityId: string,
    public readonly statusCode: 401 | 403,
    cause?: unknown,
  ) {
    const reason = statusCode === 401 ? "Authentication required" : "Permission denied";
    super(`${reason} for governance operation (entity ${entityId})`, entityId, cause);
    this.name = "GovernanceAuthError";
  }

  override toJSON(): Record<string, unknown> {
    return { ...super.toJSON(), statusCode: this.statusCode };
  }
}

// ---------------------------------------------------------------------------
// Validation
// ---------------------------------------------------------------------------

/** Zod schema validation failure on API response. */
export class GovernanceValidationError extends GovernanceError {
  constructor(
    entityId: string,
    public readonly issues: unknown[],
    cause?: unknown,
  ) {
    super(`Governance schema validation failed (${issues.length} issue(s))`, entityId, cause);
    this.name = "GovernanceValidationError";
  }

  override toJSON(): Record<string, unknown> {
    return { ...super.toJSON(), issueCount: this.issues.length };
  }
}

// ---------------------------------------------------------------------------
// Network
// ---------------------------------------------------------------------------

/** Network or server error during governance API call. */
export class GovernanceNetworkError extends GovernanceError {
  constructor(
    entityId: string,
    public readonly statusCode?: number,
    cause?: unknown,
  ) {
    const statusInfo = statusCode ? ` (status: ${statusCode})` : "";
    super(`Network error in governance operation${statusInfo}`, entityId, cause);
    this.name = "GovernanceNetworkError";
  }

  override toJSON(): Record<string, unknown> {
    return { ...super.toJSON(), statusCode: this.statusCode };
  }
}

// ---------------------------------------------------------------------------
// Separation of duties
// ---------------------------------------------------------------------------

/**
 * SoD violation — submitter attempted to act as reviewer on their own request.
 *
 * This maps from HTTP 409 Conflict returned by the backend when
 * reviewer_id === requested_by.
 */
export class GovernanceSoDError extends GovernanceError {
  constructor(entityId: string, cause?: unknown) {
    super(
      `Separation of duties violation: you cannot review your own request (${entityId})`,
      entityId,
      cause,
    );
    this.name = "GovernanceSoDError";
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
 *
 * Args:
 *   error: Any error from the governance feature.
 *
 * Returns:
 *   true if the error is transient and should be retried.
 */
export function isTransientError(error: unknown): boolean {
  if (error instanceof GovernanceNotFoundError) return false;
  if (error instanceof GovernanceAuthError) return false;
  if (error instanceof GovernanceValidationError) return false;
  if (error instanceof GovernanceSoDError) return false;
  if (error instanceof GovernanceNetworkError) {
    const code = error.statusCode;
    if (!code) return true; // Network-level failure (no response)
    return code === 429 || code >= 500;
  }
  return false;
}
