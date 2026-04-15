/**
 * Tests for governance feature error hierarchy.
 *
 * Covers: construction, toJSON serialization, and transient classification
 * for all governance error types.
 */

import { describe, it, expect } from "vitest";
import {
  GovernanceError,
  GovernanceNotFoundError,
  GovernanceAuthError,
  GovernanceValidationError,
  GovernanceNetworkError,
  GovernanceSoDError,
  isTransientError,
} from "./errors";

// ---------------------------------------------------------------------------
// GovernanceError (base)
// ---------------------------------------------------------------------------

describe("GovernanceError", () => {
  it("sets name, message, and entityId", () => {
    const err = new GovernanceError("test", "ent-1");
    expect(err.name).toBe("GovernanceError");
    expect(err.message).toBe("test");
    expect(err.entityId).toBe("ent-1");
  });

  it("serializes to JSON with cause message", () => {
    const cause = new Error("root cause");
    const err = new GovernanceError("test", "ent-1", cause);
    expect(err.toJSON()).toEqual({
      name: "GovernanceError",
      message: "test",
      entityId: "ent-1",
      cause: "root cause",
    });
  });

  it("serializes non-Error cause as-is", () => {
    const err = new GovernanceError("test", "ent-1", "string cause");
    expect(err.toJSON().cause).toBe("string cause");
  });
});

// ---------------------------------------------------------------------------
// GovernanceNotFoundError
// ---------------------------------------------------------------------------

describe("GovernanceNotFoundError", () => {
  it("includes entityId in message", () => {
    const err = new GovernanceNotFoundError("appr-1");
    expect(err.message).toContain("appr-1");
    expect(err.name).toBe("GovernanceNotFoundError");
  });
});

// ---------------------------------------------------------------------------
// GovernanceAuthError
// ---------------------------------------------------------------------------

describe("GovernanceAuthError", () => {
  it("sets statusCode 401 with authentication message", () => {
    const err = new GovernanceAuthError("ent-1", 401);
    expect(err.statusCode).toBe(401);
    expect(err.message).toContain("Authentication required");
  });

  it("sets statusCode 403 with permission message", () => {
    const err = new GovernanceAuthError("ent-1", 403);
    expect(err.statusCode).toBe(403);
    expect(err.message).toContain("Permission denied");
  });

  it("includes statusCode in toJSON", () => {
    const err = new GovernanceAuthError("ent-1", 403);
    expect(err.toJSON().statusCode).toBe(403);
  });
});

// ---------------------------------------------------------------------------
// GovernanceValidationError
// ---------------------------------------------------------------------------

describe("GovernanceValidationError", () => {
  it("includes issue count in message", () => {
    const err = new GovernanceValidationError("ent-1", [
      { code: "invalid_type" },
      { code: "too_small" },
    ]);
    expect(err.message).toContain("2 issue(s)");
  });

  it("includes issueCount in toJSON", () => {
    const err = new GovernanceValidationError("ent-1", [{ code: "err" }]);
    expect(err.toJSON().issueCount).toBe(1);
  });
});

// ---------------------------------------------------------------------------
// GovernanceNetworkError
// ---------------------------------------------------------------------------

describe("GovernanceNetworkError", () => {
  it("includes status code in message when provided", () => {
    const err = new GovernanceNetworkError("ent-1", 500);
    expect(err.message).toContain("500");
    expect(err.statusCode).toBe(500);
  });

  it("omits status code from message when not provided", () => {
    const err = new GovernanceNetworkError("ent-1");
    expect(err.message).not.toContain("undefined");
    expect(err.statusCode).toBeUndefined();
  });
});

// ---------------------------------------------------------------------------
// GovernanceSoDError
// ---------------------------------------------------------------------------

describe("GovernanceSoDError", () => {
  it("includes entityId in message", () => {
    const err = new GovernanceSoDError("appr-1");
    expect(err.message).toContain("appr-1");
    expect(err.message).toContain("Separation of duties");
    expect(err.name).toBe("GovernanceSoDError");
  });
});

// ---------------------------------------------------------------------------
// isTransientError
// ---------------------------------------------------------------------------

describe("isTransientError", () => {
  it("returns false for GovernanceNotFoundError", () => {
    expect(isTransientError(new GovernanceNotFoundError("ent-1"))).toBe(false);
  });

  it("returns false for GovernanceAuthError", () => {
    expect(isTransientError(new GovernanceAuthError("ent-1", 401))).toBe(false);
    expect(isTransientError(new GovernanceAuthError("ent-1", 403))).toBe(false);
  });

  it("returns false for GovernanceValidationError", () => {
    expect(isTransientError(new GovernanceValidationError("ent-1", []))).toBe(false);
  });

  it("returns false for GovernanceSoDError", () => {
    expect(isTransientError(new GovernanceSoDError("ent-1"))).toBe(false);
  });

  it("returns true for GovernanceNetworkError with no status code", () => {
    expect(isTransientError(new GovernanceNetworkError("ent-1"))).toBe(true);
  });

  it("returns true for GovernanceNetworkError with 429", () => {
    expect(isTransientError(new GovernanceNetworkError("ent-1", 429))).toBe(true);
  });

  it("returns true for GovernanceNetworkError with 500", () => {
    expect(isTransientError(new GovernanceNetworkError("ent-1", 500))).toBe(true);
  });

  it("returns true for GovernanceNetworkError with 502", () => {
    expect(isTransientError(new GovernanceNetworkError("ent-1", 502))).toBe(true);
  });

  it("returns true for GovernanceNetworkError with 503", () => {
    expect(isTransientError(new GovernanceNetworkError("ent-1", 503))).toBe(true);
  });

  it("returns false for GovernanceNetworkError with 400", () => {
    expect(isTransientError(new GovernanceNetworkError("ent-1", 400))).toBe(false);
  });

  it("returns false for GovernanceNetworkError with 409", () => {
    expect(isTransientError(new GovernanceNetworkError("ent-1", 409))).toBe(false);
  });

  it("returns false for unknown error types", () => {
    expect(isTransientError(new Error("random"))).toBe(false);
  });
});
