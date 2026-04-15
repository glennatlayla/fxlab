/**
 * RunMonitorService — pure business logic for run monitoring.
 *
 * Purpose:
 *   Encapsulate all non-React business logic for the run monitor feature.
 *   Extracted from hooks (controller layer) per CLAUDE.md §4 onion
 *   architecture to ensure testability without React rendering context.
 *
 * Responsibilities:
 *   - Exponential backoff interval calculation (§8.1).
 *   - Terminal status detection.
 *   - Stale data threshold evaluation.
 *   - Stop-polling decision logic (terminal + 404).
 *   - Optimization metrics derivation from run records.
 *   - Input validation: ULID format, result URI scheme (XSS prevention).
 *   - Safe date parsing and JSON serialization helpers.
 *
 * Does NOT:
 *   - Manage React state (that remains in hooks/controllers).
 *   - Make HTTP calls (that's the repository/API layer).
 *   - Render UI or manage component lifecycle.
 *
 * Dependencies:
 *   - @/types/run for domain types and constants.
 *
 * Error conditions:
 *   - calculateNextInterval throws on non-positive inputs.
 *   - safeParseDateMs returns null on unparseable dates.
 *   - safeJsonStringify returns fallback on circular references.
 *
 * Example:
 *   import { calculateNextInterval, isTerminalStatus } from "./RunMonitorService";
 *
 *   const nextMs = calculateNextInterval(2000, 2, 30000); // 4000
 *   const done = isTerminalStatus("complete"); // true
 */

import type { RunRecord, RunStatus, OptimizationMetrics } from "@/types/run";
import { TERMINAL_RUN_STATUSES } from "@/types/run";

// ---------------------------------------------------------------------------
// Polling strategy
// ---------------------------------------------------------------------------

/**
 * Calculate the next polling interval with exponential backoff.
 *
 * Multiplies the current interval by the backoff multiplier, capped at max.
 *
 * Args:
 *   currentMs: Current polling interval in milliseconds. Must be positive.
 *   multiplier: Backoff multiplier (e.g. 2 for doubling). Must be positive.
 *   maxMs: Maximum interval cap in milliseconds.
 *
 * Returns:
 *   Next interval in milliseconds, capped at maxMs.
 *
 * Raises:
 *   Error if currentMs or multiplier is not positive.
 *
 * Example:
 *   calculateNextInterval(2000, 2, 30000) → 4000
 *   calculateNextInterval(20000, 2, 30000) → 30000
 */
export function calculateNextInterval(
  currentMs: number,
  multiplier: number,
  maxMs: number,
): number {
  if (currentMs <= 0) {
    throw new Error("interval must be positive");
  }
  if (multiplier <= 0) {
    throw new Error("multiplier must be positive");
  }
  return Math.min(currentMs * multiplier, maxMs);
}

/**
 * Check whether a run status is terminal (polling should stop).
 *
 * Args:
 *   status: Current run status string.
 *
 * Returns:
 *   True if status is in TERMINAL_RUN_STATUSES (complete, failed, cancelled).
 *
 * Example:
 *   isTerminalStatus("complete") → true
 *   isTerminalStatus("running") → false
 */
export function isTerminalStatus(status: RunStatus): boolean {
  return (TERMINAL_RUN_STATUSES as readonly string[]).includes(status);
}

/**
 * Determine whether displayed data should be marked stale.
 *
 * Data is stale when all three conditions are met:
 *   1. At least one successful poll has occurred (lastSuccessMs is non-null).
 *   2. An error is currently present (most recent poll failed).
 *   3. Elapsed time since last success exceeds the threshold.
 *
 * Args:
 *   lastSuccessMs: Epoch milliseconds of last successful poll (null if never succeeded).
 *   hasError: Whether the most recent poll resulted in an error.
 *   thresholdMs: Staleness threshold in milliseconds.
 *
 * Returns:
 *   True if data should be marked stale.
 *
 * Example:
 *   isStaleData(Date.now() - 10000, true, 5000) → true
 *   isStaleData(Date.now() - 1000, true, 5000) → false
 */
export function isStaleData(
  lastSuccessMs: number | null,
  hasError: boolean,
  thresholdMs: number,
): boolean {
  if (lastSuccessMs === null) return false;
  if (!hasError) return false;
  return Date.now() - lastSuccessMs > thresholdMs;
}

