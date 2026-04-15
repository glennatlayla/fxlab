/**
 * Governance retry helper — exponential backoff with jitter per CLAUDE.md §9.
 *
 * Purpose:
 *   Implement the retry policy documented in CLAUDE.md §9 for idempotent
 *   governance API GET calls. Transient errors (network, 429, 5xx) are
 *   retried with exponential backoff plus jitter; permanent errors
 *   (4xx, SoD, validation, auth) fail fast without retry.
 *
 * Responsibilities:
 *   - Execute an async operation with configurable retry policy.
 *   - Classify errors via isTransientError() before retrying.
 *   - Sleep with exponential backoff + symmetric jitter between attempts.
 *   - Abort immediately on AbortSignal cancellation (no retries after abort).
 *   - Emit a structured logger hook on each retry attempt.
 *
 * Does NOT:
 *   - Retry non-idempotent mutations (caller must only wrap GETs).
 *   - Catch or swallow non-transient errors — they rethrow immediately.
 *   - Know about axios, governance domain, or React.
 *
 * Dependencies:
 *   - isTransientError() from ./errors for classification.
 *   - Constants from ./constants for defaults.
 *
 * Example:
 *   const data = await retryWithBackoff(
 *     () => axios.get("/api/approvals", { signal }),
 *     { signal, onRetry: (attempt, delay, err) => logger.retry(attempt, delay, err) },
 *   );
 */

import { isTransientError } from "./errors";
import {
  GOVERNANCE_API_MAX_RETRIES,
  GOVERNANCE_API_RETRY_BASE_DELAY_MS,
  GOVERNANCE_API_JITTER_FACTOR,
} from "./constants";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

/** Callback invoked before each retry attempt for structured logging. */
export type RetryLogCallback = (attempt: number, delayMs: number, error: unknown) => void;

export interface RetryOptions {
  /** Maximum retry attempts after the initial call. Default: GOVERNANCE_API_MAX_RETRIES. */
  maxRetries?: number;
  /** Base delay in ms for exponential backoff. Default: GOVERNANCE_API_RETRY_BASE_DELAY_MS. */
  baseDelayMs?: number;
  /** Symmetric jitter factor (0 ≤ f < 1). Default: GOVERNANCE_API_JITTER_FACTOR. */
  jitterFactor?: number;
  /** Optional AbortSignal to stop retries on cancellation. */
  signal?: AbortSignal;
  /** Optional retry log hook. */
  onRetry?: RetryLogCallback;
  /** Override classification function (test seam). */
  isTransient?: (err: unknown) => boolean;
  /** Override sleep implementation (test seam — allows deterministic tests). */
  sleep?: (ms: number) => Promise<void>;
}

// ---------------------------------------------------------------------------
// Internal helpers
// ---------------------------------------------------------------------------

/**
 * Default sleep implementation honoring an AbortSignal.
 *
 * Rejects with a DOMException("AbortError") if the signal aborts mid-sleep.
 */
function defaultSleep(ms: number, signal?: AbortSignal): Promise<void> {
  return new Promise((resolve, reject) => {
    if (signal?.aborted) {
      reject(signal.reason ?? new DOMException("Aborted", "AbortError"));
      return;
    }
    const timer = setTimeout(() => {
      signal?.removeEventListener("abort", onAbort);
      resolve();
    }, ms);
    const onAbort = () => {
      clearTimeout(timer);
      reject(signal?.reason ?? new DOMException("Aborted", "AbortError"));
    };
    signal?.addEventListener("abort", onAbort, { once: true });
  });
}

/**
 * Compute the next delay with exponential backoff + symmetric jitter.
 *
 * delay = baseDelay * 2^attempt
 * jitter = delay * jitterFactor * (2 * random - 1)   // ±jitterFactor
 * final  = max(0, delay + jitter)
 *
 * Exported for unit testing.
 */
export function computeBackoffDelayMs(
  attempt: number,
  baseDelayMs: number,
  jitterFactor: number,
  random: () => number = Math.random,
): number {
  const exponential = baseDelayMs * Math.pow(2, attempt);
  const jitter = exponential * jitterFactor * (2 * random() - 1);
  return Math.max(0, Math.round(exponential + jitter));
}

// ---------------------------------------------------------------------------
// Public API
// ---------------------------------------------------------------------------

/**
 * Execute an async operation with exponential-backoff retry on transient errors.
 *
 * Args:
 *   operation: The idempotent async operation to execute. Receives the
 *     current attempt number (0-indexed) so callers can thread new signals.
 *   options: Retry configuration (see RetryOptions).
 *
 * Returns:
 *   The resolved value from the first successful attempt.
 *
 * Raises:
 *   - The last transient error after maxRetries is exhausted.
 *   - The first non-transient error immediately (fail fast).
 *   - DOMException("AbortError") if the signal aborts during sleep.
 */
export async function retryWithBackoff<T>(
  operation: (attempt: number) => Promise<T>,
  options: RetryOptions = {},
): Promise<T> {
  const {
    maxRetries = GOVERNANCE_API_MAX_RETRIES,
    baseDelayMs = GOVERNANCE_API_RETRY_BASE_DELAY_MS,
    jitterFactor = GOVERNANCE_API_JITTER_FACTOR,
    signal,
    onRetry,
    isTransient = isTransientError,
    sleep = (ms: number) => defaultSleep(ms, signal),
  } = options;

  let lastError: unknown;

  for (let attempt = 0; attempt <= maxRetries; attempt++) {
    // Fail fast if the caller has already aborted.
    if (signal?.aborted) {
      throw signal.reason ?? new DOMException("Aborted", "AbortError");
    }

    try {
      return await operation(attempt);
    } catch (err) {
      lastError = err;

      // Abort errors are never retried — they're a user/navigation signal.
      if (err instanceof DOMException && err.name === "AbortError") {
        throw err;
      }

      // Non-transient → fail fast.
      if (!isTransient(err)) {
        throw err;
      }

      // Out of retries → rethrow the last error.
      if (attempt >= maxRetries) {
        throw err;
      }

      const delayMs = computeBackoffDelayMs(attempt, baseDelayMs, jitterFactor);
      onRetry?.(attempt + 1, delayMs, err);
      await sleep(delayMs);
    }
  }

  // Unreachable — the loop always either returns or throws.
  throw lastError;
}
