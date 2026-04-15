/**
 * Tests for Results Explorer error types and classification.
 *
 * Verifies the error hierarchy, message formatting, toJSON serialization,
 * cause chain preservation, and the isTransientError classifier per
 * CLAUDE.md §9 retry policy.
 */

import { describe, it, expect } from "vitest";
import {
  ResultsError,
  ResultsNotFoundError,
  ResultsAuthError,
  ResultsValidationError,
  ResultsNetworkError,
  ResultsDownloadError,
  isTransientError,
} from "./errors";

// ---------------------------------------------------------------------------
// Error hierarchy
// ---------------------------------------------------------------------------

describe("ResultsError hierarchy", () => {
  it("ResultsNotFoundError extends ResultsError", () => {
    const err = new ResultsNotFoundError("run-1");
    expect(err).toBeInstanceOf(ResultsError);
    expect(err.name).toBe("ResultsNotFoundError");
    expect(err.runId).toBe("run-1");
    expect(err.message).toContain("run-1");
  });

  it("ResultsAuthError stores status code for 401", () => {
    const err = new ResultsAuthError("run-2", 401);
    expect(err).toBeInstanceOf(ResultsError);
    expect(err.name).toBe("ResultsAuthError");
    expect(err.statusCode).toBe(401);
    expect(err.message).toContain("Authentication required");
  });

  it("ResultsAuthError stores status code for 403", () => {
    const err = new ResultsAuthError("run-3", 403);
    expect(err.statusCode).toBe(403);
    expect(err.message).toContain("Permission denied");
  });

  it("ResultsValidationError stores validation errors", () => {
    const zodErrors = [{ path: ["run_id"], message: "Required" }];
    const err = new ResultsValidationError("run-2", zodErrors);
    expect(err).toBeInstanceOf(ResultsError);
    expect(err.validationErrors).toEqual(zodErrors);
  });

  it("ResultsNetworkError stores status code", () => {
    const err = new ResultsNetworkError("run-3", 503);
    expect(err.statusCode).toBe(503);
    expect(err.message).toContain("503");
  });

  it("ResultsNetworkError includes cause message when cause is an Error", () => {
    const cause = new Error("Connection refused");
    const err = new ResultsNetworkError("run-3", undefined, cause);
    expect(err.message).toContain("Connection refused");
  });

  it("ResultsDownloadError stores reason", () => {
    const err = new ResultsDownloadError("run-4", "timeout");
    expect(err.reason).toBe("timeout");
    expect(err.message).toContain("timeout");
  });
});

// ---------------------------------------------------------------------------
// Cause chain preservation
// ---------------------------------------------------------------------------

describe("Error cause chain", () => {
  it("preserves cause through the error chain", () => {
    const original = new Error("Original failure");
    const err = new ResultsNetworkError("run-1", 500, original);
    expect(err.cause).toBe(original);
  });

  it("preserves non-Error cause", () => {
    const err = new ResultsNotFoundError("run-1", "string-cause");
    expect(err.cause).toBe("string-cause");
  });
});

// ---------------------------------------------------------------------------
// toJSON serialization
// ---------------------------------------------------------------------------

describe("Error toJSON serialization", () => {
  it("ResultsError.toJSON returns structured object", () => {
    const cause = new Error("root cause");
    const err = new ResultsError("test error", "run-1", cause);
    const json = err.toJSON();
    expect(json).toEqual({
      name: "ResultsError",
      message: "test error",
      runId: "run-1",
      cause: "root cause",
    });
  });

  it("ResultsAuthError.toJSON includes statusCode", () => {
    const err = new ResultsAuthError("run-1", 401);
    const json = err.toJSON();
    expect(json.statusCode).toBe(401);
    expect(json.name).toBe("ResultsAuthError");
  });

  it("ResultsNetworkError.toJSON includes statusCode", () => {
    const err = new ResultsNetworkError("run-1", 503);
    expect(err.toJSON().statusCode).toBe(503);
  });

  it("ResultsValidationError.toJSON includes validationErrors", () => {
    const zodErrors = [{ path: ["run_id"], message: "Required" }];
    const err = new ResultsValidationError("run-1", zodErrors);
    expect(err.toJSON().validationErrors).toEqual(zodErrors);
  });

  it("ResultsDownloadError.toJSON includes reason", () => {
    const err = new ResultsDownloadError("run-1", "timeout");
    expect(err.toJSON().reason).toBe("timeout");
  });

  it("toJSON survives JSON.stringify round-trip", () => {
    const err = new ResultsNetworkError("run-1", 502, new Error("Gateway error"));
    const serialized = JSON.parse(JSON.stringify(err.toJSON()));
    expect(serialized.name).toBe("ResultsNetworkError");
    expect(serialized.statusCode).toBe(502);
    expect(serialized.cause).toBe("Gateway error");
  });
});

// ---------------------------------------------------------------------------
// isTransientError classifier
// ---------------------------------------------------------------------------

describe("isTransientError", () => {
  it("returns false for ResultsNotFoundError (404 — no retry)", () => {
    expect(isTransientError(new ResultsNotFoundError("r1"))).toBe(false);
  });

  it("returns false for ResultsAuthError (401 — no retry)", () => {
    expect(isTransientError(new ResultsAuthError("r1", 401))).toBe(false);
  });

  it("returns false for ResultsAuthError (403 — no retry)", () => {
    expect(isTransientError(new ResultsAuthError("r1", 403))).toBe(false);
  });

  it("returns false for ResultsValidationError (schema — no retry)", () => {
    expect(isTransientError(new ResultsValidationError("r1", []))).toBe(false);
  });

  it("returns true for ResultsNetworkError with 500", () => {
    expect(isTransientError(new ResultsNetworkError("r1", 500))).toBe(true);
  });

  it("returns true for ResultsNetworkError with 503", () => {
    expect(isTransientError(new ResultsNetworkError("r1", 503))).toBe(true);
  });

  it("returns true for ResultsNetworkError with 429 (rate limited)", () => {
    expect(isTransientError(new ResultsNetworkError("r1", 429))).toBe(true);
  });

  it("returns false for ResultsNetworkError with 400 (bad request)", () => {
    expect(isTransientError(new ResultsNetworkError("r1", 400))).toBe(false);
  });

  it("returns false for ResultsNetworkError with 403 (forbidden)", () => {
    expect(isTransientError(new ResultsNetworkError("r1", 403))).toBe(false);
  });

  it("returns true for ResultsNetworkError with no status (network failure)", () => {
    expect(isTransientError(new ResultsNetworkError("r1", undefined))).toBe(true);
  });

  it("returns true for ResultsDownloadError with reason 'network'", () => {
    expect(isTransientError(new ResultsDownloadError("r1", "network"))).toBe(true);
  });

  it("returns true for ResultsDownloadError with reason 'timeout'", () => {
    expect(isTransientError(new ResultsDownloadError("r1", "timeout"))).toBe(true);
  });

  it("returns false for ResultsDownloadError with reason 'abort'", () => {
    expect(isTransientError(new ResultsDownloadError("r1", "abort"))).toBe(false);
  });

  it("returns false for generic Error", () => {
    expect(isTransientError(new Error("something"))).toBe(false);
  });

  it("returns false for non-Error values", () => {
    expect(isTransientError("string")).toBe(false);
    expect(isTransientError(null)).toBe(false);
    expect(isTransientError(undefined)).toBe(false);
  });
});
