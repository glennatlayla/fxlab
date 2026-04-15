/**
 * Tests for Readiness API service.
 *
 * Covers the retry engine, error classification, backoff computation,
 * cancellable sleep, getReadinessReport, generateReadinessReport, and
 * submitForPromotion — including transient vs permanent error handling,
 * Zod schema validation, abort signals, and structured logging calls.
 *
 * Uses vi.useFakeTimers() to test retry delays without real waits.
 */

import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { readinessApi, computeBackoffDelay, cancellableSleep, classifyAxiosError } from "./api";
import {
  ReadinessNotFoundError,
  ReadinessAuthError,
  ReadinessValidationError,
  ReadinessNetworkError,
  ReadinessGenerationError,
} from "./errors";

// ---------------------------------------------------------------------------
// Mocks — vi.mock factories are hoisted, so use dynamic imports inside them
// ---------------------------------------------------------------------------

vi.mock("axios", async (importOriginal) => {
  const mod = await importOriginal<typeof import("axios")>();
  return {
    ...mod,
    default: {
      get: vi.fn(),
      post: vi.fn(),
    },
  };
});

vi.mock("@/types/readiness", () => ({
  ReadinessReportPayloadSchema: {
    safeParse: vi.fn(),
  },
  PromotionResponseSchema: {
    safeParse: vi.fn(),
  },
}));

vi.mock("./logger", () => ({
  readinessLogger: {
    fetchStart: vi.fn(),
    fetchSuccess: vi.fn(),
    fetchFailure: vi.fn(),
    fetchRetry: vi.fn(),
    generateStart: vi.fn(),
    generateSuccess: vi.fn(),
    generateFailure: vi.fn(),
    promotionStart: vi.fn(),
    promotionSuccess: vi.fn(),
    promotionFailure: vi.fn(),
    validationFailure: vi.fn(),
  },
}));

vi.mock("@/infrastructure/sentry", () => ({
  Sentry: {
    captureException: vi.fn(),
    addBreadcrumb: vi.fn(),
  },
}));

import axios, { AxiosError, AxiosHeaders } from "axios";
import { ReadinessReportPayloadSchema, PromotionResponseSchema } from "@/types/readiness";
import { readinessLogger } from "./logger";

const mockGet = vi.mocked(axios.get);
const mockPost = vi.mocked(axios.post);
const mockSafeParse = vi.mocked(ReadinessReportPayloadSchema.safeParse);
const mockPromotionSafeParse = vi.mocked(PromotionResponseSchema.safeParse);

// ---------------------------------------------------------------------------
// Fixtures
// ---------------------------------------------------------------------------

function makeValidPayload() {
  return {
    run_id: "run-1",
    grade: "B",
    score: 72,
    policy_version: "1",
    assessed_at: "2026-04-06T12:00:00Z",
    assessor: "readiness-engine",
    dimensions: [
      {
        dimension: "oos_stability",
        label: "OOS Stability",
        score: 85,
        weight: 0.25,
        threshold: 50,
        passed: true,
        details: "OOS/IS ratio: 0.78",
      },
    ],
    holdout: {
      passed: true,
      holdout_start: "2026-01-01",
      holdout_end: "2026-03-01",
      contamination_detected: false,
      sharpe_ratio: 1.2,
    },
    regime_consistency: [
      {
        regime: "bull",
        sharpe_ratio: 0.9,
        passed: true,
        trade_count: 42,
      },
    ],
    blockers: [],
    override_watermark: null,
    history: [],
    has_pending_promotion: false,
  };
}

function makeAxiosError(status: number, code?: string): AxiosError {
  return new AxiosError("Request failed", code ?? "ERR_BAD_RESPONSE", undefined, undefined, {
    status,
    statusText: "Error",
    headers: {},
    config: { headers: new AxiosHeaders() },
    data: null,
  });
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
    // With jitter factor 0.25: attempt 1 → [2000, 2500], attempt 2 → [4000, 5000]
    const d1 = computeBackoffDelay(1);
    expect(d1).toBeGreaterThanOrEqual(2000);
    expect(d1).toBeLessThanOrEqual(2500);

    const d2 = computeBackoffDelay(2);
    expect(d2).toBeGreaterThanOrEqual(4000);
    expect(d2).toBeLessThanOrEqual(5000);
  });

  it("returns at least the base delay (no zero-delay retries)", () => {
    for (let i = 0; i < 10; i++) {
      expect(computeBackoffDelay(0)).toBeGreaterThanOrEqual(1000);
    }
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

  it("throws a DOMException with name AbortError", async () => {
    const controller = new AbortController();
    controller.abort();
    const err = await cancellableSleep(100, controller.signal).catch((e: unknown) => e);
    expect(err).toBeInstanceOf(DOMException);
    expect((err as DOMException).name).toBe("AbortError");
  });
});

