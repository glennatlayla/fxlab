/**
 * Results Explorer error types — typed exception hierarchy per CLAUDE.md §9.
 *
 * Purpose:
 *   Provide domain-specific error classes for the Results Explorer feature.
 *   Enables error classification for retry/no-retry decisions and structured
 *   error reporting to Sentry.
 *
 * Hierarchy:
 *   ResultsError (base)
 *   ├── ResultsNotFoundError    ← run does not exist (404, no retry)
 *   ├── ResultsAuthError        ← authentication/authorisation failure (401/403, no retry)
 *   ├── ResultsValidationError  ← Zod schema mismatch (no retry)
 *   ├── ResultsNetworkError     ← transient failure (retry with backoff)
 *   └── ResultsDownloadError    ← download-specific failure
 *
 * Does NOT:
 *   - Contain business logic or retry logic (api.ts handles retries).
 *   - Interact with the DOM or React.
 *
 * Dependencies:
 *   - None (pure error classes).
 */

/**
 * Base error for all Results Explorer failures.
 *
 * All subclasses carry a runId for correlation and a cause for
 * error-chain preservation. Implements toJSON() for clean Sentry
 * serialization.
 */
export class ResultsError extends Error {
  constructor(
    message: string,
    public readonly runId: string,
    public readonly cause?: unknown,
  ) {
    super(message);
    this.name = "ResultsError";
  }

  /**
   * Serialize for structured logging and Sentry.
   *
   * Returns:
   *   Plain object with name, message, runId, and cause message.
   */
  toJSON(): Record<string, unknown> {
    return {
      name: this.name,
      message: this.message,
      runId: this.runId,
      cause: this.cause instanceof Error ? this.cause.message : this.cause,
    };
  }
}

/** Run not found (HTTP 404). No retry. */
export class ResultsNotFoundError extends ResultsError {
  constructor(runId: string, cause?: unknown) {
    super(`Run ${runId} not found`, runId, cause);
    this.name = "ResultsNotFoundError";
  }
}

/**
 * Authentication or authorisation failure (HTTP 401/403). No retry.
 *
 * Distinct from ResultsNetworkError so the UI can show "Session expired"
 * or "Permission denied" instead of a generic network error.
 */
export class ResultsAuthError extends ResultsError {
  constructor(
    runId: string,
    public readonly statusCode: 401 | 403,
    cause?: unknown,
  ) {
    const reason = statusCode === 401 ? "Authentication required" : "Permission denied";
    super(`${reason} for run ${runId}`, runId, cause);
    this.name = "ResultsAuthError";
  }

  override toJSON(): Record<string, unknown> {
    return { ...super.toJSON(), statusCode: this.statusCode };
  }
}

/** Response schema validation failed. No retry. */
export class ResultsValidationError extends ResultsError {
  constructor(
    runId: string,
    public readonly validationErrors: unknown,
    cause?: unknown,
  ) {
    super(`Invalid response schema for run ${runId}`, runId, cause);
    this.name = "ResultsValidationError";
  }

  override toJSON(): Record<string, unknown> {
    return { ...super.toJSON(), validationErrors: this.validationErrors };
  }
}

/** Transient network/server error. Eligible for retry. */
export class ResultsNetworkError extends ResultsError {
  constructor(
    runId: string,
    public readonly statusCode: number | undefined,
    cause?: unknown,
  ) {
    const causeMsg = cause instanceof Error ? `: ${cause.message}` : "";
    super(
      `Network error fetching run ${runId} (status: ${statusCode ?? "unknown"})${causeMsg}`,
      runId,
      cause,
    );
    this.name = "ResultsNetworkError";
  }

  override toJSON(): Record<string, unknown> {
    return { ...super.toJSON(), statusCode: this.statusCode };
  }
}

/** Download-specific error (timeout, abort, corrupt blob). */
export class ResultsDownloadError extends ResultsError {
  constructor(
    runId: string,
    public readonly reason: "timeout" | "abort" | "network" | "unknown",
    cause?: unknown,
  ) {
    super(`Export download failed for run ${runId}: ${reason}`, runId, cause);
    this.name = "ResultsDownloadError";
  }

  override toJSON(): Record<string, unknown> {
    return { ...super.toJSON(), reason: this.reason };
  }
}

/**
 * Determine if an error is transient and eligible for retry.
 *
 * Per CLAUDE.md §9:
 *   - Retry on: network timeouts, 429, 5xx.
 *   - No retry on: 400, 401, 403, 404, validation errors, auth errors.
 *
 * Args:
 *   error: The error to classify.
 *
 * Returns:
 *   true if the error is transient and should be retried.
 */
export function isTransientError(error: unknown): boolean {
  if (error instanceof ResultsNotFoundError) return false;
  if (error instanceof ResultsAuthError) return false;
  if (error instanceof ResultsValidationError) return false;
  if (error instanceof ResultsNetworkError) {
    const status = error.statusCode;
    if (status === undefined) return true; // network failure, no response
    if (status === 429) return true; // rate-limited
    if (status >= 500) return true; // server error
    return false; // 4xx client errors are not transient
  }
  if (error instanceof ResultsDownloadError) {
    return error.reason === "network" || error.reason === "timeout";
  }
  return false;
}
