/**
 * Tests for the runs API service layer.
 *
 * Verifies that all API functions:
 *   - Make the correct HTTP requests with proper URLs and payloads.
 *   - Validate responses with Zod schemas before returning.
 *   - Propagate errors from axios and Zod to the caller.
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import type { AxiosResponse, InternalAxiosRequestConfig } from "axios";
import { apiClient } from "@/api/client";
import { runsApi } from "./api";
import type { RunRecord, TrialRecord } from "@/types/run";

// ---------------------------------------------------------------------------
// Mock apiClient
// ---------------------------------------------------------------------------

vi.mock("@/api/client", () => ({
  apiClient: {
    get: vi.fn(),
    post: vi.fn(),
    delete: vi.fn(),
  },
}));

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/**
 * Create a properly typed mock AxiosResponse.
 *
 * Eliminates `as any` casts by providing all required AxiosResponse fields.
 */
function mockAxiosResponse<T>(data: T, status = 200): AxiosResponse<T> {
  return {
    data,
    status,
    statusText: "OK",
    headers: {},
    config: {
      headers: {},
    } as InternalAxiosRequestConfig,
  };
}

function makeValidRunRecord(): RunRecord {
  return {
    id: "01HZ0000000000000000000001",
    strategy_build_id: "01HZ0000000000000000000002",
    run_type: "research",
    status: "pending",
    config: { instrument: "EURUSD", timeframe: "1h" },
    result_uri: null,
    created_by: "user-ulid-001",
    created_at: "2026-04-04T10:00:00Z",
    updated_at: "2026-04-04T10:00:00Z",
    started_at: null,
    completed_at: null,
  };
}

