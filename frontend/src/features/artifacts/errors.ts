/**
 * Artifacts feature error hierarchy — typed exceptions per CLAUDE.md §9.
 *
 * Purpose:
 *   Domain-specific error types for the Artifacts feature (browsing, downloading).
 *   Enables precise error handling, retry classification, and user-facing error messages.
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
 *   import { ArtifactAuthError, isTransientArtifactError } from "@/features/artifacts/errors";
 *   if (isTransientArtifactError(err)) { // retry }
 */

// ---------------------------------------------------------------------------
// Base error
// ---------------------------------------------------------------------------

/**
 * Base error for all artifacts feature errors.
 *
 * Carries entityId for correlation across the feature (artifact ID, query ID,
 * or "list" for collection operations).
 */
export class ArtifactError extends Error {
  constructor(
    message: string,
    public readonly entityId: string,
    public readonly cause?: unknown,
  ) {
    super(message);
    this.name = "ArtifactError";
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
export class ArtifactNotFoundError extends ArtifactError {
  constructor(entityId: string, cause?: unknown) {
    super(`Artifact not found: ${entityId}`, entityId, cause);
    this.name = "ArtifactNotFoundError";
  }
}

// ---------------------------------------------------------------------------
// Auth errors
// ---------------------------------------------------------------------------

/** Authentication or authorization failure (HTTP 401/403). */
export class ArtifactAuthError extends ArtifactError {
  constructor(
    entityId: string,
    public readonly statusCode: 401 | 403,
    cause?: unknown,
  ) {
    const reason = statusCode === 401 ? "Authentication required" : "Permission denied";
    super(`${reason} for artifact operation (entity ${entityId})`, entityId, cause);
    this.name = "ArtifactAuthError";
  }

  override toJSON(): Record<string, unknown> {
    return { ...super.toJSON(), statusCode: this.statusCode };
  }
}

// ---------------------------------------------------------------------------
// Validation
// ---------------------------------------------------------------------------

/** Zod schema validation failure on API response. */
export class ArtifactValidationError extends ArtifactError {
  constructor(
    entityId: string,
    public readonly issues: unknown[],
    cause?: unknown,
  ) {
    super(`Artifact schema validation failed (${issues.length} issue(s))`, entityId, cause);
    this.name = "ArtifactValidationError";
  }

  override toJSON(): Record<string, unknown> {
    return { ...super.toJSON(), issueCount: this.issues.length };
  }
}

// ---------------------------------------------------------------------------
// Network
// ---------------------------------------------------------------------------

/** Network or server error during artifacts API call. */
export class ArtifactNetworkError extends ArtifactError {
  constructor(
    entityId: string,
    public readonly statusCode?: number,
    cause?: unknown,
  ) {
    const statusInfo = statusCode ? ` (status: ${statusCode})` : "";
    super(`Network error in artifacts operation${statusInfo}`, entityId, cause);
    this.name = "ArtifactNetworkError";
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
export function isTransientArtifactError(error: unknown): boolean {
  if (error instanceof ArtifactNotFoundError) return false;
  if (error instanceof ArtifactAuthError) return false;
  if (error instanceof ArtifactValidationError) return false;
  if (error instanceof ArtifactNetworkError) {
    const code = error.statusCode;
    if (!code) return true; // Network-level failure (no response)
    return code === 429 || code >= 500;
  }
  return false;
}
