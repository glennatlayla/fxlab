/**
 * Readiness feature error hierarchy — typed exceptions per CLAUDE.md §9.
 *
 * Purpose:
 *   Domain-specific error types for the Readiness Report Viewer.
 *   Enables precise error handling, retry classification, and
 *   user-facing error messages.
 *
 * Responsibilities:
 *   - Define error classes for not-found, auth, validation, network, and generation failures.
 *   - Classify transient vs permanent errors for retry logic.
 *   - Provide toJSON() for Sentry error reporting.
 *
 * Does NOT:
 *   - Contain business logic or UI rendering.
 *   - Import component-layer code.
 *
 * Dependencies:
 *   - None (pure error types).
 */

// ---------------------------------------------------------------------------
// Base error
// ---------------------------------------------------------------------------

/**
 * Base error for all Readiness feature errors.
 *
 * Carries runId for correlation across the feature.
 */
export class ReadinessError extends Error {
  constructor(
    message: string,
    public readonly runId: string,
    public readonly cause?: unknown,
  ) {
    super(message);
    this.name = "ReadinessError";
  }

  /** Serialize for Sentry structured context. */
  toJSON(): Record<string, unknown> {
    return {
      name: this.name,
      message: this.message,
      runId: this.runId,
      cause: this.cause instanceof Error ? this.cause.message : this.cause,
    };
  }
}

// ---------------------------------------------------------------------------
// Not found
// ---------------------------------------------------------------------------

/** Run or readiness report does not exist (HTTP 404). */
export class ReadinessNotFoundError extends ReadinessError {
  constructor(runId: string, cause?: unknown) {
    super(`Readiness report not found for run ${runId}`, runId, cause);
    this.name = "ReadinessNotFoundError";
  }
}

// ---------------------------------------------------------------------------
// Auth errors
// ---------------------------------------------------------------------------

/** Authentication or authorization failure (HTTP 401/403). */
export class ReadinessAuthError extends ReadinessError {
  constructor(
    runId: string,
    public readonly statusCode: 401 | 403,
    cause?: unknown,
  ) {
    const reason = statusCode === 401 ? "Authentication required" : "Permission denied";
    super(`${reason} for readiness report (run ${runId})`, runId, cause);
    this.name = "ReadinessAuthError";
  }

  override toJSON(): Record<string, unknown> {
    return { ...super.toJSON(), statusCode: this.statusCode };
  }
}

// ---------------------------------------------------------------------------
// Validation
// ---------------------------------------------------------------------------

/** Zod schema validation failure on API response. */
export class ReadinessValidationError extends ReadinessError {
  constructor(
    runId: string,
    public readonly issues: unknown[],
    cause?: unknown,
  ) {
    super(
      `Readiness report schema validation failed for run ${runId} (${issues.length} issue(s))`,
      runId,
      cause,
    );
    this.name = "ReadinessValidationError";
  }

  override toJSON(): Record<string, unknown> {
    return { ...super.toJSON(), issueCount: this.issues.length };
  }
}

// ---------------------------------------------------------------------------
// Network
// ---------------------------------------------------------------------------

/** Network or server error during readiness API call. */
export class ReadinessNetworkError extends ReadinessError {
  constructor(
    runId: string,
    public readonly statusCode?: number,
    cause?: unknown,
  ) {
    const statusInfo = statusCode ? ` (status: ${statusCode})` : "";
    super(`Network error fetching readiness for run ${runId}${statusInfo}`, runId, cause);
    this.name = "ReadinessNetworkError";
  }

  override toJSON(): Record<string, unknown> {
    return { ...super.toJSON(), statusCode: this.statusCode };
  }
}

// ---------------------------------------------------------------------------
// Generation
// ---------------------------------------------------------------------------

/** Error generating a new readiness report (POST failure). */
export class ReadinessGenerationError extends ReadinessError {
  constructor(
    runId: string,
    public readonly statusCode?: number,
    cause?: unknown,
  ) {
    super(`Failed to generate readiness report for run ${runId}`, runId, cause);
    this.name = "ReadinessGenerationError";
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
 * Do NOT retry on 400, 401, 403, 404.
 *
 * Args:
 *   error: Any error from the readiness feature.
 *
 * Returns:
 *   true if the error is transient and should be retried.
 */
export function isTransientError(error: unknown): boolean {
  if (error instanceof ReadinessNotFoundError) return false;
  if (error instanceof ReadinessAuthError) return false;
  if (error instanceof ReadinessValidationError) return false;
  if (error instanceof ReadinessNetworkError) {
    const code = error.statusCode;
    if (!code) return true; // Network-level failure (no response)
    return code === 429 || code >= 500;
  }
  if (error instanceof ReadinessGenerationError) {
    const code = error.statusCode;
    if (!code) return true;
    return code === 429 || code >= 500;
  }
  return false;
}