// ---------------------------------------------------------------------------
// classifyAxiosError
// ---------------------------------------------------------------------------

describe("classifyAxiosError", () => {
  it("classifies 404 as ReadinessNotFoundError", () => {
    const err = classifyAxiosError(makeAxiosError(404), "run-1");
    expect(err).toBeInstanceOf(ReadinessNotFoundError);
  });

  it("classifies 401 as ReadinessAuthError with statusCode 401", () => {
    const err = classifyAxiosError(makeAxiosError(401), "run-1");
    expect(err).toBeInstanceOf(ReadinessAuthError);
    expect((err as ReadinessAuthError).statusCode).toBe(401);
  });

  it("classifies 403 as ReadinessAuthError with statusCode 403", () => {
    const err = classifyAxiosError(makeAxiosError(403), "run-1");
    expect(err).toBeInstanceOf(ReadinessAuthError);
    expect((err as ReadinessAuthError).statusCode).toBe(403);
  });

  it("classifies 500 as ReadinessNetworkError", () => {
    const err = classifyAxiosError(makeAxiosError(500), "run-1");
    expect(err).toBeInstanceOf(ReadinessNetworkError);
    expect((err as ReadinessNetworkError).statusCode).toBe(500);
  });

  it("classifies 429 as ReadinessNetworkError (transient)", () => {
    const err = classifyAxiosError(makeAxiosError(429), "run-1");
    expect(err).toBeInstanceOf(ReadinessNetworkError);
    expect((err as ReadinessNetworkError).statusCode).toBe(429);
  });

  it("classifies 502 as ReadinessNetworkError (transient)", () => {
    const err = classifyAxiosError(makeAxiosError(502), "run-1");
    expect(err).toBeInstanceOf(ReadinessNetworkError);
    expect((err as ReadinessNetworkError).statusCode).toBe(502);
  });

  it("classifies network error (no response) with undefined status", () => {
    const err = classifyAxiosError(makeNetworkError(), "run-1");
    expect(err).toBeInstanceOf(ReadinessNetworkError);
    expect((err as ReadinessNetworkError).statusCode).toBeUndefined();
  });

  it("preserves the original AxiosError as cause", () => {
    const axErr = makeAxiosError(500);
    const err = classifyAxiosError(axErr, "run-1");
    expect(err.cause).toBe(axErr);
  });
});

// ---------------------------------------------------------------------------
// readinessApi.getReadinessReport
// ---------------------------------------------------------------------------

