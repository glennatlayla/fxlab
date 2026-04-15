/**
 * Tests for Results Explorer API service.
 *
 * Covers the retry engine, error classification, backoff computation,
 * cancellable sleep, download lifecycle, and blob validation.
 *
 * Uses vi.useFakeTimers() to test retry delays without real waits.
 */

import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { AxiosError, AxiosHeaders } from "axios";
import { ZodError } from "zod";
import { resultsApi, computeBackoffDelay, cancellableSleep, classifyAxiosError } from "./api";
import {
  ResultsNotFoundError,
  ResultsAuthError,
  ResultsValidationError,
  ResultsNetworkError,
  ResultsDownloadError,
} from "./errors";

// ---------------------------------------------------------------------------
// Mocks
// ---------------------------------------------------------------------------

vi.mock("@/api/client", () => ({
  apiClient: {
    get: vi.fn(),
  },
}));

vi.mock("@/types/results.schemas", () => ({
  RunChartsPayloadSchema: {
    parse: vi.fn(),
  },
}));

vi.mock("./logger", () => ({
  resultsLogger: {
    fetchStart: vi.fn(),
    fetchRetry: vi.fn(),
    fetchSuccess: vi.fn(),
    fetchFailure: vi.fn(),
    validationFailure: vi.fn(),
    downloadStart: vi.fn(),
    downloadSuccess: vi.fn(),
    downloadFailure: vi.fn(),
    downloadAborted: vi.fn(),
  },
}));

vi.mock("@/infrastructure/sentry", () => ({
  Sentry: {
    captureException: vi.fn(),
    addBreadcrumb: vi.fn(),
  },
}));

import { apiClient } from "@/api/client";
import { RunChartsPayloadSchema } from "@/types/results.schemas";
import { resultsLogger } from "./logger";

const mockGet = vi.mocked(apiClient.get);
const mockParse = vi.mocked(RunChartsPayloadSchema.parse);

// ---------------------------------------------------------------------------
// Fixtures
// ---------------------------------------------------------------------------

function makeValidPayload() {
  return {
    run_id: "run-1",
    equity_curve: [{ timestamp: "2026-01-01", equity: 10000, drawdown: 0 }],
    sampling_applied: false,
    raw_equity_point_count: 1,
    fold_boundaries: [],
    regime_segments: [],
    trades: [{ id: "t1" }],
    trades_truncated: false,
    total_trade_count: 1,
    fold_performance: [],
    regime_performance: [],
    trial_summaries: [],
    candidate_metrics: [],
    export_schema_version: "1.0.0",
  };
}

function makeAxiosError(status: number, code?: string): AxiosError {
  const err = new AxiosError("Request failed", code ?? "ERR_BAD_RESPONSE", undefined, undefined, {
    status,
    statusText: "Error",
    headers: {},
    config: { headers: new AxiosHeaders() },
    data: null,
  });
  return err;
}

function makeNetworkError(): AxiosError {
  return new AxiosError("Network Error", "ERR_NETWORK");
}

// ---------------------------------------------------------------------------
// computeBackoffDelay
// ---------------------------------------------------------------------------

describe("computeBackoffDelay", () => {
  it("returns a value in the expected range for attempt 0 (1000-1250ms)", () => {
    const delay = computeBackoffDelay(0);
    expect(delay).toBeGreaterThanOrEqual(1000);
    expect(delay).toBeLessThanOrEqual(1250);
  });

  it("doubles the base for each subsequent attempt", () => {
    // With jitter, attempt 1 should be in [2000, 2500], attempt 2 in [4000, 5000]
    const d1 = computeBackoffDelay(1);
    expect(d1).toBeGreaterThanOrEqual(2000);
    expect(d1).toBeLessThanOrEqual(2500);

    const d2 = computeBackoffDelay(2);
    expect(d2).toBeGreaterThanOrEqual(4000);
    expect(d2).toBeLessThanOrEqual(5000);
  });
});

