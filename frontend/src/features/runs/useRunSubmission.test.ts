/**
 * Tests for useRunSubmission hook — run submission lifecycle management.
 *
 * Verifies:
 *   - Research run submission calls the correct API and returns RunRecord.
 *   - Optimization run submission calls the correct API and returns RunRecord.
 *   - Loading state tracks in-flight submissions.
 *   - Error state captures submission failures.
 *   - clearError resets error state.
 *   - Errors are re-thrown for caller handling.
 */

import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { renderHook, act } from "@testing-library/react";
import { useRunSubmission } from "./useRunSubmission";
import { runsApi } from "./api";
import type { RunRecord } from "@/types/run";
import { SUBMISSION_MAX_RETRIES } from "./services/RunMonitorService";

// ---------------------------------------------------------------------------
// Mock API
// ---------------------------------------------------------------------------

vi.mock("./api", () => ({
  runsApi: {
    submitResearchRun: vi.fn(),
    submitOptimizationRun: vi.fn(),
  },
}));

// Mock RunLogger to prevent actual HTTP calls during tests
vi.mock("./services/RunLogger", () => ({
  RunLogger: vi.fn().mockImplementation(() => ({
    correlationId: "test-correlation-id",
    logSubmissionStarted: vi.fn().mockResolvedValue(undefined),
    logSubmissionSucceeded: vi.fn().mockResolvedValue(undefined),
    logSubmissionFailed: vi.fn().mockResolvedValue(undefined),
  })),
}));

const mockSubmitResearch = vi.mocked(runsApi.submitResearchRun);
const mockSubmitOptimization = vi.mocked(runsApi.submitOptimizationRun);

// ---------------------------------------------------------------------------
// Fixtures
// ---------------------------------------------------------------------------

function makePendingRun(runType: "research" | "optimization" = "research"): RunRecord {
  return {
    id: "01HZ0000000000000000000001",
    strategy_build_id: "01HZ0000000000000000000002",
    run_type: runType,
    status: "pending",
    config: { instrument: "EURUSD" },
    result_uri: null,
    created_by: "user-001",
    created_at: "2026-04-04T10:00:00Z",
    updated_at: "2026-04-04T10:00:00Z",
    started_at: null,
    completed_at: null,
  };
}

// ---------------------------------------------------------------------------
// Setup
// ---------------------------------------------------------------------------

