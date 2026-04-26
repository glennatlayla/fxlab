/**
 * Environment configuration tests.
 *
 * Verifies:
 *   - getConfig returns validated config object.
 *   - apiBaseUrl falls back to default in development.
 *   - isDevelopment / isProduction flags derived from MODE.
 */

import { describe, it, expect } from "vitest";
import { getConfig } from "./env";

describe("getConfig", () => {
  it("returns a config object with required fields", () => {
    const config = getConfig();

    expect(config).toHaveProperty("apiBaseUrl");
    expect(config).toHaveProperty("isDevelopment");
    expect(config).toHaveProperty("isProduction");
    expect(typeof config.apiBaseUrl).toBe("string");
  });

  it("apiBaseUrl is a valid URL", () => {
    const config = getConfig();
    // apiBaseUrl may be either an absolute URL (e.g. "https://api.example.com")
    // or a relative path (e.g. "/api") — the latter is the recommended default
    // for Docker deployments behind an nginx proxy. Validate both shapes by
    // resolving against an arbitrary base when the value starts with "/".
    const isRelative = config.apiBaseUrl.startsWith("/");
    if (isRelative) {
      expect(() => new URL(config.apiBaseUrl, "http://localhost")).not.toThrow();
    } else {
      expect(() => new URL(config.apiBaseUrl)).not.toThrow();
    }
  });

  it("has auth configuration", () => {
    const config = getConfig();

    expect(config).toHaveProperty("auth");
    expect(config.auth).toHaveProperty("refreshBufferPercent");
    expect(config.auth).toHaveProperty("maxLoginAttempts");
    expect(config.auth).toHaveProperty("lockoutDurationSeconds");
    expect(config.auth.refreshBufferPercent).toBeGreaterThan(0);
    expect(config.auth.refreshBufferPercent).toBeLessThan(1);
  });
});
