/**
 * Exports feature error hierarchy — typed exceptions per CLAUDE.md §9.
 *
 * Purpose:
 *   Domain-specific error types for the Exports feature. Enables precise
 *   error handling, retry classification, and user-facing error messages.
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
 *   import { ExportAuthError, isTransientExportError } from "@/features/exports/errors";
 *   if (isTransientExportError(err)) { // retry }
 */

// ---------------------------------------------------------------------------
// Base error
// ---------------------------------------------------------------------------

/**
 * Base error for all exports feature errors.
 *
 * Carries exportId for correlation across the feature (export job ID
 * or "create" / "list" for collection operations).
 */
export class ExportError extends Error {
  constructor(
    message: string,
    public readonly exportId: string,
    public readonly cause?: unknown,
  ) {
    super(message);
    this.name = "ExportError";
  }

  /** Serialize for Sentry structured context. */
  toJSON(): Record<string, unknown> {
    return {
      name: this.name,
      message: this.message,
      exportId: this.exportId,
      cause: this.cause instanceof Error ? this.cause.message : this.cause,
    };
  }
}

// ---------------------------------------------------------------------------
// Not found
// ---------------------------------------------------------------------------

/** Export job does not exist (HTTP 404). */
export class ExportNotFoundError extends ExportError {
  constructor(exportId: string, cause?: unknown) {
    super(`Export job not found: ${exportId}`, exportId, cause);
    this.name = "ExportNotFoundError";
  }
}

// ---------------------------------------------------------------------------
// Auth errors
// ---------------------------------------------------------------------------

/** Authentication or authorization failure (HTTP 401/403). */
export class ExportAuthError extends ExportError {
  constructor(
    exportId: string,
    public readonly statusCode: 401 | 403,
    cause?: unknown,
  ) {
    const reason = statusCode === 401 ? "Authentication required" : "Permission denied";
    super(`${reason} for export operation (export ${exportId})`, exportId, cause);
    this.name = "ExportAuthError";
  }

  override toJSON(): Record<string, unknown> {
    return { ...super.toJSON(), statusCode: this.statusCode };
  }
}

// ---------------------------------------------------------------------------
// Validation
// ---------------------------------------------------------------------------

/** Zod schema validation failure on API response. */
export class ExportValidationError extends ExportError {
  constructor(
    exportId: string,
    public readonly issues: unknown[],
    cause?: unknown,
  ) {
    super(`Export schema validation failed (${issues.length} issue(s))`, exportId, cause);
    this.name = "ExportValidationError";
  }

  override toJSON(): Record<string, unknown> {
    return { ...super.toJSON(), issueCount: this.issues.length };
  }
}

// ---------------------------------------------------------------------------
// Network
// ---------------------------------------------------------------------------

/** Network or server error during export API call. */
export class ExportNetworkError extends ExportError {
  constructor(
    exportId: string,
    public readonly statusCode?: number,
    cause?: unknown,
  ) {
    const statusInfo = statusCode ? ` (status: ${statusCode})` : "";
    super(`Network error in export operation${statusInfo}`, exportId, cause);
    this.name = "ExportNetworkError";
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
export function isTransientExportError(error: unknown): boolean {
  if (error instanceof ExportNotFoundError) return false;
  if (error instanceof ExportAuthError) return false;
  if (error instanceof ExportValidationError) return false;
  if (error instanceof ExportNetworkError) {
    const code = error.statusCode;
    if (!code) return true; // Network-level failure (no response)
    return code === 429 || code >= 500;
  }
  return false;
}