/**
 * Decide whether polling should stop entirely.
 *
 * Polling stops when the run reaches a terminal status OR the server
 * returns 404 (run does not exist / has been deleted).
 *
 * Args:
 *   status: Current run status.
 *   httpStatus: HTTP status code from the most recent poll (undefined if successful or no code).
 *
 * Returns:
 *   True if polling should stop.
 *
 * Example:
 *   shouldStopPolling("complete", undefined) → true
 *   shouldStopPolling("running", 404) → true
 *   shouldStopPolling("running", 500) → false
 */
export function shouldStopPolling(status: RunStatus, httpStatus: number | undefined): boolean {
  if (isTerminalStatus(status)) return true;
  if (httpStatus === 404) return true;
  return false;
}

// ---------------------------------------------------------------------------
// Metrics derivation
// ---------------------------------------------------------------------------

/**
 * Derive optimization progress metrics from a run record.
 *
 * Returns null for non-optimization runs or when required fields are missing.
 * Uses safe date parsing to handle malformed timestamps gracefully.
 *
 * Args:
 *   run: Current run record.
 *
 * Returns:
 *   OptimizationMetrics or null if not applicable.
 *
 * Example:
 *   const metrics = deriveOptimizationMetrics(optimizationRun);
 *   // metrics.trialsPerMinute === 1.5
 */
export function deriveOptimizationMetrics(run: RunRecord): OptimizationMetrics | null {
  if (run.run_type !== "optimization") return null;
  if (run.trial_count === undefined || run.completed_trials === undefined) return null;

  let trialsPerMinute = 0;

  if (run.started_at && run.completed_trials > 0) {
    const startedMs = safeParseDateMs(run.started_at);
    if (startedMs !== null) {
      const endMs = run.completed_at
        ? (safeParseDateMs(run.completed_at) ?? Date.now())
        : Date.now();
      const elapsedMinutes = (endMs - startedMs) / 60_000;
      trialsPerMinute = elapsedMinutes > 0 ? run.completed_trials / elapsedMinutes : 0;
    }
  }

  return {
    totalTrials: run.trial_count,
    completedTrials: run.completed_trials,
    bestObjectiveValue: null, // Populated from trial data when available
    bestTrialIndex: null,
    trialsPerMinute,
  };
}

// ---------------------------------------------------------------------------
// Input validation
// ---------------------------------------------------------------------------

/**
 * Allowed URI schemes for result_uri links.
 *
 * Prevents XSS via javascript:, data:, and vbscript: schemes which
 * could execute arbitrary code when rendered as <a href="...">.
 */
const ALLOWED_URI_SCHEMES = ["https:", "http:", "s3:", "gs:", "ftp:"];

/**
 * Validate a result URI scheme to prevent XSS injection.
 *
 * Only allows http(s), s3, gs, and ftp schemes. Blocks javascript:,
 * data:, vbscript:, and any other potentially dangerous schemes.
 *
 * Args:
 *   uri: The result URI to validate. May be null/undefined.
 *
 * Returns:
 *   True if the URI has a safe, allowed scheme.
 *
 * Example:
 *   validateResultUri("https://bucket.s3.amazonaws.com/results.parquet") → true
 *   validateResultUri("javascript:alert(1)") → false
 */
export function validateResultUri(uri: string | null | undefined): boolean {
  if (!uri || uri.length === 0) return false;

  // Extract scheme (everything before the first colon)
  const colonIndex = uri.indexOf(":");
  if (colonIndex === -1) return false;

  const scheme = uri.slice(0, colonIndex + 1).toLowerCase();
  return ALLOWED_URI_SCHEMES.includes(scheme);
}

/**
 * ULID format: 26 uppercase Crockford Base32 characters.
 *
 * Crockford's Base32 alphabet excludes I, L, O, U to avoid ambiguity.
 */
const ULID_REGEX = /^[0-9A-HJKMNP-TV-Z]{26}$/;

/**
 * Validate that a string is a well-formed ULID.
 *
 * ULIDs are 26-character strings using Crockford Base32 encoding
 * (uppercase only, no I/L/O/U characters).
 *
 * Args:
 *   id: String to validate.
 *
 * Returns:
 *   True if the string matches ULID format.
 *
 * Example:
 *   validateUlid("01HZ0000000000000000000001") → true
 *   validateUlid("invalid") → false
 */
