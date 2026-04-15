/**
 * Tests for RunMonitorService — pure business logic for run monitoring.
 *
 * Verifies CLAUDE.md §4 service layer requirements: all polling strategy,
 * terminal detection, stale data, metrics derivation, and input validation
 * logic is testable without React.
 */

import { describe, it, expect, vi } from "vitest";
import {
  calculateNextInterval,
  isTerminalStatus,
  isStaleData,
  shouldStopPolling,
  deriveOptimizationMetrics,
  validateResultUri,
  validateUlid,
  safeParseDateMs,
  safeJsonStringify,
  isTransientError,
  calculateRetryDelay,
  SUBMISSION_MAX_RETRIES,
  SUBMISSION_RETRY_BASE_MS,
} from "./RunMonitorService";
import type { RunRecord } from "@/types/run";
import {
  INITIAL_POLL_INTERVAL_MS,
  MAX_POLL_INTERVAL_MS,
  POLL_BACKOFF_MULTIPLIER,
  STALE_INDICATOR_THRESHOLD_MS,
} from "@/types/run";

// ---------------------------------------------------------------------------
// calculateNextInterval
// ---------------------------------------------------------------------------

describe("calculateNextInterval", () => {
  it("doubles the interval on each call", () => {
    const next = calculateNextInterval(
      INITIAL_POLL_INTERVAL_MS,
      POLL_BACKOFF_MULTIPLIER,
      MAX_POLL_INTERVAL_MS,
    );
    expect(next).toBe(INITIAL_POLL_INTERVAL_MS * POLL_BACKOFF_MULTIPLIER);
  });

  it("caps at MAX_POLL_INTERVAL_MS", () => {
    const next = calculateNextInterval(20_000, POLL_BACKOFF_MULTIPLIER, MAX_POLL_INTERVAL_MS);
    expect(next).toBe(MAX_POLL_INTERVAL_MS);
  });

  it("returns max when current already equals max", () => {
    const next = calculateNextInterval(
      MAX_POLL_INTERVAL_MS,
      POLL_BACKOFF_MULTIPLIER,
      MAX_POLL_INTERVAL_MS,
    );
    expect(next).toBe(MAX_POLL_INTERVAL_MS);
  });

  it("handles multiplier of 1 (no backoff)", () => {
    const next = calculateNextInterval(2_000, 1, MAX_POLL_INTERVAL_MS);
    expect(next).toBe(2_000);
  });

  it("rejects non-positive interval", () => {
    expect(() => calculateNextInterval(0, 2, 30_000)).toThrow("interval must be positive");
  });

  it("rejects non-positive multiplier", () => {
    expect(() => calculateNextInterval(2_000, 0, 30_000)).toThrow("multiplier must be positive");
  });
});

// ---------------------------------------------------------------------------
// isTerminalStatus
// ---------------------------------------------------------------------------

describe("isTerminalStatus", () => {
  it("returns true for complete", () => {
    expect(isTerminalStatus("complete")).toBe(true);
  });

  it("returns true for failed", () => {
    expect(isTerminalStatus("failed")).toBe(true);
  });

  it("returns true for cancelled", () => {
    expect(isTerminalStatus("cancelled")).toBe(true);
  });

  it("returns false for pending", () => {
    expect(isTerminalStatus("pending")).toBe(false);
  });

  it("returns false for running", () => {
    expect(isTerminalStatus("running")).toBe(false);
  });
});

// ---------------------------------------------------------------------------
// isStaleData
// ---------------------------------------------------------------------------

describe("isStaleData", () => {
  it("returns false when lastSuccessMs is null", () => {
    expect(isStaleData(null, false, STALE_INDICATOR_THRESHOLD_MS)).toBe(false);
  });

  it("returns false when no error is present", () => {
    const recentMs = Date.now() - 1_000;
    expect(isStaleData(recentMs, false, STALE_INDICATOR_THRESHOLD_MS)).toBe(false);
  });

  it("returns false when error present but within threshold", () => {
    const recentMs = Date.now() - 2_000;
    expect(isStaleData(recentMs, true, STALE_INDICATOR_THRESHOLD_MS)).toBe(false);
  });

  it("returns true when error present and exceeds threshold", () => {
    const staleMs = Date.now() - 10_000;
    expect(isStaleData(staleMs, true, STALE_INDICATOR_THRESHOLD_MS)).toBe(true);
  });

  it("returns true at exactly the threshold boundary", () => {
    const boundaryMs = Date.now() - STALE_INDICATOR_THRESHOLD_MS - 1;
    expect(isStaleData(boundaryMs, true, STALE_INDICATOR_THRESHOLD_MS)).toBe(true);
  });
});

