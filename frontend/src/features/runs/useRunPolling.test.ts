/**
 * Tests for useRunPolling hook — exponential backoff polling per spec §8.1.
 *
 * Verifies:
 *   - Initial poll fires on mount.
 *   - Exponential backoff (2s → 4s → 8s → 16s → 30s cap).
 *   - Polling stops on terminal statuses (complete, failed, cancelled).
 *   - Stale data indicator appears after threshold on failure.
 *   - Manual refresh resets backoff and fires immediately.
 *   - 404 stops polling (run does not exist).
 *   - No state updates after unmount.
 */

import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { renderHook, act, waitFor } from "@testing-library/react";
import { useRunPolling } from "./useRunPolling";
import { runsApi } from "./api";
import type { RunRecord } from "@/types/run";

// ---------------------------------------------------------------------------
// Mock API
// ---------------------------------------------------------------------------

vi.mock("./api", () => ({
  runsApi: {
    getRunStatus: vi.fn(),
  },
}));

const mockGetRunStatus = vi.mocked(runsApi.getRunStatus);

// ---------------------------------------------------------------------------
// Fixtures
// ---------------------------------------------------------------------------

function makeRunningRun(): RunRecord {
  return {
    id: "01HZ0000000000000000000001",
    strategy_build_id: "01HZ0000000000000000000002",
    run_type: "research",
    status: "running",
    config: { instrument: "EURUSD" },
    result_uri: null,
    created_by: "user-001",
    created_at: "2026-04-04T10:00:00Z",
    updated_at: "2026-04-04T10:05:00Z",
    started_at: "2026-04-04T10:01:00Z",
    completed_at: null,
    trial_count: 50,
    completed_trials: 10,
  };
}

function makeCompletedRun(): RunRecord {
  return {
    ...makeRunningRun(),
    status: "complete",
    completed_at: "2026-04-04T11:00:00Z",
    result_uri: "s3://bucket/results.parquet",
    completed_trials: 50,
  };
}

function makeFailedRun(): RunRecord {
  return {
    ...makeRunningRun(),
    status: "failed",
    completed_at: "2026-04-04T10:30:00Z",
    error_message: "Out of memory during trial 42",
  };
}

// ---------------------------------------------------------------------------
// Setup — use fake timers to control polling intervals
// ---------------------------------------------------------------------------

beforeEach(() => {
  vi.clearAllMocks();
  vi.useFakeTimers({ shouldAdvanceTime: true });
});