beforeEach(() => {
  vi.clearAllMocks();
});

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("useRunSubmission", () => {
  describe("submitResearch", () => {
    it("submits a research run and returns the created record", async () => {
      const run = makePendingRun("research");
      mockSubmitResearch.mockResolvedValue(run);

      const { result } = renderHook(() => useRunSubmission());

      let returnedRun: RunRecord | undefined;
      await act(async () => {
        returnedRun = await result.current.submitResearch({
          strategy_build_id: "01HZ0000000000000000000002",
          config: { instrument: "EURUSD" },
        });
      });

      expect(returnedRun).toEqual(run);
      expect(mockSubmitResearch).toHaveBeenCalledWith({
        strategy_build_id: "01HZ0000000000000000000002",
        config: { instrument: "EURUSD" },
      });
      expect(result.current.isSubmitting).toBe(false);
      expect(result.current.error).toBeNull();
    });

    it("sets isSubmitting during request", async () => {
      let resolvePromise: (value: RunRecord) => void;
      const pending = new Promise<RunRecord>((resolve) => {
        resolvePromise = resolve;
      });
      mockSubmitResearch.mockReturnValue(pending);

      const { result } = renderHook(() => useRunSubmission());

      // Start submission (don't await)
      let submissionPromise: Promise<RunRecord>;
      act(() => {
        submissionPromise = result.current.submitResearch({
          strategy_build_id: "01HZ002",
          config: {},
        });
      });

      // Should be submitting while request is in flight
      expect(result.current.isSubmitting).toBe(true);

      // Resolve the promise
      await act(async () => {
        resolvePromise!(makePendingRun());
        await submissionPromise!;
      });

      expect(result.current.isSubmitting).toBe(false);
    });

    it("sets error state on failure and re-throws", async () => {
      mockSubmitResearch.mockRejectedValue(new Error("422 Validation Error"));

      const { result } = renderHook(() => useRunSubmission());

      let caughtError: unknown = null;
      await act(async () => {
        try {
          await result.current.submitResearch({
            strategy_build_id: "01HZ002",
            config: {},
          });
        } catch (err) {
          caughtError = err as Error;
        }
      });

      expect((caughtError as Error)?.message).toBe("422 Validation Error");
      expect(result.current.error?.message).toBe("422 Validation Error");
      expect(result.current.isSubmitting).toBe(false);
    });
  });

  describe("submitOptimization", () => {
    it("submits an optimization run and returns the created record", async () => {
      const run = makePendingRun("optimization");
      mockSubmitOptimization.mockResolvedValue(run);

      const { result } = renderHook(() => useRunSubmission());

      let returnedRun: RunRecord | undefined;
      await act(async () => {
        returnedRun = await result.current.submitOptimization({
          strategy_build_id: "01HZ0000000000000000000002",
          config: { objective: "sharpe" },
          max_trials: 100,
        });
      });

      expect(returnedRun).toEqual(run);
      expect(mockSubmitOptimization).toHaveBeenCalledWith({
        strategy_build_id: "01HZ0000000000000000000002",
        config: { objective: "sharpe" },
        max_trials: 100,
      });
    });

    it("sets error state on optimization failure", async () => {
      mockSubmitOptimization.mockRejectedValue(new Error("Preflight failed"));

      const { result } = renderHook(() => useRunSubmission());

      let caughtError: unknown = null;
      await act(async () => {
        try {
          await result.current.submitOptimization({
            strategy_build_id: "01HZ002",
            config: {},
            max_trials: 50,
          });
        } catch (err) {
          caughtError = err as Error;
        }
      });

      expect((caughtError as Error)?.message).toBe("Preflight failed");
      expect(result.current.error?.message).toBe("Preflight failed");
    });
  });

  describe("clearError", () => {
    it("resets error state to null", async () => {
      mockSubmitResearch.mockRejectedValue(new Error("Submission failed"));

      const { result } = renderHook(() => useRunSubmission());

      // Cause an error
      await act(async () => {
        try {
          await result.current.submitResearch({
            strategy_build_id: "01HZ002",
            config: {},
          });
        } catch {
          // Expected
        }
      });

      expect(result.current.error).not.toBeNull();

      // Clear it
      act(() => {
        result.current.clearError();
      });

      expect(result.current.error).toBeNull();
    });
  });

  describe("initial state", () => {
    it("starts with isSubmitting false and no error", () => {
      const { result } = renderHook(() => useRunSubmission());

      expect(result.current.isSubmitting).toBe(false);
      expect(result.current.error).toBeNull();
    });
  });

  // -------------------------------------------------------------------------
  // Transient retry behaviour (§9 exponential backoff + jitter)
  // -------------------------------------------------------------------------

  describe("transient retry", () => {
    beforeEach(() => {
      vi.useFakeTimers({ shouldAdvanceTime: true });
    });

    afterEach(() => {
      vi.useRealTimers();
    });

    it("retries transient 500 errors and succeeds on second attempt", async () => {
      const transient500 = Object.assign(new Error("Internal Server Error"), {
        response: { status: 500 },
      });
      const run = makePendingRun("research");

      // First call: 500, second call: success
      mockSubmitResearch.mockRejectedValueOnce(transient500).mockResolvedValueOnce(run);

      const { result } = renderHook(() => useRunSubmission());

      let returnedRun: RunRecord | undefined;
      await act(async () => {
        returnedRun = await result.current.submitResearch({
          strategy_build_id: "01HZ0000000000000000000002",
          config: {},
        });
      });

      expect(returnedRun).toEqual(run);
      expect(mockSubmitResearch).toHaveBeenCalledTimes(2);
      expect(result.current.error).toBeNull();
    });

    it("retries network errors (ERR_NETWORK) and succeeds", async () => {
      const networkError = Object.assign(new Error("Network Error"), {
        code: "ERR_NETWORK",
      });
      const run = makePendingRun("optimization");

      mockSubmitOptimization.mockRejectedValueOnce(networkError).mockResolvedValueOnce(run);

      const { result } = renderHook(() => useRunSubmission());

      let returnedRun: RunRecord | undefined;
      await act(async () => {
        returnedRun = await result.current.submitOptimization({
          strategy_build_id: "01HZ0000000000000000000002",
          config: {},
          max_trials: 50,
        });
      });

      expect(returnedRun).toEqual(run);
      expect(mockSubmitOptimization).toHaveBeenCalledTimes(2);
    });

    it("does NOT retry 422 validation errors (permanent failure)", async () => {
      const validationError = Object.assign(new Error("Validation Error"), {
        response: { status: 422 },
      });

      mockSubmitResearch.mockRejectedValue(validationError);

      const { result } = renderHook(() => useRunSubmission());

      let caughtError: unknown = null;
      await act(async () => {
        try {
          await result.current.submitResearch({
            strategy_build_id: "01HZ002",
            config: {},
          });
        } catch (err) {
          caughtError = err;
        }
      });

      // Should only be called once — no retries for 422
      expect(mockSubmitResearch).toHaveBeenCalledTimes(1);
      expect((caughtError as Error)?.message).toBe("Validation Error");
      expect(result.current.error?.message).toBe("Validation Error");
    });

    it("does NOT retry 401 auth errors (permanent failure)", async () => {
      const authError = Object.assign(new Error("Unauthorized"), {
        response: { status: 401 },
      });

      mockSubmitResearch.mockRejectedValue(authError);

      const { result } = renderHook(() => useRunSubmission());

      let caughtError: unknown = null;
      await act(async () => {
        try {
          await result.current.submitResearch({
            strategy_build_id: "01HZ002",
            config: {},
          });
        } catch (err) {
          caughtError = err;
        }
      });

      expect(mockSubmitResearch).toHaveBeenCalledTimes(1);
      expect((caughtError as Error)?.message).toBe("Unauthorized");
    });

    it("exhausts all retries on persistent transient failure and sets error", async () => {
      const transient503 = Object.assign(new Error("Service Unavailable"), {
        response: { status: 503 },
      });

      mockSubmitResearch.mockRejectedValue(transient503);

      const { result } = renderHook(() => useRunSubmission());

      let caughtError: unknown = null;
      await act(async () => {
        try {
          await result.current.submitResearch({
            strategy_build_id: "01HZ002",
            config: {},
          });
        } catch (err) {
          caughtError = err;
        }
      });

      // 1 initial attempt + SUBMISSION_MAX_RETRIES retries
      expect(mockSubmitResearch).toHaveBeenCalledTimes(SUBMISSION_MAX_RETRIES + 1);
      expect((caughtError as Error)?.message).toBe("Service Unavailable");
      expect(result.current.error?.message).toBe("Service Unavailable");
      expect(result.current.isSubmitting).toBe(false);
    });

    it("retries 429 rate limit errors", async () => {
      const rateLimitError = Object.assign(new Error("Too Many Requests"), {
        response: { status: 429 },
      });
      const run = makePendingRun("research");

      mockSubmitResearch.mockRejectedValueOnce(rateLimitError).mockResolvedValueOnce(run);

      const { result } = renderHook(() => useRunSubmission());

      let returnedRun: RunRecord | undefined;
      await act(async () => {
        returnedRun = await result.current.submitResearch({
          strategy_build_id: "01HZ0000000000000000000002",
          config: {},
        });
      });

      expect(returnedRun).toEqual(run);
      expect(mockSubmitResearch).toHaveBeenCalledTimes(2);
    });

    it("retries ECONNABORTED timeout errors", async () => {
      const timeoutError = Object.assign(new Error("timeout"), {
        code: "ECONNABORTED",
      });
      const run = makePendingRun("research");

      mockSubmitResearch.mockRejectedValueOnce(timeoutError).mockResolvedValueOnce(run);

      const { result } = renderHook(() => useRunSubmission());

      let returnedRun: RunRecord | undefined;
      await act(async () => {
        returnedRun = await result.current.submitResearch({
          strategy_build_id: "01HZ0000000000000000000002",
          config: {},
        });
      });

      expect(returnedRun).toEqual(run);
      expect(mockSubmitResearch).toHaveBeenCalledTimes(2);
    });
  });
});