// ---------------------------------------------------------------------------
// shouldStopPolling
// ---------------------------------------------------------------------------

describe("shouldStopPolling", () => {
  it("returns true for terminal status", () => {
    expect(shouldStopPolling("complete", undefined)).toBe(true);
    expect(shouldStopPolling("failed", undefined)).toBe(true);
    expect(shouldStopPolling("cancelled", undefined)).toBe(true);
  });

  it("returns true for 404 response", () => {
    expect(shouldStopPolling("running", 404)).toBe(true);
  });

  it("returns false for running with no http status", () => {
    expect(shouldStopPolling("running", undefined)).toBe(false);
  });

  it("returns false for pending with 500 (transient error)", () => {
    expect(shouldStopPolling("pending", 500)).toBe(false);
  });
});

// ---------------------------------------------------------------------------
// deriveOptimizationMetrics
// ---------------------------------------------------------------------------

function makeRunRecord(overrides: Partial<RunRecord> = {}): RunRecord {
  return {
    id: "01HZ0000000000000000000001",
    strategy_build_id: "01HZ0000000000000000000002",
    run_type: "research",
    status: "running",
    config: {},
    result_uri: null,
    created_by: "user-001",
    created_at: "2026-04-04T10:00:00Z",
    updated_at: "2026-04-04T10:05:00Z",
    started_at: "2026-04-04T10:01:00Z",
    completed_at: null,
    ...overrides,
  };
}

describe("deriveOptimizationMetrics", () => {
  it("returns null for non-optimization runs", () => {
    const run = makeRunRecord({ run_type: "research" });
    expect(deriveOptimizationMetrics(run)).toBeNull();
  });

  it("returns null when trial_count is undefined", () => {
    const run = makeRunRecord({ run_type: "optimization" });
    expect(deriveOptimizationMetrics(run)).toBeNull();
  });

  it("returns null when completed_trials is undefined", () => {
    const run = makeRunRecord({ run_type: "optimization", trial_count: 100 });
    expect(deriveOptimizationMetrics(run)).toBeNull();
  });

  it("calculates metrics for running optimization", () => {
    const run = makeRunRecord({
      run_type: "optimization",
      trial_count: 100,
      completed_trials: 20,
      started_at: "2026-04-04T10:00:00Z",
      completed_at: null,
    });

    const metrics = deriveOptimizationMetrics(run);
    expect(metrics).not.toBeNull();
    expect(metrics!.totalTrials).toBe(100);
    expect(metrics!.completedTrials).toBe(20);
    expect(metrics!.bestObjectiveValue).toBeNull();
    expect(metrics!.bestTrialIndex).toBeNull();
    expect(metrics!.trialsPerMinute).toBeGreaterThan(0);
  });

  it("returns zero trialsPerMinute when no trials completed", () => {
    const run = makeRunRecord({
      run_type: "optimization",
      trial_count: 100,
      completed_trials: 0,
      started_at: "2026-04-04T10:00:00Z",
    });

    const metrics = deriveOptimizationMetrics(run);
    expect(metrics!.trialsPerMinute).toBe(0);
  });

  it("returns zero trialsPerMinute when started_at is null", () => {
    const run = makeRunRecord({
      run_type: "optimization",
      trial_count: 100,
      completed_trials: 5,
      started_at: null,
    });

    const metrics = deriveOptimizationMetrics(run);
    expect(metrics!.trialsPerMinute).toBe(0);
  });

  it("handles invalid started_at gracefully", () => {
    const run = makeRunRecord({
      run_type: "optimization",
      trial_count: 100,
      completed_trials: 5,
      started_at: "not-a-date",
    });

    const metrics = deriveOptimizationMetrics(run);
    expect(metrics!.trialsPerMinute).toBe(0);
  });

  it("uses completed_at for elapsed time when available", () => {
    const run = makeRunRecord({
      run_type: "optimization",
      trial_count: 100,
      completed_trials: 60,
      started_at: "2026-04-04T10:00:00Z",
      completed_at: "2026-04-04T11:00:00Z", // 60 minutes
    });

    const metrics = deriveOptimizationMetrics(run);
    // 60 trials / 60 minutes = 1 trial/min
    expect(metrics!.trialsPerMinute).toBe(1);
  });
});

// ---------------------------------------------------------------------------
// validateResultUri
// ---------------------------------------------------------------------------

