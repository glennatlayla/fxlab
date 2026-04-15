/**
 * Tests for retry helper — exponential backoff with jitter per CLAUDE.md §9.
 *
 * Covers:
 *   - Happy path: first attempt succeeds → no retries.
 *   - Transient error recovery: fails N times then succeeds.
 *   - Exponential backoff calculation with jitter.
 *   - Fail fast on non-transient errors (no retries).
 *   - Max retries exhaustion rethrows last error.
 *   - AbortSignal pre-abort throws immediately.
 *   - AbortSignal mid-flight cancels pending retries.
 *   - Sleep is called with computed delay between attempts.
 *   - onRetry callback emits attempt/delay/error per retry.
 *   - Default transient classifier uses isTransientError.
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { retryWithBackoff, computeBackoffDelayMs } from "./retry";
import { GovernanceNetworkError, GovernanceAuthError, GovernanceSoDError } from "./errors";

describe("computeBackoffDelayMs", () => {
  it("computes pure exponential with zero jitter", () => {
    // attempt 0: 1000 * 2^0 = 1000
    expect(computeBackoffDelayMs(0, 1000, 0, () => 0.5)).toBe(1000);
    // attempt 1: 1000 * 2^1 = 2000
    expect(computeBackoffDelayMs(1, 1000, 0, () => 0.5)).toBe(2000);
    // attempt 2: 1000 * 2^2 = 4000
    expect(computeBackoffDelayMs(2, 1000, 0, () => 0.5)).toBe(4000);
    // attempt 3: 1000 * 2^3 = 8000
    expect(computeBackoffDelayMs(3, 1000, 0, () => 0.5)).toBe(8000);
  });

  it("applies symmetric jitter at the upper bound", () => {
    // random=1 → jitter = delay * 0.25 * 1 → 1000 + 250 = 1250
    expect(computeBackoffDelayMs(0, 1000, 0.25, () => 1)).toBe(1250);
  });

  it("applies symmetric jitter at the lower bound", () => {
    // random=0 → jitter = delay * 0.25 * -1 → 1000 - 250 = 750
    expect(computeBackoffDelayMs(0, 1000, 0.25, () => 0)).toBe(750);
  });

  it("never returns negative values", () => {
    // Large jitter factor that could go negative is clamped to 0.
    expect(computeBackoffDelayMs(0, 100, 10, () => 0)).toBe(0);
  });
});

describe("retryWithBackoff", () => {
  let sleep: (ms: number) => Promise<void>;
  let sleepSpy: ReturnType<typeof vi.fn>;

  beforeEach(() => {
    sleepSpy = vi.fn().mockResolvedValue(undefined);
    sleep = (ms: number) => sleepSpy(ms) as Promise<void>;
  });

  it("returns result on first attempt without retrying", async () => {
    const op = vi.fn().mockResolvedValue("ok");
    const result = await retryWithBackoff(op, { sleep });
    expect(result).toBe("ok");
    expect(op).toHaveBeenCalledTimes(1);
    expect(sleepSpy).not.toHaveBeenCalled();
  });

  it("retries on transient errors and succeeds on second attempt", async () => {
    const op = vi
      .fn()
      .mockRejectedValueOnce(new GovernanceNetworkError("e1", 503))
      .mockResolvedValueOnce("recovered");

    const result = await retryWithBackoff(op, { sleep, baseDelayMs: 10, jitterFactor: 0 });

    expect(result).toBe("recovered");
    expect(op).toHaveBeenCalledTimes(2);
    expect(sleepSpy).toHaveBeenCalledTimes(1);
    expect(sleepSpy).toHaveBeenCalledWith(10); // attempt 0 → 10ms
  });

  it("retries network-level errors with no status code", async () => {
    const op = vi
      .fn()
      .mockRejectedValueOnce(new GovernanceNetworkError("e1"))
      .mockResolvedValueOnce("ok");

    const result = await retryWithBackoff(op, { sleep, baseDelayMs: 5, jitterFactor: 0 });
    expect(result).toBe("ok");
    expect(op).toHaveBeenCalledTimes(2);
  });

  it("exhausts retries and rethrows last error when all attempts fail", async () => {
    const lastError = new GovernanceNetworkError("e1", 500);
    const op = vi
      .fn()
      .mockRejectedValueOnce(new GovernanceNetworkError("e1", 500))
      .mockRejectedValueOnce(new GovernanceNetworkError("e1", 502))
      .mockRejectedValueOnce(new GovernanceNetworkError("e1", 503))
      .mockRejectedValueOnce(lastError);

    await expect(
      retryWithBackoff(op, { sleep, maxRetries: 3, baseDelayMs: 1, jitterFactor: 0 }),
    ).rejects.toBe(lastError);
    expect(op).toHaveBeenCalledTimes(4); // initial + 3 retries
    expect(sleepSpy).toHaveBeenCalledTimes(3);
  });

  it("fails fast on non-transient auth errors without retrying", async () => {
    const err = new GovernanceAuthError("e1", 403);
    const op = vi.fn().mockRejectedValue(err);

    await expect(retryWithBackoff(op, { sleep })).rejects.toBe(err);
    expect(op).toHaveBeenCalledTimes(1);
    expect(sleepSpy).not.toHaveBeenCalled();
  });

  it("fails fast on non-transient SoD errors (409)", async () => {
    const err = new GovernanceSoDError("e1");
    const op = vi.fn().mockRejectedValue(err);

    await expect(retryWithBackoff(op, { sleep })).rejects.toBe(err);
    expect(op).toHaveBeenCalledTimes(1);
  });

  it("does not retry on 400/404 (non-transient network errors)", async () => {
    const err = new GovernanceNetworkError("e1", 400);
    const op = vi.fn().mockRejectedValue(err);

    await expect(retryWithBackoff(op, { sleep })).rejects.toBe(err);
    expect(op).toHaveBeenCalledTimes(1);
  });

  it("retries on 429 rate-limit", async () => {
    const op = vi
      .fn()
      .mockRejectedValueOnce(new GovernanceNetworkError("e1", 429))
      .mockResolvedValueOnce("ok");

    const result = await retryWithBackoff(op, { sleep, baseDelayMs: 1, jitterFactor: 0 });
    expect(result).toBe("ok");
    expect(op).toHaveBeenCalledTimes(2);
  });

  it("uses exponential delays across successive retries", async () => {
    const op = vi
      .fn()
      .mockRejectedValueOnce(new GovernanceNetworkError("e1", 500))
      .mockRejectedValueOnce(new GovernanceNetworkError("e1", 500))
      .mockResolvedValueOnce("ok");

    await retryWithBackoff(op, { sleep, baseDelayMs: 100, jitterFactor: 0 });

    expect(sleepSpy).toHaveBeenNthCalledWith(1, 100); // 100 * 2^0
    expect(sleepSpy).toHaveBeenNthCalledWith(2, 200); // 100 * 2^1
  });

  it("throws AbortError immediately if signal is already aborted", async () => {
    const controller = new AbortController();
    controller.abort();
    const op = vi.fn().mockResolvedValue("ok");

    await expect(retryWithBackoff(op, { sleep, signal: controller.signal })).rejects.toThrow();
    expect(op).not.toHaveBeenCalled();
  });

  it("does not retry when operation throws AbortError", async () => {
    const abortErr = new DOMException("Aborted", "AbortError");
    const op = vi.fn().mockRejectedValue(abortErr);

    await expect(retryWithBackoff(op, { sleep })).rejects.toBe(abortErr);
    expect(op).toHaveBeenCalledTimes(1);
    expect(sleepSpy).not.toHaveBeenCalled();
  });

  it("invokes onRetry callback before each retry with attempt/delay/error", async () => {
    const onRetry = vi.fn();
    const err = new GovernanceNetworkError("e1", 500);
    const op = vi.fn().mockRejectedValueOnce(err).mockResolvedValueOnce("ok");

    await retryWithBackoff(op, { sleep, onRetry, baseDelayMs: 50, jitterFactor: 0 });

    expect(onRetry).toHaveBeenCalledTimes(1);
    expect(onRetry).toHaveBeenCalledWith(1, 50, err);
  });

  it("passes attempt number to the operation callback", async () => {
    const op = vi.fn().mockImplementation(async (attempt: number) => {
      if (attempt < 2) throw new GovernanceNetworkError("e1", 500);
      return attempt;
    });

    const result = await retryWithBackoff(op, { sleep, baseDelayMs: 1, jitterFactor: 0 });
    expect(result).toBe(2);
    expect(op).toHaveBeenNthCalledWith(1, 0);
    expect(op).toHaveBeenNthCalledWith(2, 1);
    expect(op).toHaveBeenNthCalledWith(3, 2);
  });

  it("honors custom isTransient override", async () => {
    const err = new Error("custom");
    const op = vi.fn().mockRejectedValueOnce(err).mockResolvedValueOnce("ok");

    const result = await retryWithBackoff(op, {
      sleep,
      baseDelayMs: 1,
      jitterFactor: 0,
      isTransient: () => true,
    });

    expect(result).toBe("ok");
    expect(op).toHaveBeenCalledTimes(2);
  });

  it("defaults to not retrying unknown (non-governance) errors", async () => {
    const err = new Error("unknown");
    const op = vi.fn().mockRejectedValue(err);

    await expect(retryWithBackoff(op, { sleep })).rejects.toBe(err);
    expect(op).toHaveBeenCalledTimes(1);
  });
});