// ---------------------------------------------------------------------------
// cancellableSleep
// ---------------------------------------------------------------------------

describe("cancellableSleep", () => {
  beforeEach(() => {
    vi.useFakeTimers();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("resolves after the specified delay", async () => {
    const promise = cancellableSleep(1000);
    vi.advanceTimersByTime(1000);
    await expect(promise).resolves.toBeUndefined();
  });

  it("rejects immediately if signal is already aborted", async () => {
    const controller = new AbortController();
    controller.abort();
    await expect(cancellableSleep(1000, controller.signal)).rejects.toThrow("Aborted");
  });

  it("rejects when signal is aborted during sleep", async () => {
    const controller = new AbortController();
    const promise = cancellableSleep(5000, controller.signal);
    controller.abort();
    await expect(promise).rejects.toThrow("Aborted");
  });
});

// ---------------------------------------------------------------------------
// classifyAxiosError
// ---------------------------------------------------------------------------

describe("classifyAxiosError", () => {
  it("classifies 404 as ResultsNotFoundError", () => {
    const err = classifyAxiosError(makeAxiosError(404), "run-1");
    expect(err).toBeInstanceOf(ResultsNotFoundError);
  });

  it("classifies 401 as ResultsAuthError", () => {
    const err = classifyAxiosError(makeAxiosError(401), "run-1");
    expect(err).toBeInstanceOf(ResultsAuthError);
    expect((err as ResultsAuthError).statusCode).toBe(401);
  });

  it("classifies 403 as ResultsAuthError", () => {
    const err = classifyAxiosError(makeAxiosError(403), "run-1");
    expect(err).toBeInstanceOf(ResultsAuthError);
    expect((err as ResultsAuthError).statusCode).toBe(403);
  });

  it("classifies 500 as ResultsNetworkError", () => {
    const err = classifyAxiosError(makeAxiosError(500), "run-1");
    expect(err).toBeInstanceOf(ResultsNetworkError);
    expect((err as ResultsNetworkError).statusCode).toBe(500);
  });

  it("classifies network error (no response) as ResultsNetworkError with undefined status", () => {
    const err = classifyAxiosError(makeNetworkError(), "run-1");
    expect(err).toBeInstanceOf(ResultsNetworkError);
    expect((err as ResultsNetworkError).statusCode).toBeUndefined();
  });
});

// ---------------------------------------------------------------------------
// resultsApi.getRunCharts
// ---------------------------------------------------------------------------

describe("resultsApi.getRunCharts", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.clearAllMocks();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("returns parsed payload on success", async () => {
    const payload = makeValidPayload();
    mockGet.mockResolvedValue({ data: payload });
    mockParse.mockReturnValue(payload as never);

    const result = await resultsApi.getRunCharts("run-1");

    expect(result).toEqual(payload);
    expect(mockGet).toHaveBeenCalledWith("/runs/run-1/charts");
    expect(resultsLogger.fetchStart).toHaveBeenCalledWith("run-1");
    expect(resultsLogger.fetchSuccess).toHaveBeenCalled();
  });

  it("throws ResultsNotFoundError on 404 without retry", async () => {
    mockGet.mockRejectedValue(makeAxiosError(404));

    await expect(resultsApi.getRunCharts("run-1")).rejects.toThrow(ResultsNotFoundError);
    expect(mockGet).toHaveBeenCalledTimes(1); // No retry
  });

  it("throws ResultsAuthError on 401 without retry", async () => {
    mockGet.mockRejectedValue(makeAxiosError(401));

    await expect(resultsApi.getRunCharts("run-1")).rejects.toThrow(ResultsAuthError);
    expect(mockGet).toHaveBeenCalledTimes(1); // No retry
  });

  it("throws ResultsAuthError on 403 without retry", async () => {
    mockGet.mockRejectedValue(makeAxiosError(403));

    await expect(resultsApi.getRunCharts("run-1")).rejects.toThrow(ResultsAuthError);
    expect(mockGet).toHaveBeenCalledTimes(1); // No retry
  });

  it("throws ResultsValidationError on Zod parse failure without retry", async () => {
    mockGet.mockResolvedValue({ data: {} });
    mockParse.mockImplementation(() => {
      throw new ZodError([{ code: "custom", path: ["run_id"], message: "Required" }]);
    });

    await expect(resultsApi.getRunCharts("run-1")).rejects.toThrow(ResultsValidationError);
    expect(mockGet).toHaveBeenCalledTimes(1); // No retry
    expect(resultsLogger.validationFailure).toHaveBeenCalled();
  });

  it("retries transient 500 errors up to API_MAX_RETRIES times", async () => {
    const payload = makeValidPayload();
    // Fail 3 times with 500, succeed on 4th attempt
    mockGet
      .mockRejectedValueOnce(makeAxiosError(500))
      .mockRejectedValueOnce(makeAxiosError(500))
      .mockRejectedValueOnce(makeAxiosError(500))
      .mockResolvedValueOnce({ data: payload });
    mockParse.mockReturnValue(payload as never);

    // Start the call — it will hit the first failure and start the backoff loop
    const promise = resultsApi.getRunCharts("run-1");

    // Advance through all 3 retry delays
    await vi.advanceTimersByTimeAsync(2000); // attempt 0 backoff
    await vi.advanceTimersByTimeAsync(3000); // attempt 1 backoff
    await vi.advanceTimersByTimeAsync(6000); // attempt 2 backoff

    const result = await promise;
    expect(result).toEqual(payload);
    expect(mockGet).toHaveBeenCalledTimes(4); // 1 initial + 3 retries
    expect(resultsLogger.fetchRetry).toHaveBeenCalledTimes(3);
  });

  it("retries 429 rate-limit errors", async () => {
    const payload = makeValidPayload();
    mockGet.mockRejectedValueOnce(makeAxiosError(429)).mockResolvedValueOnce({ data: payload });
    mockParse.mockReturnValue(payload as never);

    const promise = resultsApi.getRunCharts("run-1");
    await vi.advanceTimersByTimeAsync(2000);

    const result = await promise;
    expect(result).toEqual(payload);
    expect(mockGet).toHaveBeenCalledTimes(2);
  });

  it("throws ResultsNetworkError after all retries exhausted", async () => {
    mockGet.mockRejectedValue(makeAxiosError(503));

    // Attach the rejection handler before advancing timers so the
    // rejection is never unhandled between microtask flushes.
    const promise = resultsApi.getRunCharts("run-1").catch((e: unknown) => e);

    // Advance through all retry delays in one large step.
    await vi.advanceTimersByTimeAsync(20_000);

    const error = await promise;
    expect(error).toBeInstanceOf(ResultsNetworkError);
    expect(mockGet).toHaveBeenCalledTimes(4); // 1 initial + 3 retries
    expect(resultsLogger.fetchFailure).toHaveBeenCalled();
  });

  it("fails fast on non-Axios unknown errors without retry", async () => {
    mockGet.mockRejectedValue(new TypeError("Cannot read properties of null"));

    await expect(resultsApi.getRunCharts("run-1")).rejects.toThrow(TypeError);
    expect(mockGet).toHaveBeenCalledTimes(1); // No retry
    expect(resultsLogger.fetchFailure).toHaveBeenCalled();
  });

  it("does not retry 400 bad request", async () => {
    mockGet.mockRejectedValue(makeAxiosError(400));

    await expect(resultsApi.getRunCharts("run-1")).rejects.toThrow(ResultsNetworkError);
    expect(mockGet).toHaveBeenCalledTimes(1); // No retry
  });

  it("logs retry attempt with attempt number and delay", async () => {
    const payload = makeValidPayload();
    mockGet.mockRejectedValueOnce(makeAxiosError(500)).mockResolvedValueOnce({ data: payload });
    mockParse.mockReturnValue(payload as never);

    const promise = resultsApi.getRunCharts("run-1");
    await vi.advanceTimersByTimeAsync(2000);
    await promise;

    expect(resultsLogger.fetchRetry).toHaveBeenCalledWith(
      "run-1",
      1, // attempt number (1-based)
      3, // max retries
      expect.any(Number), // delay ms
    );
  });
});

// ---------------------------------------------------------------------------
// resultsApi.downloadExportBundle
// ---------------------------------------------------------------------------

describe("resultsApi.downloadExportBundle", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("returns blob on successful download", async () => {
    const blob = new Blob(["zip-data"], { type: "application/zip" });
    mockGet.mockResolvedValue({ data: blob });

    const result = await resultsApi.downloadExportBundle("run-1");

    expect(result).toBe(blob);
    expect(resultsLogger.downloadStart).toHaveBeenCalledWith("run-1");
    expect(resultsLogger.downloadSuccess).toHaveBeenCalled();
  });

  it("throws ResultsNotFoundError on 404", async () => {
    mockGet.mockRejectedValue(makeAxiosError(404));

    await expect(resultsApi.downloadExportBundle("run-1")).rejects.toThrow(ResultsNotFoundError);
    expect(resultsLogger.downloadFailure).toHaveBeenCalled();
  });

  it("throws ResultsAuthError on 401", async () => {
    mockGet.mockRejectedValue(makeAxiosError(401));

    await expect(resultsApi.downloadExportBundle("run-1")).rejects.toThrow(ResultsAuthError);
  });

  it("throws ResultsDownloadError with reason 'timeout' on ECONNABORTED", async () => {
    mockGet.mockRejectedValue(makeAxiosError(0, "ECONNABORTED"));

    const err = await resultsApi.downloadExportBundle("run-1").catch((e) => e);
    expect(err).toBeInstanceOf(ResultsDownloadError);
    expect(err.reason).toBe("timeout");
  });

  it("throws ResultsDownloadError with reason 'abort' on AbortError", async () => {
    mockGet.mockRejectedValue(new DOMException("Aborted", "AbortError"));

    const err = await resultsApi.downloadExportBundle("run-1").catch((e) => e);
    expect(err).toBeInstanceOf(ResultsDownloadError);
    expect(err.reason).toBe("abort");
    expect(resultsLogger.downloadAborted).toHaveBeenCalledWith("run-1");
  });

  it("throws ResultsDownloadError with reason 'network' on generic AxiosError", async () => {
    mockGet.mockRejectedValue(makeAxiosError(502));

    const err = await resultsApi.downloadExportBundle("run-1").catch((e) => e);
    expect(err).toBeInstanceOf(ResultsDownloadError);
    expect(err.reason).toBe("network");
  });

  it("throws ResultsDownloadError with reason 'unknown' on non-Axios error", async () => {
    mockGet.mockRejectedValue(new Error("Unexpected"));

    const err = await resultsApi.downloadExportBundle("run-1").catch((e) => e);
    expect(err).toBeInstanceOf(ResultsDownloadError);
    expect(err.reason).toBe("unknown");
  });

  it("rejects blob with non-application MIME type (e.g., text/html error page)", async () => {
    const htmlBlob = new Blob(["<html>error</html>"], { type: "text/html" });
    mockGet.mockResolvedValue({ data: htmlBlob });

    const err = await resultsApi.downloadExportBundle("run-1").catch((e) => e);
    expect(err).toBeInstanceOf(ResultsDownloadError);
    expect(err.reason).toBe("unknown");
  });

  it("accepts blob with generic application/* MIME type", async () => {
    const blob = new Blob(["data"], { type: "application/octet-stream" });
    mockGet.mockResolvedValue({ data: blob });

    const result = await resultsApi.downloadExportBundle("run-1");
    expect(result).toBe(blob);
  });
});
