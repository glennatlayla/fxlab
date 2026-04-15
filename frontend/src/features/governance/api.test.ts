/**
 * Tests for governance API client.
 *
 * Covers:
 *   - Happy-path list/mutation calls with Zod validation.
 *   - classifyAxiosError: 404→NotFound, 401/403→Auth, 409→SoD, else→Network.
 *   - Zod validation failure throws GovernanceValidationError and does not retry.
 *   - Retry behavior on transient errors for idempotent reads (list calls).
 *   - Non-retry behavior on mutations (approve/reject/requestOverride).
 *   - X-Correlation-Id header propagation for distributed tracing per §8.
 *   - AbortSignal cancellation is honored.
 *   - Non-Error throwables are caught and wrapped safely.
 *   - Duration tracking and logger hooks fire on success and failure.
 */

import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";
import { AxiosError, type AxiosRequestConfig } from "axios";

// ---------------------------------------------------------------------------
// Mocks — must be hoisted above the api.ts import so it picks up the mocked
// apiClient instance.
// ---------------------------------------------------------------------------

const { mockGet, mockPost, mockLogger } = vi.hoisted(() => {
  const mockGet = vi.fn();
  const mockPost = vi.fn();
  const mockLogger = {
    listApprovalsStart: vi.fn(),
    listApprovalsSuccess: vi.fn(),
    listApprovalsFailure: vi.fn(),
    approveStart: vi.fn(),
    approveSuccess: vi.fn(),
    approveFailure: vi.fn(),
    rejectStart: vi.fn(),
    rejectSuccess: vi.fn(),
    rejectFailure: vi.fn(),
    listOverridesStart: vi.fn(),
    listOverridesSuccess: vi.fn(),
    listOverridesFailure: vi.fn(),
    getOverrideStart: vi.fn(),
    getOverrideSuccess: vi.fn(),
    getOverrideFailure: vi.fn(),
    requestOverrideStart: vi.fn(),
    requestOverrideSuccess: vi.fn(),
    requestOverrideFailure: vi.fn(),
    listPromotionsStart: vi.fn(),
    listPromotionsSuccess: vi.fn(),
    listPromotionsFailure: vi.fn(),
    validationFailure: vi.fn(),
    retryAttempt: vi.fn(),
  };
  return { mockGet, mockPost, mockLogger };
});

vi.mock("@/api/client", () => ({
  apiClient: {
    get: (...args: unknown[]) => mockGet(...args),
    post: (...args: unknown[]) => mockPost(...args),
  },
}));

vi.mock("./logger", () => ({
  governanceLogger: mockLogger,
}));

// Make retry instant: keep real retry logic but stub sleep + zero base delay so
// transient-error tests do not wait for real exponential backoff timers.
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

import { governanceApi } from "./api";
import {
  GovernanceAuthError,
  GovernanceNotFoundError,
  GovernanceSoDError,
  GovernanceNetworkError,
  GovernanceValidationError,
} from "./errors";

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function makeAxiosError(status: number, data: unknown = {}): AxiosError {
  const err = new AxiosError("http error");
  err.response = {
    status,
    data,
    statusText: "Error",
    headers: {},
    config: {} as never,
  };
  return err;
}

function makeApprovalDetail() {
  return {
    id: "01HAPPROVAL0000000001",
    requested_by: "01HUSER0000000000001",
    reviewer_id: null,
    status: "pending",
    decision_reason: null,
    decided_at: null,
    created_at: "2026-04-06T12:00:00Z",
    updated_at: "2026-04-06T12:00:00Z",
  };
}

function makeOverrideDetail() {
  return {
    id: "01HOVERRIDE000000001",
    override_type: "blocker_waiver",
    status: "pending",
    object_id: "01HOBJ0000000000001",
    object_type: "candidate",
    submitter_id: "01HUSER0000000000001",
    reviewed_by: null,
    reviewed_at: null,
    rationale: "waiver rationale provided",
    evidence_link: "https://jira.example.com/FX-1",
    original_state: { flag: "off" },
    new_state: { flag: "on" },
    override_watermark: null,
    created_at: "2026-04-06T12:00:00Z",
    updated_at: "2026-04-06T12:00:00Z",
  };
}