describe("readinessApi.getReadinessReport", () => {
  beforeEach(() => {
    vi.useFakeTimers();
    vi.clearAllMocks();
  });

  afterEach(() => {
    vi.useRealTimers();
  });

  it("returns validated payload on success", async () => {
    const payload = makeValidPayload();
    mockGet.mockResolvedValue({ data: payload });
    mockSafeParse.mockReturnValue({ success: true, data: payload } as never);

    const result = await readinessApi.getReadinessReport("run-1");

    expect(result).toEqual(payload);
    expect(mockGet).toHaveBeenCalledWith("/api/runs/run-1/readiness");
    expect(readinessLogger.fetchStart).toHaveBeenCalledWith("run-1", undefined);
    expect(readinessLogger.fetchSuccess).toHaveBeenCalled();
  });

  it("throws ReadinessNotFoundError on 404 without retry", async () => {
    mockGet.mockRejectedValue(makeAxiosError(404));

    await expect(readinessApi.getReadinessReport("run-1")).rejects.toThrow(ReadinessNotFoundError);
    expect(mockGet).toHaveBeenCalledTimes(1);
  });

  it("throws ReadinessAuthError on 401 without retry", async () => {
    mockGet.mockRejectedValue(makeAxiosError(401));

    await expect(readinessApi.getReadinessReport("run-1")).rejects.toThrow(ReadinessAuthError);
    expect(mockGet).toHaveBeenCalledTimes(1);
  });

  it("throws ReadinessAuthError on 403 without retry", async () => {
    mockGet.mockRejectedValue(makeAxiosError(403));

    await expect(readinessApi.getReadinessReport("run-1")).rejects.toThrow(ReadinessAuthError);
    expect(mockGet).toHaveBeenCalledTimes(1);
  });

  it("throws ReadinessValidationError on Zod parse failure without retry", async () => {
    mockGet.mockResolvedValue({ data: {} });
    mockSafeParse.mockReturnValue({
      success: false,
      error: {
        issues: [{ code: "custom", path: ["run_id"], message: "Required" }],
      },
    } as never);

    await expect(readinessApi.getReadinessReport("run-1")).rejects.toThrow(
      ReadinessValidationError,
    );
    expect(mockGet).toHaveBeenCalledTimes(1);
    expect(readinessLogger.validationFailure).toHaveBeenCalled();
  });

  it("does not retry 400 bad request (non-transient)", async () => {
    mockGet.mockRejectedValue(makeAxiosError(400));

    await expect(readinessApi.getReadinessReport("run-1")).rejects.toThrow(ReadinessNetworkError);
    expect(mockGet).toHaveBeenCalledTimes(1);
    expect(readinessLogger.fetchFailure).toHaveBeenCalled();
  });

  it("retries transient 500 errors up to max retries then succeeds", async () => {
    const payload = makeValidPayload();
    mockGet
      .mockRejectedValueOnce(makeAxiosError(500))
      .mockRejectedValueOnce(makeAxiosError(500))
      .mockRejectedValueOnce(makeAxiosError(500))
      .mockResolvedValueOnce({ data: payload });
    mockSafeParse.mockReturnValue({ success: true, data: payload } as never);

    const promise = readinessApi.getReadinessReport("run-1");

    await vi.advanceTimersByTimeAsync(2000);
    await vi.advanceTimersByTimeAsync(3000);
    await vi.advanceTimersByTimeAsync(6000);

    const result = await promise;
    expect(result).toEqual(payload);
    expect(mockGet).toHaveBeenCalledTimes(4);
    expect(readinessLogger.fetchRetry).toHaveBeenCalledTimes(3);
  });

  it("retries 429 rate-limit errors", async () => {
    const payload = makeValidPayload();
    mockGet.mockRejectedValueOnce(makeAxiosError(429)).mockResolvedValueOnce({ data: payload });
    mockSafeParse.mockReturnValue({ success: true, data: payload } as never);

    const promise = readinessApi.getReadinessReport("run-1");
    await vi.advanceTimersByTimeAsync(2000);

    const result = await promise;
    expect(result).toEqual(payload);
    expect(mockGet).toHaveBeenCalledTimes(2);
  });

  it("retries 503 service unavailable errors", async () => {
    const payload = makeValidPayload();
    mockGet.mockRejectedValueOnce(makeAxiosError(503)).mockResolvedValueOnce({ data: payload });
    mockSafeParse.mockReturnValue({ success: true, data: payload } as never);

    const promise = readinessApi.getReadinessReport("run-1");
    await vi.advanceTimersByTimeAsync(2000);

    const result = await promise;
    expect(result).toEqual(payload);
    expect(mockGet).toHaveBeenCalledTimes(2);
  });

  it("retries network errors (no response, status undefined)", async () => {
    const payload = makeValidPayload();
    mockGet.mockRejectedValueOnce(makeNetworkError()).mockResolvedValueOnce({ data: payload });
    mockSafeParse.mockReturnValue({ success: true, data: payload } as never);

    const promise = readinessApi.getReadinessReport("run-1");
    await vi.advanceTimersByTimeAsync(2000);

    const result = await promise;
    expect(result).toEqual(payload);
    expect(mockGet).toHaveBeenCalledTimes(2);
  });

  it("throws ReadinessNetworkError after all retries exhausted", async () => {
    mockGet.mockRejectedValue(makeAxiosError(503));

    const promise = readinessApi.getReadinessReport("run-1").catch((e: unknown) => e);
    await vi.advanceTimersByTimeAsync(20_000);

    const error = await promise;
    expect(error).toBeInstanceOf(ReadinessNetworkError);
    // 1 initial + 3 retries = 4 total calls
    expect(mockGet).toHaveBeenCalledTimes(4);
    expect(readinessLogger.fetchFailure).toHaveBeenCalled();
  });

  it("fails fast on non-Axios unknown errors without retry", async () => {
    mockGet.mockRejectedValue(new TypeError("Cannot read properties of null"));

    await expect(readinessApi.getReadinessReport("run-1")).rejects.toThrow(TypeError);
    expect(mockGet).toHaveBeenCalledTimes(1);
    expect(readinessLogger.fetchFailure).toHaveBeenCalled();
  });

  it("logs retry attempt with attempt number and delay", async () => {
    const payload = makeValidPayload();
    mockGet.mockRejectedValueOnce(makeAxiosError(500)).mockResolvedValueOnce({ data: payload });
    mockSafeParse.mockReturnValue({ success: true, data: payload } as never);

    const promise = readinessApi.getReadinessReport("run-1");
    await vi.advanceTimersByTimeAsync(2000);
    await promise;

    expect(readinessLogger.fetchRetry).toHaveBeenCalledWith(
      "run-1",
      1, // attempt 1 (1-based)
      3, // max retries
      expect.any(Number), // delay ms
      undefined, // correlationId
    );
  });

  it("logs fetchStart at the beginning", async () => {
    const payload = makeValidPayload();
    mockGet.mockResolvedValue({ data: payload });
    mockSafeParse.mockReturnValue({ success: true, data: payload } as never);

    await readinessApi.getReadinessReport("run-1");
    expect(readinessLogger.fetchStart).toHaveBeenCalledWith("run-1", undefined);
  });

  it("logs fetchSuccess with grade and score metadata on success", async () => {
    const payload = makeValidPayload();
    mockGet.mockResolvedValue({ data: payload });
    mockSafeParse.mockReturnValue({ success: true, data: payload } as never);

    await readinessApi.getReadinessReport("run-1");

    expect(readinessLogger.fetchSuccess).toHaveBeenCalledWith(
      "run-1",
      expect.any(Number),
      expect.objectContaining({
        grade: "B",
        score: 72,
        dimensionCount: 1,
      }),
      undefined, // correlationId
    );
  });
});

