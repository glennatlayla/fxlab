/**
 * Tests for Readiness feature error hierarchy.
 *
 * Verifies error classification, toJSON serialization,
 * cause chain propagation, and transient error detection.
 */

import { describe, it, expect } from "vitest";
import {
  ReadinessError,
  ReadinessNotFoundError,
  ReadinessAuthError,
  ReadinessValidationError,
  ReadinessNetworkError,
  ReadinessGenerationError,
  isTransientError,
} from "./errors";

describe("ReadinessError (base)", () => {
  it("stores runId and message", () => {
    const err = new ReadinessError("test message", "run-1");
    expect(err.message).toBe("test message");
    expect(err.runId).toBe("run-1");
    expect(err.name).toBe("ReadinessError");
  });

  it("toJSON includes name, message, runId", () => {
    const err = new ReadinessError("msg", "run-2");
    const json = err.toJSON();
    expect(json.name).toBe("ReadinessError");
    expect(json.message).toBe("msg");
    expect(json.runId).toBe("run-2");
  });

  it("toJSON serializes Error cause as message string", () => {
    const cause = new Error("root cause");
    const err = new ReadinessError("msg", "run-3", cause);
    expect(err.toJSON().cause).toBe("root cause");
  });

  it("toJSON serializes non-Error cause as-is", () => {
    const err = new ReadinessError("msg", "run-4", "string cause");
    expect(err.toJSON().cause).toBe("string cause");
  });
});

describe("ReadinessNotFoundError", () => {
  it("has correct name and message", () => {
    const err = new ReadinessNotFoundError("run-1");
    expect(err.name).toBe("ReadinessNotFoundError");
    expect(err.message).toContain("not found");
    expect(err.runId).toBe("run-1");
  });
});

describe("ReadinessAuthError", () => {
  it("generates 401 message", () => {
    const err = new ReadinessAuthError("run-1", 401);
    expect(err.message).toContain("Authentication required");
    expect(err.statusCode).toBe(401);
  });

  it("generates 403 message", () => {
    const err = new ReadinessAuthError("run-1", 403);
    expect(err.message).toContain("Permission denied");
    expect(err.statusCode).toBe(403);
  });

  it("toJSON includes statusCode", () => {
    const err = new ReadinessAuthError("run-1", 403);
    expect(err.toJSON().statusCode).toBe(403);
  });
});

describe("ReadinessValidationError", () => {
  it("includes issue count in message", () => {
    const err = new ReadinessValidationError("run-1", [{ path: "a" }, { path: "b" }]);
    expect(err.message).toContain("2 issue(s)");
    expect(err.issues).toHaveLength(2);
  });

  it("toJSON includes issueCount", () => {
    const err = new ReadinessValidationError("run-1", [{ path: "a" }]);
    expect(err.toJSON().issueCount).toBe(1);
  });
});

describe("ReadinessNetworkError", () => {
  it("includes status code when provided", () => {
    const err = new ReadinessNetworkError("run-1", 503);
    expect(err.message).toContain("503");
    expect(err.statusCode).toBe(503);
  });

  it("works without status code", () => {
    const err = new ReadinessNetworkError("run-1");
    expect(err.statusCode).toBeUndefined();
  });
});

describe("ReadinessGenerationError", () => {
  it("includes run ID in message", () => {
    const err = new ReadinessGenerationError("run-1", 500);
    expect(err.message).toContain("run-1");
    expect(err.statusCode).toBe(500);
  });
});

describe("isTransientError", () => {
  it("returns false for ReadinessNotFoundError", () => {
    expect(isTransientError(new ReadinessNotFoundError("run-1"))).toBe(false);
  });

  it("returns false for ReadinessAuthError", () => {
    expect(isTransientError(new ReadinessAuthError("run-1", 401))).toBe(false);
  });

  it("returns false for ReadinessValidationError", () => {
    expect(isTransientError(new ReadinessValidationError("run-1", []))).toBe(false);
  });

  it("returns true for ReadinessNetworkError with 500", () => {
    expect(isTransientError(new ReadinessNetworkError("run-1", 500))).toBe(true);
  });

  it("returns true for ReadinessNetworkError with 429", () => {
    expect(isTransientError(new ReadinessNetworkError("run-1", 429))).toBe(true);
  });

  it("returns false for ReadinessNetworkError with 400", () => {
    expect(isTransientError(new ReadinessNetworkError("run-1", 400))).toBe(false);
  });

  it("returns true for ReadinessNetworkError with no status (network-level)", () => {
    expect(isTransientError(new ReadinessNetworkError("run-1"))).toBe(true);
  });

  it("returns true for ReadinessGenerationError with 503", () => {
    expect(isTransientError(new ReadinessGenerationError("run-1", 503))).toBe(true);
  });

  it("returns false for unknown error types", () => {
    expect(isTransientError(new Error("random"))).toBe(false);
  });
});