function makePromotionEntry() {
  return {
    id: "01HPROMO00000000001",
    candidate_id: "01HCANDIDATE00000001",
    target_environment: "paper" as const,
    submitted_by: "01HUSER0000000000001",
    status: "pending" as const,
    reviewed_by: null,
    reviewed_at: null,
    decision_rationale: null,
    evidence_link: null,
    created_at: "2026-04-06T12:00:00Z",
    updated_at: "2026-04-06T12:00:00Z",
    override_watermark: null,
  };
}

function makeApprovalDecisionResponse(status: "approved" | "rejected") {
  return {
    approval_id: "01HAPPROVAL0000000001",
    status,
    rationale: status === "rejected" ? "insufficient evidence" : undefined,
  };
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("governanceApi.listApprovals", () => {
  beforeEach(() => {
    vi.resetAllMocks();
  });

  it("returns parsed approvals on happy path", async () => {
    mockGet.mockResolvedValue({ data: [makeApprovalDetail()] });
    const result = await governanceApi.listApprovals("corr-1");
    expect(result).toHaveLength(1);
    expect(result[0].id).toBe("01HAPPROVAL0000000001");
    expect(mockLogger.listApprovalsStart).toHaveBeenCalledWith("corr-1");
    expect(mockLogger.listApprovalsSuccess).toHaveBeenCalledWith(1, expect.any(Number), "corr-1");
  });

  it("sends X-Correlation-Id header for distributed tracing", async () => {
    mockGet.mockResolvedValue({ data: [] });
    await governanceApi.listApprovals("trace-abc");
    const config = mockGet.mock.calls[0][1] as AxiosRequestConfig;
    expect(config?.headers?.["X-Correlation-Id"]).toBe("trace-abc");
  });

  it("forwards AbortSignal to axios", async () => {
    mockGet.mockResolvedValue({ data: [] });
    const controller = new AbortController();
    await governanceApi.listApprovals("corr-1", controller.signal);
    const config = mockGet.mock.calls[0][1] as AxiosRequestConfig;
    expect(config?.signal).toBe(controller.signal);
  });

  it("throws GovernanceValidationError when Zod parsing fails and does not retry", async () => {
    mockGet.mockResolvedValue({ data: [{ garbage: true }] });
    await expect(governanceApi.listApprovals("corr-1")).rejects.toBeInstanceOf(
      GovernanceValidationError,
    );
    expect(mockGet).toHaveBeenCalledTimes(1); // no retry on validation error
    expect(mockLogger.validationFailure).toHaveBeenCalled();
  });

  it("classifies 401 as GovernanceAuthError", async () => {
    mockGet.mockRejectedValue(makeAxiosError(401));
    await expect(governanceApi.listApprovals("corr-1")).rejects.toBeInstanceOf(GovernanceAuthError);
    expect(mockGet).toHaveBeenCalledTimes(1); // no retry on 401
  });

  it("classifies 403 as GovernanceAuthError", async () => {
    mockGet.mockRejectedValue(makeAxiosError(403));
    await expect(governanceApi.listApprovals("corr-1")).rejects.toBeInstanceOf(GovernanceAuthError);
  });

  it("classifies 404 as GovernanceNotFoundError", async () => {
    mockGet.mockRejectedValue(makeAxiosError(404));
    await expect(governanceApi.listApprovals("corr-1")).rejects.toBeInstanceOf(
      GovernanceNotFoundError,
    );
  });

  it("classifies 409 as GovernanceSoDError", async () => {
    mockGet.mockRejectedValue(makeAxiosError(409));
    await expect(governanceApi.listApprovals("corr-1")).rejects.toBeInstanceOf(GovernanceSoDError);
  });

  it("classifies 500 as GovernanceNetworkError", async () => {
    mockGet.mockRejectedValue(makeAxiosError(500));
    await expect(governanceApi.listApprovals("corr-1")).rejects.toBeInstanceOf(
      GovernanceNetworkError,
    );
  });

  it("retries on 503 transient failure and eventually succeeds", async () => {
    mockGet
      .mockRejectedValueOnce(makeAxiosError(503))
      .mockResolvedValueOnce({ data: [makeApprovalDetail()] });

    const result = await governanceApi.listApprovals("corr-1");
    expect(result).toHaveLength(1);
    expect(mockGet).toHaveBeenCalledTimes(2);
    expect(mockLogger.retryAttempt).toHaveBeenCalledTimes(1);
  });

  it("retries on 429 rate-limit and eventually succeeds", async () => {
    mockGet.mockRejectedValueOnce(makeAxiosError(429)).mockResolvedValueOnce({ data: [] });

    const result = await governanceApi.listApprovals("corr-1");
    expect(result).toEqual([]);
    expect(mockGet).toHaveBeenCalledTimes(2);
  });

  it("does not retry on 400 bad-request", async () => {
    mockGet.mockRejectedValue(makeAxiosError(400));
    await expect(governanceApi.listApprovals("corr-1")).rejects.toBeInstanceOf(
      GovernanceNetworkError,
    );
    expect(mockGet).toHaveBeenCalledTimes(1);
  });

  it("wraps non-Error throwables from axios into a generic network error", async () => {
    mockGet.mockRejectedValue("unexpected string throwable");
    await expect(governanceApi.listApprovals("corr-1")).rejects.toBeInstanceOf(
      GovernanceNetworkError,
    );
    expect(mockLogger.listApprovalsFailure).toHaveBeenCalled();
  });

  it("rethrows AbortError without retrying", async () => {
    const abortErr = new DOMException("Aborted", "AbortError");
    mockGet.mockRejectedValue(abortErr);
    await expect(governanceApi.listApprovals("corr-1")).rejects.toBe(abortErr);
    expect(mockGet).toHaveBeenCalledTimes(1);
  });
});

describe("governanceApi.approveRequest (mutation — no retry)", () => {
  beforeEach(() => {
    vi.resetAllMocks();
  });

  it("posts to /approvals/:id/approve and returns validated response", async () => {
    mockPost.mockResolvedValue({ data: makeApprovalDecisionResponse("approved") });
    const result = await governanceApi.approveRequest("01HAPPROVAL0000000001", "corr-1");
    expect(result.status).toBe("approved");
    expect(mockPost).toHaveBeenCalledWith(
      "/api/approvals/01HAPPROVAL0000000001/approve",
      undefined,
      expect.objectContaining({
        headers: expect.objectContaining({ "X-Correlation-Id": "corr-1" }),
      }),
    );
  });

  it("does NOT retry on transient 503 (mutations are non-idempotent)", async () => {
    mockPost.mockRejectedValue(makeAxiosError(503));
    await expect(governanceApi.approveRequest("id-1", "corr-1")).rejects.toBeInstanceOf(
      GovernanceNetworkError,
    );
    expect(mockPost).toHaveBeenCalledTimes(1);
  });

  it("throws GovernanceSoDError on 409 Conflict", async () => {
    mockPost.mockRejectedValue(makeAxiosError(409));
    await expect(governanceApi.approveRequest("id-1", "corr-1")).rejects.toBeInstanceOf(
      GovernanceSoDError,
    );
  });

  it("throws GovernanceNotFoundError on 404", async () => {
    mockPost.mockRejectedValue(makeAxiosError(404));
    await expect(governanceApi.approveRequest("id-1", "corr-1")).rejects.toBeInstanceOf(
      GovernanceNotFoundError,
    );
  });
});

describe("governanceApi.rejectRequest (mutation — no retry)", () => {
  beforeEach(() => {
    vi.resetAllMocks();
  });

  it("posts rationale in body and returns validated response", async () => {
    mockPost.mockResolvedValue({ data: makeApprovalDecisionResponse("rejected") });
    await governanceApi.rejectRequest("id-1", "insufficient evidence", "corr-1");
    expect(mockPost).toHaveBeenCalledWith(
      "/api/approvals/id-1/reject",
      { rationale: "insufficient evidence" },
      expect.objectContaining({
        headers: expect.objectContaining({ "X-Correlation-Id": "corr-1" }),
      }),
    );
  });

  it("does not retry on transient failure", async () => {
    mockPost.mockRejectedValue(makeAxiosError(502));
    await expect(governanceApi.rejectRequest("id-1", "rationale", "corr-1")).rejects.toBeInstanceOf(
      GovernanceNetworkError,
    );
    expect(mockPost).toHaveBeenCalledTimes(1);
  });
});

describe("governanceApi.listOverrides", () => {
  beforeEach(() => {
    vi.resetAllMocks();
  });

  it("retries on transient 500 and succeeds", async () => {
    mockGet
      .mockRejectedValueOnce(makeAxiosError(500))
      .mockResolvedValueOnce({ data: [makeOverrideDetail()] });

    const result = await governanceApi.listOverrides("corr-1");
    expect(result).toHaveLength(1);
    expect(mockGet).toHaveBeenCalledTimes(2);
  });

  it("propagates correlationId as header", async () => {
    mockGet.mockResolvedValue({ data: [] });
    await governanceApi.listOverrides("trace-overrides");
    const config = mockGet.mock.calls[0][1] as AxiosRequestConfig;
    expect(config?.headers?.["X-Correlation-Id"]).toBe("trace-overrides");
  });
});

describe("governanceApi.getOverride", () => {
  beforeEach(() => {
    vi.resetAllMocks();
  });

  it("retries on transient failure for single-entity read", async () => {
    mockGet
      .mockRejectedValueOnce(makeAxiosError(503))
      .mockResolvedValueOnce({ data: makeOverrideDetail() });
    const result = await governanceApi.getOverride("01HOVERRIDE000000001", "corr-1");
    expect(result.id).toBe("01HOVERRIDE000000001");
    expect(mockGet).toHaveBeenCalledTimes(2);
  });

  it("throws GovernanceNotFoundError on 404", async () => {
    mockGet.mockRejectedValue(makeAxiosError(404));
    await expect(
      governanceApi.getOverride("01HOVERRIDE000000001", "corr-1"),
    ).rejects.toBeInstanceOf(GovernanceNotFoundError);
  });
});

describe("governanceApi.requestOverride (mutation — no retry)", () => {
  beforeEach(() => {
    vi.resetAllMocks();
  });

  it("posts payload and returns validated response", async () => {
    const payload = {
      object_id: "obj-1",
      object_type: "candidate" as const,
      override_type: "blocker_waiver" as const,
      rationale: "this rationale is long enough to pass validation",
      evidence_link: "https://jira.example.com/FX-1",
      original_state: {},
      new_state: {},
    };
    mockPost.mockResolvedValue({
      data: { override_id: "01HOVERRIDE000000001", status: "pending" },
    });
    const result = await governanceApi.requestOverride(payload, "corr-1");
    expect(result.override_id).toBe("01HOVERRIDE000000001");
    expect(mockPost).toHaveBeenCalledWith(
      "/api/overrides/request",
      payload,
      expect.objectContaining({
        headers: expect.objectContaining({ "X-Correlation-Id": "corr-1" }),
      }),
    );
  });

  it("does not retry on transient failure", async () => {
    mockPost.mockRejectedValue(makeAxiosError(503));
    const payload = {
      object_id: "obj-1",
      object_type: "candidate" as const,
      override_type: "blocker_waiver" as const,
      rationale: "long enough rationale for override request body here",
      evidence_link: "https://jira.example.com/FX-1",
      original_state: {},
      new_state: {},
    };
    await expect(governanceApi.requestOverride(payload, "corr-1")).rejects.toBeInstanceOf(
      GovernanceNetworkError,
    );
    expect(mockPost).toHaveBeenCalledTimes(1);
  });
});

describe("governanceApi.listPromotions", () => {
  beforeEach(() => {
    vi.resetAllMocks();
  });

  it("retries on transient failure", async () => {
    mockGet
      .mockRejectedValueOnce(makeAxiosError(500))
      .mockResolvedValueOnce({ data: [makePromotionEntry()] });
    const result = await governanceApi.listPromotions("cand-1", "corr-1");
    expect(result).toHaveLength(1);
    expect(mockGet).toHaveBeenCalledTimes(2);
  });

  it("sends candidate_id query param and correlation header", async () => {
    mockGet.mockResolvedValue({ data: [] });
    await governanceApi.listPromotions("cand-xyz", "trace-p");
    const [url, config] = mockGet.mock.calls[0] as [string, AxiosRequestConfig];
    expect(url).toBe("/api/promotions");
    expect(config?.params).toEqual({ candidate_id: "cand-xyz" });
    expect(config?.headers?.["X-Correlation-Id"]).toBe("trace-p");
  });

  it("forwards AbortSignal", async () => {
    mockGet.mockResolvedValue({ data: [] });
    const controller = new AbortController();
    await governanceApi.listPromotions("cand-1", "corr-1", controller.signal);
    const config = mockGet.mock.calls[0][1] as AxiosRequestConfig;
    expect(config?.signal).toBe(controller.signal);
  });
});

afterEach(() => {
  vi.resetAllMocks();
});
