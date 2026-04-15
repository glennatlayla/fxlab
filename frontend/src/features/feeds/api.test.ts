/**
 * Tests for feeds API client.
 *
 * Covers:
 *   - Happy-path list / detail / health calls with Zod validation.
 *   - classifyAxiosError: 404→NotFound, 401/403→Auth, else→Network.
 *   - Zod validation failure throws FeedsValidationError and does not retry.
 *   - Retry behavior on transient errors (5xx, 429) for idempotent reads.
 *   - X-Correlation-Id header propagation per CLAUDE.md §8.
 *   - AbortSignal cancellation is honored (DOMException AbortError passes through).
 *   - Non-Error throwables wrapped into FeedsNetworkError.
 *   - Logger lifecycle hooks fire on start / success / failure.
 *   - Pagination params (limit/offset) propagate to apiClient.
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { AxiosError } from "axios";

// ---------------------------------------------------------------------------
// Mocks (hoisted)
// ---------------------------------------------------------------------------

const { mockGet, mockLogger } = vi.hoisted(() => {
  const mockGet = vi.fn();
  const mockLogger = {
    listFeedsStart: vi.fn(),
    listFeedsSuccess: vi.fn(),
    listFeedsFailure: vi.fn(),
    getFeedStart: vi.fn(),
    getFeedSuccess: vi.fn(),
    getFeedFailure: vi.fn(),
    listFeedHealthStart: vi.fn(),
    listFeedHealthSuccess: vi.fn(),
    listFeedHealthFailure: vi.fn(),
    validationFailure: vi.fn(),
    retryAttempt: vi.fn(),
  };
  return { mockGet, mockLogger };
});

vi.mock("@/api/client", () => ({
  apiClient: {
    get: (...args: unknown[]) => mockGet(...args),
  },
}));

vi.mock("./logger", () => ({
  feedsLogger: mockLogger,
}));

// Instant retry: keep real classification, zero out sleep + base delay.
vi.mock("./retry", async () => {
  const actual = await vi.importActual<typeof import("./retry")>("./retry");
  return {
    ...actual,
    retryWithBackoff: <T>(
      op: (attempt: number) => Promise<T>,
      opts: import("./retry").RetryOptions = {},
    ) =>
      actual.retryWithBackoff(op, {
        ...opts,
        baseDelayMs: 0,
        jitterFactor: 0,
        sleep: () => Promise.resolve(),
      }),
  };
});

import { feedsApi } from "./api";
import {
  FeedsAuthError,
  FeedsNotFoundError,
  FeedsNetworkError,
  FeedsValidationError,
} from "./errors";

// ---------------------------------------------------------------------------
// Fixtures
// ---------------------------------------------------------------------------

function makeAxiosError(status: number, data: unknown = {}): AxiosError {
  const err = new AxiosError("http error");
  err.response = {
    status,
    statusText: "ERR",
    headers: {},
    config: {} as never,
    data,
  };
  return err;
}

const ISO = "2026-04-06T12:00:00.000Z";

function makeFeed(overrides: Partial<Record<string, unknown>> = {}) {
  return {
    id: "01HFEEDAAAAAAAAAAAAAAAAAAA",
    name: "binance-btcusd",
    provider: "Binance",
    config: { symbol: "BTC/USD", interval: "1m" },
    is_active: true,
    is_quarantined: false,
    created_at: ISO,
    updated_at: ISO,
    ...overrides,
  };
}

function makeFeedListResponse() {
  return {
    feeds: [makeFeed()],
    total_count: 1,
    limit: 25,
    offset: 0,
  };
}

function makeFeedDetailResponse() {
  return {
    feed: makeFeed(),
    version_history: [
      {
        version: 1,
        config: { symbol: "BTC/USD" },
        created_at: ISO,
        created_by: "01HUSER0000000000000000000",
        change_summary: "initial",
      },
    ],
    connectivity_tests: [
      {
        id: "01HCONN0000000000000000000",
        feed_id: "01HFEEDAAAAAAAAAAAAAAAAAAA",
        tested_at: ISO,
        status: "ok",
        latency_ms: 42,
        error_message: null,
      },
    ],
  };
}

function makeFeedHealthResponse() {
  return {
    feeds: [
      {
        feed_id: "01HFEEDAAAAAAAAAAAAAAAAAAA",
        status: "degraded",
        last_update: ISO,
        recent_anomalies: [
          {
            id: "01HANOM0000000000000000000",
            feed_id: "01HFEEDAAAAAAAAAAAAAAAAAAA",
            anomaly_type: "gap",
            detected_at: ISO,
            start_time: ISO,
            end_time: null,
            severity: "high",
            message: "Detected 5-minute gap in tick stream",
            metadata: { source: "ingest" },
          },
        ],
        quarantine_reason: null,
      },
    ],
    generated_at: ISO,
  };
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("feedsApi.listFeeds", () => {
  beforeEach(() => {
    vi.resetAllMocks();
  });

  it("returns parsed feed list and propagates correlation header + pagination params", async () => {
    mockGet.mockResolvedValueOnce({ data: makeFeedListResponse() });

    const result = await feedsApi.listFeeds({ limit: 25, offset: 0 }, "corr-1");

    expect(result.feeds).toHaveLength(1);
    expect(result.total_count).toBe(1);
    expect(mockGet).toHaveBeenCalledWith(
      "/feeds",
      expect.objectContaining({
        headers: { "X-Correlation-Id": "corr-1" },
        params: { limit: 25, offset: 0 },
      }),
    );
    expect(mockLogger.listFeedsStart).toHaveBeenCalledWith(25, 0, "corr-1");
    expect(mockLogger.listFeedsSuccess).toHaveBeenCalled();
  });

  it("forwards AbortSignal in axios config", async () => {
    mockGet.mockResolvedValueOnce({ data: makeFeedListResponse() });
    const ctrl = new AbortController();

    await feedsApi.listFeeds({ limit: 10, offset: 0 }, "corr-2", ctrl.signal);

    expect(mockGet).toHaveBeenCalledWith(
      "/feeds",
      expect.objectContaining({ signal: ctrl.signal }),
    );
  });

  it("throws FeedsValidationError on Zod failure and does not retry", async () => {
    mockGet.mockResolvedValueOnce({ data: { feeds: "not-an-array" } });

    await expect(feedsApi.listFeeds({ limit: 25, offset: 0 })).rejects.toBeInstanceOf(
      FeedsValidationError,
    );
    expect(mockGet).toHaveBeenCalledTimes(1);
    expect(mockLogger.validationFailure).toHaveBeenCalled();
  });

  it("classifies 401 as FeedsAuthError(401)", async () => {
    mockGet.mockRejectedValueOnce(makeAxiosError(401));

    await expect(feedsApi.listFeeds({ limit: 25, offset: 0 })).rejects.toMatchObject({
      name: "FeedsAuthError",
      statusCode: 401,
    });
    expect(mockGet).toHaveBeenCalledTimes(1);
  });

  it("classifies 403 as FeedsAuthError(403)", async () => {
    mockGet.mockRejectedValueOnce(makeAxiosError(403));

    await expect(feedsApi.listFeeds({ limit: 25, offset: 0 })).rejects.toMatchObject({
      name: "FeedsAuthError",
      statusCode: 403,
    });
  });

  it("classifies 500 as FeedsNetworkError and retries before giving up", async () => {
    mockGet
      .mockRejectedValueOnce(makeAxiosError(500))
      .mockRejectedValueOnce(makeAxiosError(500))
      .mockRejectedValueOnce(makeAxiosError(500))
      .mockRejectedValueOnce(makeAxiosError(500));

    await expect(feedsApi.listFeeds({ limit: 25, offset: 0 })).rejects.toBeInstanceOf(
      FeedsNetworkError,
    );
    // 1 initial + 3 retries = 4 calls
    expect(mockGet).toHaveBeenCalledTimes(4);
    expect(mockLogger.retryAttempt).toHaveBeenCalled();
  });

  it("retries on 503 then succeeds", async () => {
    mockGet
      .mockRejectedValueOnce(makeAxiosError(503))
      .mockResolvedValueOnce({ data: makeFeedListResponse() });

    const result = await feedsApi.listFeeds({ limit: 25, offset: 0 });
    expect(result.feeds).toHaveLength(1);
    expect(mockGet).toHaveBeenCalledTimes(2);
    expect(mockLogger.retryAttempt).toHaveBeenCalledTimes(1);
  });

  it("retries on 429 then succeeds", async () => {
    mockGet
      .mockRejectedValueOnce(makeAxiosError(429))
      .mockResolvedValueOnce({ data: makeFeedListResponse() });

    await expect(feedsApi.listFeeds({ limit: 25, offset: 0 })).resolves.toBeDefined();
    expect(mockGet).toHaveBeenCalledTimes(2);
  });

  it("does not retry on 400", async () => {
    mockGet.mockRejectedValueOnce(makeAxiosError(400));

    await expect(feedsApi.listFeeds({ limit: 25, offset: 0 })).rejects.toBeInstanceOf(
      FeedsNetworkError,
    );
    expect(mockGet).toHaveBeenCalledTimes(1);
  });

  it("rethrows DOMException AbortError without wrapping", async () => {
    const abortErr = new DOMException("Aborted", "AbortError");
    mockGet.mockRejectedValueOnce(abortErr);

    await expect(feedsApi.listFeeds({ limit: 25, offset: 0 })).rejects.toBe(abortErr);
    expect(mockGet).toHaveBeenCalledTimes(1);
  });

  it("wraps non-Error throwables into FeedsNetworkError", async () => {
    mockGet.mockRejectedValueOnce("something exploded");

    await expect(feedsApi.listFeeds({ limit: 25, offset: 0 })).rejects.toBeInstanceOf(
      FeedsNetworkError,
    );
  });
});

describe("feedsApi.getFeed", () => {
  beforeEach(() => {
    vi.resetAllMocks();
  });

  it("returns parsed feed detail", async () => {
    mockGet.mockResolvedValueOnce({ data: makeFeedDetailResponse() });

    const result = await feedsApi.getFeed("01HFEEDAAAAAAAAAAAAAAAAAAA", "corr-3");

    expect(result.feed.id).toBe("01HFEEDAAAAAAAAAAAAAAAAAAA");
    expect(result.version_history).toHaveLength(1);
    expect(result.connectivity_tests).toHaveLength(1);
    expect(mockGet).toHaveBeenCalledWith(
      "/feeds/01HFEEDAAAAAAAAAAAAAAAAAAA",
      expect.objectContaining({ headers: { "X-Correlation-Id": "corr-3" } }),
    );
    expect(mockLogger.getFeedSuccess).toHaveBeenCalled();
  });

  it("classifies 404 as FeedsNotFoundError", async () => {
    mockGet.mockRejectedValueOnce(makeAxiosError(404));

    await expect(feedsApi.getFeed("missing")).rejects.toBeInstanceOf(FeedsNotFoundError);
    expect(mockGet).toHaveBeenCalledTimes(1);
  });

  it("retries on 502 then succeeds", async () => {
    mockGet
      .mockRejectedValueOnce(makeAxiosError(502))
      .mockResolvedValueOnce({ data: makeFeedDetailResponse() });

    await expect(feedsApi.getFeed("01HFEEDAAAAAAAAAAAAAAAAAAA")).resolves.toBeDefined();
    expect(mockGet).toHaveBeenCalledTimes(2);
  });

  it("throws FeedsValidationError when detail payload fails Zod", async () => {
    mockGet.mockResolvedValueOnce({ data: { feed: { id: "" } } });

    await expect(feedsApi.getFeed("01HFEEDAAAAAAAAAAAAAAAAAAA")).rejects.toBeInstanceOf(
      FeedsValidationError,
    );
  });
});

describe("feedsApi.listFeedHealth", () => {
  beforeEach(() => {
    vi.resetAllMocks();
  });

  it("returns parsed feed health report and forwards signal", async () => {
    mockGet.mockResolvedValueOnce({ data: makeFeedHealthResponse() });
    const ctrl = new AbortController();

    const result = await feedsApi.listFeedHealth("corr-4", ctrl.signal);

    expect(result.feeds).toHaveLength(1);
    expect(result.feeds[0]?.status).toBe("degraded");
    expect(result.feeds[0]?.recent_anomalies).toHaveLength(1);
    expect(mockGet).toHaveBeenCalledWith(
      "/feed-health",
      expect.objectContaining({
        headers: { "X-Correlation-Id": "corr-4" },
        signal: ctrl.signal,
      }),
    );
    expect(mockLogger.listFeedHealthSuccess).toHaveBeenCalled();
  });

  it("retries on transient 504 then succeeds", async () => {
    mockGet
      .mockRejectedValueOnce(makeAxiosError(504))
      .mockResolvedValueOnce({ data: makeFeedHealthResponse() });

    await expect(feedsApi.listFeedHealth()).resolves.toBeDefined();
    expect(mockGet).toHaveBeenCalledTimes(2);
  });

  it("does not retry on 401", async () => {
    mockGet.mockRejectedValueOnce(makeAxiosError(401));

    await expect(feedsApi.listFeedHealth()).rejects.toBeInstanceOf(FeedsAuthError);
    expect(mockGet).toHaveBeenCalledTimes(1);
  });
});