// ---------------------------------------------------------------------------
// readinessApi.generateReadinessReport
// ---------------------------------------------------------------------------

describe("readinessApi.generateReadinessReport", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("returns validated payload on success", async () => {
    const payload = makeValidPayload();
    mockPost.mockResolvedValue({ data: payload });
    mockSafeParse.mockReturnValue({ success: true, data: payload } as never);

    const result = await readinessApi.generateReadinessReport("run-1");

    expect(result).toEqual(payload);
    expect(mockPost).toHaveBeenCalledWith("/api/runs/run-1/readiness");
    expect(readinessLogger.generateStart).toHaveBeenCalledWith("run-1", undefined);
    expect(readinessLogger.generateSuccess).toHaveBeenCalledWith(
      "run-1",
      expect.any(Number),
      "B",
      undefined,
    );
  });

  it("throws ReadinessNotFoundError on 404", async () => {
    mockPost.mockRejectedValue(makeAxiosError(404));

    await expect(readinessApi.generateReadinessReport("run-1")).rejects.toThrow(
      ReadinessNotFoundError,
    );
  });

  it("throws ReadinessAuthError on 401", async () => {
    mockPost.mockRejectedValue(makeAxiosError(401));

    await expect(readinessApi.generateReadinessReport("run-1")).rejects.toThrow(ReadinessAuthError);
  });

  it("throws ReadinessAuthError on 403", async () => {
    mockPost.mockRejectedValue(makeAxiosError(403));

    await expect(readinessApi.generateReadinessReport("run-1")).rejects.toThrow(ReadinessAuthError);
  });

  it("throws ReadinessGenerationError on 500", async () => {
    mockPost.mockRejectedValue(makeAxiosError(500));

    await expect(readinessApi.generateReadinessReport("run-1")).rejects.toThrow(
      ReadinessGenerationError,
    );
    expect(readinessLogger.generateFailure).toHaveBeenCalled();
  });

  it("throws ReadinessValidationError on Zod parse failure", async () => {
    mockPost.mockResolvedValue({ data: {} });
    mockSafeParse.mockReturnValue({
      success: false,
      error: {
        issues: [{ code: "custom", path: ["grade"], message: "Required" }],
      },
    } as never);

    await expect(readinessApi.generateReadinessReport("run-1")).rejects.toThrow(
      ReadinessValidationError,
    );
    expect(readinessLogger.validationFailure).toHaveBeenCalled();
  });

  it("does NOT retry (generation is expensive)", async () => {
    mockPost.mockRejectedValue(makeAxiosError(500));

    await expect(readinessApi.generateReadinessReport("run-1")).rejects.toThrow(
      ReadinessGenerationError,
    );
    expect(mockPost).toHaveBeenCalledTimes(1);
  });

  it("fails fast on non-Axios errors", async () => {
    mockPost.mockRejectedValue(new TypeError("Null reference"));

    await expect(readinessApi.generateReadinessReport("run-1")).rejects.toThrow(TypeError);
    expect(readinessLogger.generateFailure).toHaveBeenCalled();
  });
});