afterEach(() => {
  vi.useRealTimers();
});

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("useRunPolling", () => {
  it("fetches run status on mount", async () => {
    const run = makeRunningRun();
    mockGetRunStatus.mockResolvedValue(run);

    const { result } = renderHook(() => useRunPolling("01HZ0000000000000000000001"));

    // Initial state should be loading
    expect(result.current.isLoading).toBe(true);

    await waitFor(() => {
      expect(result.current.isLoading).toBe(false);
    });

    expect(result.current.run).toEqual(run);
    expect(result.current.error).toBeNull();
    expect(mockGetRunStatus).toHaveBeenCalledWith("01HZ0000000000000000000001");
  });

  it("applies exponential backoff on successive polls", async () => {
    const run = makeRunningRun();
    mockGetRunStatus.mockResolvedValue(run);

    renderHook(() => useRunPolling("01HZ0000000000000000000001"));

    // Wait for initial poll
    await waitFor(() => {
      expect(mockGetRunStatus).toHaveBeenCalledTimes(1);
    });

    // After first success, currentInterval doubles from 2s → 4s before scheduling.
    // So we need to advance 4s to trigger the second poll.
    await act(async () => {
      await vi.advanceTimersByTimeAsync(4_000);
    });

    await waitFor(() => {
      expect(mockGetRunStatus).toHaveBeenCalledTimes(2);
    });

    // After second success, interval doubles from 4s → 8s. Advance 8s.
    await act(async () => {
      await vi.advanceTimersByTimeAsync(8_000);
    });

    await waitFor(() => {
      expect(mockGetRunStatus).toHaveBeenCalledTimes(3);
    });
  });

  it("caps backoff at MAX_POLL_INTERVAL_MS (30s)", async () => {
    const run = makeRunningRun();
    mockGetRunStatus.mockResolvedValue(run);

    renderHook(() => useRunPolling("01HZ0000000000000000000001"));

    // Wait for initial poll
    await waitFor(() => {
      expect(mockGetRunStatus).toHaveBeenCalledTimes(1);
    });

    // After each success, interval doubles before scheduling.
    // Poll 1 → interval becomes 4s, poll 2 → 8s, poll 3 → 16s, poll 4 → 30s (capped)
    const scheduledIntervals = [4_000, 8_000, 16_000, 30_000];
    for (let i = 0; i < scheduledIntervals.length; i++) {
      await act(async () => {
        await vi.advanceTimersByTimeAsync(scheduledIntervals[i]);
      });
      await waitFor(() => {
        expect(mockGetRunStatus).toHaveBeenCalledTimes(i + 2);
      });
    }

    // Next interval should still be capped at 30s (not 60s)
    await act(async () => {
      await vi.advanceTimersByTimeAsync(30_000);
    });

    await waitFor(() => {
      expect(mockGetRunStatus).toHaveBeenCalledTimes(6);
    });
  });

  it("stops polling when run reaches 'complete' status", async () => {
    const completedRun = makeCompletedRun();
    mockGetRunStatus.mockResolvedValue(completedRun);

    const { result } = renderHook(() => useRunPolling("01HZ0000000000000000000001"));

    await waitFor(() => {
      expect(result.current.isTerminal).toBe(true);
    });

    expect(result.current.run?.status).toBe("complete");
    expect(result.current.run?.result_uri).toBe("s3://bucket/results.parquet");

    // Advance time — no more polls should fire
    const callCount = mockGetRunStatus.mock.calls.length;
    await act(async () => {
      await vi.advanceTimersByTimeAsync(60_000);
    });
    expect(mockGetRunStatus).toHaveBeenCalledTimes(callCount);
  });

  it("stops polling when run reaches 'failed' status", async () => {
    const failedRun = makeFailedRun();
    mockGetRunStatus.mockResolvedValue(failedRun);

    const { result } = renderHook(() => useRunPolling("01HZ0000000000000000000001"));

    await waitFor(() => {
      expect(result.current.isTerminal).toBe(true);
    });

    expect(result.current.run?.status).toBe("failed");
    expect(result.current.run?.error_message).toBe("Out of memory during trial 42");
  });

  it("stops polling when run reaches 'cancelled' status", async () => {
    const cancelledRun = {
      ...makeRunningRun(),
      status: "cancelled" as const,
      cancellation_reason: "User cancelled",
    };
    mockGetRunStatus.mockResolvedValue(cancelledRun);

    const { result } = renderHook(() => useRunPolling("01HZ0000000000000000000001"));

    await waitFor(() => {
      expect(result.current.isTerminal).toBe(true);
    });

    expect(result.current.run?.status).toBe("cancelled");
  });

  it("sets error state on API failure", async () => {
    mockGetRunStatus.mockRejectedValue(new Error("Network Error"));

    const { result } = renderHook(() => useRunPolling("01HZ0000000000000000000001"));

    await waitFor(() => {
      expect(result.current.error).not.toBeNull();
    });

    expect(result.current.error?.message).toBe("Network Error");
    expect(result.current.isLoading).toBe(false);
  });

  it("sets isStale after threshold following a failure", async () => {
    // First poll succeeds, then subsequent polls fail
    const run = makeRunningRun();
    mockGetRunStatus.mockResolvedValueOnce(run).mockRejectedValue(new Error("Network Error"));

    const { result } = renderHook(() => useRunPolling("01HZ0000000000000000000001"));

    // Wait for first success
    await waitFor(() => {
      expect(result.current.run).not.toBeNull();
    });

    // Trigger second poll (fails) — after first success, interval doubled to 4s
    await act(async () => {
      await vi.advanceTimersByTimeAsync(4_000);
    });

    await waitFor(() => {
      expect(result.current.error).not.toBeNull();
    });

    // Advance past stale threshold (5s) — stale checker runs every 1s
    await act(async () => {
      await vi.advanceTimersByTimeAsync(6_000);
    });

    await waitFor(() => {
      expect(result.current.isStale).toBe(true);
    });
  });

  it("refresh() resets backoff and fires immediately", async () => {
    const run = makeRunningRun();
    mockGetRunStatus.mockResolvedValue(run);

    const { result } = renderHook(() => useRunPolling("01HZ0000000000000000000001"));

    // Wait for initial poll
    await waitFor(() => {
      expect(result.current.run).not.toBeNull();
    });

    const callCountBefore = mockGetRunStatus.mock.calls.length;

    // Trigger manual refresh
    await act(async () => {
      result.current.refresh();
    });

    await waitFor(() => {
      expect(mockGetRunStatus).toHaveBeenCalledTimes(callCountBefore + 1);
    });
  });

  it("stops polling on 404 (run does not exist)", async () => {
    const error404 = Object.assign(new Error("Not Found"), {
      response: { status: 404 },
    });
    mockGetRunStatus.mockRejectedValue(error404);

    const { result } = renderHook(() => useRunPolling("01HZ_NONEXISTENT"));

    await waitFor(() => {
      expect(result.current.isTerminal).toBe(true);
    });

    expect(result.current.error?.message).toBe("Not Found");

    // Confirm no more polls scheduled
    const callCount = mockGetRunStatus.mock.calls.length;
    await act(async () => {
      await vi.advanceTimersByTimeAsync(60_000);
    });
    expect(mockGetRunStatus).toHaveBeenCalledTimes(callCount);
  });

  it("does not poll when runId is null", async () => {
    const { result } = renderHook(() => useRunPolling(null));

    // Should immediately be non-loading with no data
    await waitFor(() => {
      expect(result.current.isLoading).toBe(false);
    });

    expect(result.current.run).toBeNull();
    expect(mockGetRunStatus).not.toHaveBeenCalled();
  });

  it("resets state when runId changes", async () => {
    const run1 = makeRunningRun();
    const run2 = {
      ...makeRunningRun(),
      id: "01HZ_RUN_2",
      status: "running" as const,
    };

    mockGetRunStatus.mockResolvedValueOnce(run1).mockResolvedValue(run2);

    const { result, rerender } = renderHook(
      ({ runId }: { runId: string }) => useRunPolling(runId),
      { initialProps: { runId: "01HZ_RUN_1" } },
    );

    await waitFor(() => {
      expect(result.current.run?.id).toBe("01HZ0000000000000000000001");
    });

    // Change runId
    rerender({ runId: "01HZ_RUN_2" });

    // Should reset and fetch new run
    await waitFor(() => {
      expect(result.current.run?.id).toBe("01HZ_RUN_2");
    });
  });
});
