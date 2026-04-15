/**
 * Feeds retry helper — exponential backoff with jitter per CLAUDE.md §9.
 *
 * Purpose:
 *   Implement the retry policy from CLAUDE.md §9 for idempotent feeds API
 *   GET calls. Transient errors (network, 429, 5xx) are retried with
 *   exponential backoff plus symmetric jitter; permanent errors (4xx,
 *   validation, auth) fail fast without retry.
 *
 * Responsibilities:
 *   - Execute an async operation with configurable retry policy.
 *   - Classify errors via isTransientFeedsError() before retrying.
 *   - Sleep with exponential backoff + symmetric jitter between attempts.
 *   - Abort immediately on AbortSignal cancellation.
 *   - Emit a structured logger hook on each retry attempt.
 *
 * Does NOT:
 *   - Retry non-idempotent mutations.
 *   - Catch or swallow non-transient errors.
 *   - Know about axios, feed domain, or React.
 */

import { isTransientFeedsError } from "./errors";
import {
  FEEDS_API_MAX_RETRIES,
  FEEDS_API_RETRY_BASE_DELAY_MS,
  FEEDS_API_JITTER_FACTOR,
} from "./constants";

/** Callback invoked before each retry attempt for structured logging. */
export type RetryLogCallback = (attempt: number, delayMs: number, error: unknown) => void;

export interface RetryOptions {
  /** Maximum retry attempts after the initial call. Default: FEEDS_API_MAX_RETRIES. */
  maxRetries?: number;
  /** Base delay in ms for exponential backoff. */
  baseDelayMs?: number;
  /** Symmetric jitter factor (0 ≤ f < 1). */
  jitterFactor?: number;
  /** Optional AbortSignal to stop retries on cancellation. */
  signal?: AbortSignal;
  /** Optional retry log hook. */
  onRetry?: RetryLogCallback;
  /** Override classification function (test seam). */
  isTransient?: (err: unknown) => boolean;
  /** Override sleep implementation (test seam). */
  sleep?: (ms: number) => Promise<void>;
}

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

/**
 * Execute an async operation with exponential-backoff retry on transient errors.
 *
 * Args:
 *   operation: The idempotent async operation to execute. Receives the
 *     current attempt number (0-indexed).
 *   options: Retry configuration.
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
    maxRetries = FEEDS_API_MAX_RETRIES,
    baseDelayMs = FEEDS_API_RETRY_BASE_DELAY_MS,
    jitterFactor = FEEDS_API_JITTER_FACTOR,
    signal,
    onRetry,
    isTransient = isTransientFeedsError,
    sleep = (ms: number) => defaultSleep(ms, signal),
  } = options;

  let lastError: unknown;

  for (let attempt = 0; attempt <= maxRetries; attempt++) {
    if (signal?.aborted) {
      throw signal.reason ?? new DOMException("Aborted", "AbortError");
    }

    try {
      return await operation(attempt);
    } catch (err) {
      lastError = err;

      if (err instanceof DOMException && err.name === "AbortError") {
        throw err;
      }

      if (!isTransient(err)) {
        throw err;
      }

      if (attempt >= maxRetries) {
        throw err;
      }

      const delayMs = computeBackoffDelayMs(attempt, baseDelayMs, jitterFactor);
      onRetry?.(attempt + 1, delayMs, err);
      await sleep(delayMs);
    }
  }

  throw lastError;
}