export function validateUlid(id: string): boolean {
  if (!id || typeof id !== "string") return false;
  return ULID_REGEX.test(id);
}

// ---------------------------------------------------------------------------
// Safe parsing helpers
// ---------------------------------------------------------------------------

/**
 * Safely parse a date string to epoch milliseconds.
 *
 * Returns null for invalid, empty, null, or undefined inputs instead
 * of returning NaN (which Date.parse produces for invalid strings).
 *
 * Args:
 *   dateStr: ISO-8601 date string, null, or undefined.
 *
 * Returns:
 *   Epoch milliseconds or null if unparseable.
 *
 * Example:
 *   safeParseDateMs("2026-04-04T10:00:00Z") → 1775296800000
 *   safeParseDateMs("not-a-date") → null
 */
export function safeParseDateMs(dateStr: string | null | undefined): number | null {
  if (!dateStr || dateStr.length === 0) return null;

  try {
    const ms = new Date(dateStr).getTime();
    // Date constructor returns NaN for invalid strings
    if (Number.isNaN(ms)) return null;
    return ms;
  } catch {
    return null;
  }
}

/**
 * Safely serialize a value to JSON, returning a fallback on failure.
 *
 * Handles circular references and other serialization errors that
 * would cause JSON.stringify to throw.
 *
 * Args:
 *   value: Any value to serialize.
 *   fallback: String to return if serialization fails (default: "[unserializable]").
 *
 * Returns:
 *   JSON string or fallback.
 *
 * Example:
 *   safeJsonStringify({ a: 1 }) → '{"a":1}'
 *   safeJsonStringify(circularObj) → "[unserializable]"
 */
export function safeJsonStringify(value: unknown, fallback = "[unserializable]"): string {
  try {
    return JSON.stringify(value);
  } catch {
    return fallback;
  }
}

// ---------------------------------------------------------------------------
// Transient error detection
// ---------------------------------------------------------------------------

/**
 * HTTP status codes that indicate transient (retriable) failures.
 *
 * Per CLAUDE.md §9: retry on network timeouts, 429 rate-limit, 5xx server errors.
 * Do NOT retry on 400, 401, 403, 404.
 */
const TRANSIENT_HTTP_STATUSES = new Set([429, 500, 502, 503, 504]);

/**
 * Determine whether an error represents a transient failure worth retrying.
 *
 * Checks for network errors (no response) and transient HTTP status codes.
 *
 * Args:
 *   err: Unknown error from a catch block.
 *
 * Returns:
 *   True if the error is transient and the request should be retried.
 *
 * Example:
 *   isTransientError(new AxiosError("Network Error")) → true
 *   isTransientError(axiosErrorWith422) → false
 */
export function isTransientError(err: unknown): boolean {
  if (!(typeof err === "object" && err !== null)) return false;

  // Network errors (no response received) are always transient
  if (
    "code" in err &&
    ((err as { code?: string }).code === "ERR_NETWORK" ||
      (err as { code?: string }).code === "ECONNABORTED")
  ) {
    return true;
  }

  // Check HTTP status if a response exists
  if ("response" in err) {
    const status = (err as { response?: { status?: number } }).response?.status;
    if (status !== undefined && TRANSIENT_HTTP_STATUSES.has(status)) {
      return true;
    }
  }

  return false;
}

/** Maximum number of retry attempts for transient submission failures. */
export const SUBMISSION_MAX_RETRIES = 2;

/** Base delay in milliseconds for retry backoff (doubles each attempt). */
export const SUBMISSION_RETRY_BASE_MS = 1_000;

/**
 * Calculate retry delay with exponential backoff and jitter.
 *
 * Per CLAUDE.md §9: exponential backoff with jitter.
 *
 * Args:
 *   attempt: Zero-based retry attempt number.
 *   baseMs: Base delay in milliseconds.
 *
 * Returns:
 *   Delay in milliseconds with jitter applied.
 *
 * Example:
 *   calculateRetryDelay(0, 1000) → ~1000-1500ms
 *   calculateRetryDelay(1, 1000) → ~2000-3000ms
 */
export function calculateRetryDelay(attempt: number, baseMs: number): number {
  const exponentialDelay = baseMs * Math.pow(2, attempt);
  // Add 0-50% jitter to prevent thundering herd
  const jitter = exponentialDelay * 0.5 * Math.random();
  return exponentialDelay + jitter;
}