describe("validateResultUri", () => {
  it("allows https:// URIs", () => {
    expect(validateResultUri("https://bucket.s3.amazonaws.com/results.parquet")).toBe(true);
  });

  it("allows http:// URIs", () => {
    expect(validateResultUri("http://internal-api/results")).toBe(true);
  });

  it("allows s3:// URIs", () => {
    expect(validateResultUri("s3://bucket/results.parquet")).toBe(true);
  });

  it("allows gs:// URIs", () => {
    expect(validateResultUri("gs://bucket/results.parquet")).toBe(true);
  });

  it("rejects javascript: URIs (XSS prevention)", () => {
    expect(validateResultUri("javascript:alert(1)")).toBe(false);
  });

  it("rejects data: URIs", () => {
    expect(validateResultUri("data:text/html,<script>alert(1)</script>")).toBe(false);
  });

  it("rejects vbscript: URIs", () => {
    expect(validateResultUri("vbscript:msgbox")).toBe(false);
  });

  it("rejects empty string", () => {
    expect(validateResultUri("")).toBe(false);
  });

  it("rejects null/undefined", () => {
    expect(validateResultUri(null)).toBe(false);
    expect(validateResultUri(undefined)).toBe(false);
  });

  it("rejects URIs with mixed-case javascript scheme", () => {
    expect(validateResultUri("JavaScript:alert(1)")).toBe(false);
  });
});

// ---------------------------------------------------------------------------
// validateUlid
// ---------------------------------------------------------------------------

describe("validateUlid", () => {
  it("accepts valid ULID", () => {
    expect(validateUlid("01HZ0000000000000000000001")).toBe(true);
  });

  it("rejects too-short string", () => {
    expect(validateUlid("01HZ00000")).toBe(false);
  });

  it("rejects too-long string", () => {
    expect(validateUlid("01HZ00000000000000000000011")).toBe(false);
  });

  it("rejects lowercase (ULIDs are uppercase Crockford base32)", () => {
    expect(validateUlid("01hz0000000000000000000001")).toBe(false);
  });

  it("rejects strings with invalid characters", () => {
    expect(validateUlid("01HZ000000000000000000000!")).toBe(false);
  });

  it("rejects empty string", () => {
    expect(validateUlid("")).toBe(false);
  });

  it("rejects null/undefined", () => {
    expect(validateUlid(null as unknown as string)).toBe(false);
    expect(validateUlid(undefined as unknown as string)).toBe(false);
  });
});

// ---------------------------------------------------------------------------
// safeParseDateMs
// ---------------------------------------------------------------------------

describe("safeParseDateMs", () => {
  it("parses valid ISO-8601 date", () => {
    expect(safeParseDateMs("2026-04-04T10:00:00Z")).toBe(
      new Date("2026-04-04T10:00:00Z").getTime(),
    );
  });

  it("returns null for invalid date string", () => {
    expect(safeParseDateMs("not-a-date")).toBeNull();
  });

  it("returns null for empty string", () => {
    expect(safeParseDateMs("")).toBeNull();
  });

  it("returns null for null input", () => {
    expect(safeParseDateMs(null)).toBeNull();
  });

  it("returns null for undefined input", () => {
    expect(safeParseDateMs(undefined)).toBeNull();
  });
});

// ---------------------------------------------------------------------------
// safeJsonStringify
// ---------------------------------------------------------------------------

describe("safeJsonStringify", () => {
  it("stringifies simple object", () => {
    expect(safeJsonStringify({ a: 1 })).toBe('{"a":1}');
  });

  it("returns fallback for circular reference", () => {
    const circular: Record<string, unknown> = {};
    circular.self = circular;
    expect(safeJsonStringify(circular)).toBe("[unserializable]");
  });

  it("returns fallback for custom fallback string", () => {
    const circular: Record<string, unknown> = {};
    circular.self = circular;
    expect(safeJsonStringify(circular, "N/A")).toBe("N/A");
  });

  it("stringifies null", () => {
    expect(safeJsonStringify(null)).toBe("null");
  });

  it("stringifies arrays", () => {
    expect(safeJsonStringify([1, 2, 3])).toBe("[1,2,3]");
  });
});

// ---------------------------------------------------------------------------
// isTransientError
// ---------------------------------------------------------------------------