// ---------------------------------------------------------------------------
// readinessApi.submitForPromotion
// ---------------------------------------------------------------------------

describe("readinessApi.submitForPromotion", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("returns promotion ID on success", async () => {
    const response = { promotion_id: "promo-123" };
    mockPost.mockResolvedValue({ data: response });
    mockPromotionSafeParse.mockReturnValue({
      success: true,
      data: response,
    } as never);

    const result = await readinessApi.submitForPromotion(
      "run-1",
      "Strong OOS performance",
      "paper",
    );

    expect(result).toEqual(response);
    expect(mockPost).toHaveBeenCalledWith("/api/promotions/request", {
      run_id: "run-1",
      rationale: "Strong OOS performance",
      target_stage: "paper",
    });
    expect(readinessLogger.promotionStart).toHaveBeenCalledWith("run-1", undefined);
    expect(readinessLogger.promotionSuccess).toHaveBeenCalledWith(
      "run-1",
      expect.any(Number),
      undefined,
    );
  });

  it("throws ReadinessAuthError on 401", async () => {
    mockPost.mockRejectedValue(makeAxiosError(401));

    await expect(readinessApi.submitForPromotion("run-1", "rationale", "paper")).rejects.toThrow(
      ReadinessAuthError,
    );
  });

  it("throws ReadinessAuthError on 403", async () => {
    mockPost.mockRejectedValue(makeAxiosError(403));

    await expect(readinessApi.submitForPromotion("run-1", "rationale", "paper")).rejects.toThrow(
      ReadinessAuthError,
    );
  });

  it("throws ReadinessNetworkError on 500", async () => {
    mockPost.mockRejectedValue(makeAxiosError(500));

    await expect(readinessApi.submitForPromotion("run-1", "rationale", "paper")).rejects.toThrow(
      ReadinessNetworkError,
    );
    expect(readinessLogger.promotionFailure).toHaveBeenCalled();
  });

  it("throws ReadinessValidationError when PromotionResponseSchema.safeParse fails", async () => {
    mockPost.mockResolvedValue({ data: { unexpected: "shape" } });
    mockPromotionSafeParse.mockReturnValue({
      success: false,
      error: {
        issues: [{ code: "invalid_type", path: ["promotion_id"], message: "Required" }],
      },
    } as never);

    await expect(readinessApi.submitForPromotion("run-1", "rationale", "paper")).rejects.toThrow(
      ReadinessValidationError,
    );
    expect(readinessLogger.validationFailure).toHaveBeenCalledWith(
      "run-1",
      [{ code: "invalid_type", path: ["promotion_id"], message: "Required" }],
      undefined,
    );
  });

  it("fails fast on non-Axios errors", async () => {
    mockPost.mockRejectedValue(new Error("Unexpected"));

    await expect(readinessApi.submitForPromotion("run-1", "rationale", "paper")).rejects.toThrow(
      Error,
    );
    expect(readinessLogger.promotionFailure).toHaveBeenCalled();
  });
});
