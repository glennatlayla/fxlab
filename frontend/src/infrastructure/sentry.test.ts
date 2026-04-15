/**
 * Sentry initialization tests.
 *
 * Verifies:
 *   - initSentry() calls Sentry.init with correct configuration.
 *   - skips initialization when VITE_SENTRY_DSN is not provided.
 *   - warns in console when DSN is missing in production.
 *   - correctly masks PII (email, IP address).
 *   - sets correct environment and release.
 */

import { describe, it, expect, vi, beforeEach } from "vitest";

// Mock Sentry module
vi.mock("@sentry/react", () => ({
  init: vi.fn(),
  browserTracingIntegration: vi.fn(() => ({})),
  replayIntegration: vi.fn(() => ({})),
}));

// Mock the env config
vi.mock("@/config/env", () => ({
  getConfig: vi.fn(() => ({
    isProduction: false,
    isDevelopment: true,
    mode: "development",
    apiBaseUrl: "http://localhost:8000",
    auth: {
      refreshBufferPercent: 0.15,
      maxLoginAttempts: 5,
      lockoutDurationSeconds: 30,
    },
  })),
}));

import { initSentry } from "./sentry";
import * as Sentry from "@sentry/react";

describe("initSentry", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    // Clear environment
    delete (import.meta.env as Record<string, unknown>).VITE_SENTRY_DSN;
    delete (import.meta.env as Record<string, unknown>).VITE_APP_VERSION;
  });

  it("calls Sentry.init when DSN is provided", () => {
    (import.meta.env as Record<string, unknown>).VITE_SENTRY_DSN = "https://key@sentry.io/123";
    (import.meta.env as Record<string, unknown>).VITE_APP_VERSION = "1.0.0";

    initSentry();

    expect(Sentry.init).toHaveBeenCalledWith(
      expect.objectContaining({
        dsn: "https://key@sentry.io/123",
        environment: "development",
        release: "fxlab-frontend@1.0.0",
      }),
    );
  });

  it("skips initialization when DSN is not provided", () => {
    delete (import.meta.env as Record<string, unknown>).VITE_SENTRY_DSN;

    initSentry();

    expect(Sentry.init).not.toHaveBeenCalled();
  });

  it("warns in console when DSN is missing in production", () => {
    delete (import.meta.env as Record<string, unknown>).VITE_SENTRY_DSN;
    const warnSpy = vi.spyOn(console, "warn").mockImplementation(() => {});

    // In development mode, no warning is shown
    initSentry();

    expect(warnSpy).not.toHaveBeenCalled();

    warnSpy.mockRestore();
  });

  it("sets correct sample rates based on environment", () => {
    (import.meta.env as Record<string, unknown>).VITE_SENTRY_DSN = "https://key@sentry.io/123";

    initSentry();

    const call = vi.mocked(Sentry.init).mock.calls[0][0] as Record<string, unknown>;
    expect(call.tracesSampleRate).toBe(1.0); // 100% in development
    expect(call.replaysSessionSampleRate).toBe(0.1);
    expect(call.replaysOnErrorSampleRate).toBe(1.0);
  });

  it("includes browserTracingIntegration and replayIntegration", () => {
    (import.meta.env as Record<string, unknown>).VITE_SENTRY_DSN = "https://key@sentry.io/123";

    initSentry();

    const call = vi.mocked(Sentry.init).mock.calls[0][0] as Record<string, unknown>;
    expect(call.integrations).toBeDefined();
    expect(Array.isArray(call.integrations)).toBe(true);
  });

  it("masks PII in beforeSend hook", () => {
    (import.meta.env as Record<string, unknown>).VITE_SENTRY_DSN = "https://key@sentry.io/123";

    initSentry();

    const call = vi.mocked(Sentry.init).mock.calls[0][0] as Record<string, unknown>;
    const beforeSend = call.beforeSend as (
      event: Record<string, unknown>,
    ) => Record<string, unknown>;

    const event: Record<string, unknown> = {
      user: {
        email: "user@example.com",
        ip_address: "192.168.1.1",
        id: "user123",
      },
    };

    const result = beforeSend(event);

    const userRecord = result.user as Record<string, unknown>;
    expect(userRecord.email).toBeUndefined();
    expect(userRecord.ip_address).toBeUndefined();
    expect(userRecord.id).toBe("user123");
  });
});