function makeValidTrialRecord(): TrialRecord {
  return {
    id: "01HZ0000000000000000000010",
    run_id: "01HZ0000000000000000000001",
    trial_index: 0,
    status: "completed",
    parameters: { lookback: 20 },
    seed: 42,
    metrics: { sharpe: 1.5 },
    created_at: "2026-04-04T10:02:00Z",
    updated_at: "2026-04-04T10:03:00Z",
  };
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

const mockPost = vi.mocked(apiClient.post);
const mockGet = vi.mocked(apiClient.get);

beforeEach(() => {
  vi.clearAllMocks();
});

// ---------------------------------------------------------------------------
// submitResearchRun
// ---------------------------------------------------------------------------

describe("runsApi.submitResearchRun", () => {
  it("sends POST to /runs/research with correct payload", async () => {
    const runRecord = makeValidRunRecord();
    mockPost.mockResolvedValue(mockAxiosResponse(runRecord));

    const payload = {
      strategy_build_id: "01HZ0000000000000000000002",
      config: { instrument: "EURUSD", timeframe: "1h" },
    };

    const result = await runsApi.submitResearchRun(payload);

    expect(mockPost).toHaveBeenCalledWith("/runs/research", payload);
    expect(result.id).toBe("01HZ0000000000000000000001");
    expect(result.status).toBe("pending");
  });

  it("validates response with Zod and rejects invalid data", async () => {
    mockPost.mockResolvedValue(mockAxiosResponse({ id: "01HZ001", bad_field: true }));

    const payload = {
      strategy_build_id: "01HZ002",
      config: {},
    };

    await expect(runsApi.submitResearchRun(payload)).rejects.toThrow();
  });

  it("propagates network errors", async () => {
    mockPost.mockRejectedValue(new Error("Network Error"));

    const payload = {
      strategy_build_id: "01HZ002",
      config: {},
    };

    await expect(runsApi.submitResearchRun(payload)).rejects.toThrow("Network Error");
  });
});

// ---------------------------------------------------------------------------
// submitOptimizationRun
// ---------------------------------------------------------------------------

describe("runsApi.submitOptimizationRun", () => {
  it("sends POST to /runs/optimize with correct payload", async () => {
    const runRecord = {
      ...makeValidRunRecord(),
      run_type: "optimization" as const,
    };
    mockPost.mockResolvedValue(mockAxiosResponse(runRecord));

    const payload = {
      strategy_build_id: "01HZ0000000000000000000002",
      config: { objective: "sharpe" },
      max_trials: 100,
    };

    const result = await runsApi.submitOptimizationRun(payload);

    expect(mockPost).toHaveBeenCalledWith("/runs/optimize", payload);
    expect(result.run_type).toBe("optimization");
  });
});

// ---------------------------------------------------------------------------
// getRunStatus
// ---------------------------------------------------------------------------

describe("runsApi.getRunStatus", () => {
  it("sends GET to /runs/{runId} and returns validated record", async () => {
    const runRecord = { ...makeValidRunRecord(), status: "running" as const };
    mockGet.mockResolvedValue(mockAxiosResponse(runRecord));

    const result = await runsApi.getRunStatus("01HZ0000000000000000000001");

    expect(mockGet).toHaveBeenCalledWith("/runs/01HZ0000000000000000000001");
    expect(result.status).toBe("running");
  });

  it("returns run with live progress fields", async () => {
    const runRecord = {
      ...makeValidRunRecord(),
      status: "running" as const,
      trial_count: 100,
      completed_trials: 42,
      current_trial_params: { lookback: 20, threshold: 0.6 },
    };
    mockGet.mockResolvedValue(mockAxiosResponse(runRecord));

    const result = await runsApi.getRunStatus("01HZ0000000000000000000001");

    expect(result.trial_count).toBe(100);
    expect(result.completed_trials).toBe(42);
    expect(result.current_trial_params).toEqual({
      lookback: 20,
      threshold: 0.6,
    });
  });

  it("validates response and rejects invalid data", async () => {
    mockGet.mockResolvedValue(mockAxiosResponse({ id: "missing-required-fields" }));

    await expect(runsApi.getRunStatus("01HZ0000000000000000000001")).rejects.toThrow();
  });
});

// ---------------------------------------------------------------------------
// getTrials
// ---------------------------------------------------------------------------

describe("runsApi.getTrials", () => {
  it("sends GET to /runs/{runId}/trials with pagination params", async () => {
    const trialList = {
      trials: [makeValidTrialRecord()],
      total: 100,
      offset: 0,
      limit: 50,
    };
    mockGet.mockResolvedValue(mockAxiosResponse(trialList));

    const result = await runsApi.getTrials("01HZ0000000000000000000001", {
      offset: 0,
      limit: 50,
    });

    expect(mockGet).toHaveBeenCalledWith("/runs/01HZ0000000000000000000001/trials", {
      params: { offset: 0, limit: 50 },
    });
    expect(result.trials).toHaveLength(1);
    expect(result.total).toBe(100);
  });

  it("validates response and rejects invalid trial data", async () => {
    mockGet.mockResolvedValue(
      mockAxiosResponse({
        trials: [{ id: "bad-trial", missing: "fields" }],
        total: 1,
        offset: 0,
        limit: 50,
      }),
    );

    await expect(runsApi.getTrials("01HZ001", { offset: 0, limit: 50 })).rejects.toThrow();
  });
});

// ---------------------------------------------------------------------------
// getTrialDetail
// ---------------------------------------------------------------------------

describe("runsApi.getTrialDetail", () => {
  it("sends GET to /runs/{runId}/trials/{trialId}", async () => {
    const trial = makeValidTrialRecord();
    mockGet.mockResolvedValue(mockAxiosResponse(trial));

    const result = await runsApi.getTrialDetail(
      "01HZ0000000000000000000001",
      "01HZ0000000000000000000010",
    );

    expect(mockGet).toHaveBeenCalledWith(
      "/runs/01HZ0000000000000000000001/trials/01HZ0000000000000000000010",
    );
    expect(result.trial_index).toBe(0);
  });
});

// ---------------------------------------------------------------------------
// cancelRun
// ---------------------------------------------------------------------------

describe("runsApi.cancelRun", () => {
  it("sends POST to /runs/{runId}/cancel with reason", async () => {
    const cancelledRun = {
      ...makeValidRunRecord(),
      status: "cancelled" as const,
      cancellation_reason: "User requested cancellation",
    };
    mockPost.mockResolvedValue(mockAxiosResponse(cancelledRun));

    const result = await runsApi.cancelRun(
      "01HZ0000000000000000000001",
      "User requested cancellation",
    );

    expect(mockPost).toHaveBeenCalledWith("/runs/01HZ0000000000000000000001/cancel", {
      reason: "User requested cancellation",
    });
    expect(result.status).toBe("cancelled");
  });

  it("propagates 409 conflict error for already-terminal run", async () => {
    const axiosError = new Error("Request failed with status code 409");
    mockPost.mockRejectedValue(axiosError);

    await expect(runsApi.cancelRun("01HZ0000000000000000000001", "Too late")).rejects.toThrow(
      "Request failed with status code 409",
    );
  });
});
