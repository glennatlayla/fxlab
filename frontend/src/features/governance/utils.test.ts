/**
 * Tests for governance shared utilities.
 *
 * Covers: sanitizeUrl for XSS prevention across all governance components.
 */

import { describe, it, expect } from "vitest";
import { sanitizeUrl } from "./utils";

describe("sanitizeUrl", () => {
  it("accepts https URLs", () => {
    expect(sanitizeUrl("https://jira.example.com/FX-123")).toBe("https://jira.example.com/FX-123");
  });

  it("accepts http URLs", () => {
    expect(sanitizeUrl("http://internal.jira/RISK-99")).toBe("http://internal.jira/RISK-99");
  });

  it("blocks javascript: protocol", () => {
    expect(sanitizeUrl("javascript:alert(1)")).toBeNull();
  });

  it("blocks data: protocol", () => {
    expect(sanitizeUrl("data:text/html,<script>alert(1)</script>")).toBeNull();
  });

  it("blocks ftp: protocol", () => {
    expect(sanitizeUrl("ftp://evil.example.com/payload")).toBeNull();
  });

  it("blocks blob: protocol", () => {
    expect(sanitizeUrl("blob:https://example.com/uuid")).toBeNull();
  });

  it("returns null for invalid URLs", () => {
    expect(sanitizeUrl("not-a-url")).toBeNull();
  });

  it("returns null for empty string", () => {
    expect(sanitizeUrl("")).toBeNull();
  });
});