describe("isTransientError", () => {
  it("returns true for ERR_NETWORK error code", () => {
    const err = { code: "ERR_NETWORK", message: "Network Error" };
    expect(isTransientError(err)).toBe(true);
  });

  it("returns true for ECONNABORTED error code", () => {
    const err = { code: "ECONNABORTED", message: "timeout" };
    expect(isTransientError(err)).toBe(true);
  });

  it("returns true for 500 server error response", () => {
    const err = { response: { status: 500 } };
    expect(isTransientError(err)).toBe(true);
  });

  it("returns true for 502 bad gateway response", () => {
    const err = { response: { status: 502 } };
    expect(isTransientError(err)).toBe(true);
  });

  it("returns true for 503 service unavailable response", () => {
    const err = { response: { status: 503 } };
    expect(isTransientError(err)).toBe(true);
  });

  it("returns true for 504 gateway timeout response", () => {
    const err = { response: { status: 504 } };
    expect(isTransientError(err)).toBe(true);
  });

  it("returns true for 429 rate limit response", () => {
    const err = { response: { status: 429 } };
    expect(isTransientError(err)).toBe(true);
  });

  it("returns false for 400 bad request (permanent)", () => {
    const err = { response: { status: 400 } };
    expect(isTransientError(err)).toBe(false);
  });

  it("returns false for 401 unauthorized (permanent)", () => {
    const err = { response: { status: 401 } };
    expect(isTransientError(err)).toBe(false);
  });

  it("returns false for 403 forbidden (permanent)", () => {
    const err = { response: { status: 403 } };
    expect(isTransientError(err)).toBe(false);
  });

  it("returns false for 404 not found (permanent)", () => {
    const err = { response: { status: 404 } };
    expect(isTransientError(err)).toBe(false);
  });

  it("returns false for 422 validation error (permanent)", () => {
    const err = { response: { status: 422 } };
    expect(isTransientError(err)).toBe(false);
  });

  it("returns false for null input", () => {
    expect(isTransientError(null)).toBe(false);
  });

  it("returns false for undefined input", () => {
    expect(isTransientError(undefined)).toBe(false);
  });

  it("returns false for string input", () => {
    expect(isTransientError("error string")).toBe(false);
  });

  it("returns false for number input", () => {
    expect(isTransientError(42)).toBe(false);
  });

  it("returns false for plain Error without code or response", () => {
    expect(isTransientError(new Error("generic error"))).toBe(false);
  });

  it("returns false when response exists but has no status", () => {
    const err = { response: {} };
    expect(isTransientError(err)).toBe(false);
  });
});

// ---------------------------------------------------------------------------
// calculateRetryDelay
// ---------------------------------------------------------------------------

describe("calculateRetryDelay", () => {
  it("returns delay in expected range for attempt 0", () => {
    // attempt 0: baseMs * 2^0 = 1000, jitter 0-500 → range [1000, 1500]
    const delay = calculateRetryDelay(0, SUBMISSION_RETRY_BASE_MS);
    expect(delay).toBeGreaterThanOrEqual(SUBMISSION_RETRY_BASE_MS);
    expect(delay).toBeLessThanOrEqual(SUBMISSION_RETRY_BASE_MS * 1.5);
  });

  it("returns delay in expected range for attempt 1", () => {
    // attempt 1: baseMs * 2^1 = 2000, jitter 0-1000 → range [2000, 3000]
    const delay = calculateRetryDelay(1, SUBMISSION_RETRY_BASE_MS);
    expect(delay).toBeGreaterThanOrEqual(SUBMISSION_RETRY_BASE_MS * 2);
    expect(delay).toBeLessThanOrEqual(SUBMISSION_RETRY_BASE_MS * 3);
  });

  it("returns delay in expected range for attempt 2", () => {
    // attempt 2: baseMs * 2^2 = 4000, jitter 0-2000 → range [4000, 6000]
    const delay = calculateRetryDelay(2, SUBMISSION_RETRY_BASE_MS);
    expect(delay).toBeGreaterThanOrEqual(SUBMISSION_RETRY_BASE_MS * 4);
    expect(delay).toBeLessThanOrEqual(SUBMISSION_RETRY_BASE_MS * 6);
  });

  it("produces deterministic result when Math.random returns 0", () => {
    vi.spyOn(Math, "random").mockReturnValue(0);
    const delay = calculateRetryDelay(0, 1000);
    expect(delay).toBe(1000); // exponentialDelay + 0 jitter
    vi.restoreAllMocks();
  });

  it("produces max jitter result when Math.random returns ~1", () => {
    vi.spyOn(Math, "random").mockReturnValue(0.999);
    const delay = calculateRetryDelay(0, 1000);
    // exponentialDelay=1000, jitter=1000*0.5*0.999=499.5 → ~1499.5
    expect(delay).toBeCloseTo(1499.5, 0);
    vi.restoreAllMocks();
  });

  it("SUBMISSION_MAX_RETRIES is 2", () => {
    expect(SUBMISSION_MAX_RETRIES).toBe(2);
  });

  it("SUBMISSION_RETRY_BASE_MS is 1000", () => {
    expect(SUBMISSION_RETRY_BASE_MS).toBe(1000);
  });
});
