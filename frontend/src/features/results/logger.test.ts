/**
 * Tests for Results Explorer structured logger.
 *
 * Verifies that all log methods emit structured output with required
 * fields per CLAUDE.md §8, add Sentry breadcrumbs for user action
 * trail, report errors to Sentry, and propagate correlationId.
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { resultsLogger } from "./logger";

vi.mock("@/infrastructure/sentry", () => ({
  Sentry: {
    captureException: vi.fn(),
    addBreadcrumb: vi.fn(),
  },
}));

import { Sentry } from "@/infrastructure/sentry";

describe("resultsLogger", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    vi.spyOn(console, "info").mockImplementation(() => {});
    vi.spyOn(console, "debug").mockImplementation(() => {});
    vi.spyOn(console, "warn").mockImplementation(() => {});
    vi.spyOn(console, "error").mockImplementation(() => {});
  });

  // -------------------------------------------------------------------------
  // API fetch lifecycle
  // -------------------------------------------------------------------------

  it("fetchStart logs info with run_id", () => {
    resultsLogger.fetchStart("run-123");
    // eslint-disable-next-line no-console -- asserting-on-logger-console-output
    expect(console.info).toHaveBeenCalledWith(
      expect.stringContaining("Fetching run charts"),
      expect.objectContaining({ run_id: "run-123", operation: "results.fetch_run_charts" }),
    );
  });

  it("fetchStart adds Sentry breadcrumb", () => {
    resultsLogger.fetchStart("run-123");
    expect(Sentry.addBreadcrumb).toHaveBeenCalledWith(
      expect.objectContaining({
        category: "results-explorer",
        message: "Fetching run charts",
        data: expect.objectContaining({ run_id: "run-123" }),
      }),
    );
  });

  it("fetchStart propagates correlationId when provided", () => {
    resultsLogger.fetchStart("run-123", "corr-abc");
    // eslint-disable-next-line no-console -- asserting-on-logger-console-output
    expect(console.info).toHaveBeenCalledWith(
      expect.any(String),
      expect.objectContaining({ correlation_id: "corr-abc" }),
    );
  });

  it("fetchRetry logs warn with attempt, maxRetries, and delay", () => {
    resultsLogger.fetchRetry("run-123", 2, 3, 2045);
    expect(console.warn).toHaveBeenCalledWith(
      expect.stringContaining("Retrying fetch (attempt 2 of 3)"),
      expect.objectContaining({
        run_id: "run-123",
        attempt: 2,
        max_retries: 3,
        delay_ms: 2045,
      }),
    );
  });

  it("fetchRetry adds Sentry breadcrumb at warning level", () => {
    resultsLogger.fetchRetry("run-123", 1, 3, 1000);
    expect(Sentry.addBreadcrumb).toHaveBeenCalledWith(
      expect.objectContaining({
        category: "results-explorer",
        level: "warning",
      }),
    );
  });

  it("fetchRetry propagates correlationId when provided", () => {
    resultsLogger.fetchRetry("run-123", 1, 3, 1000, "corr-xyz");
    expect(console.warn).toHaveBeenCalledWith(
      expect.any(String),
      expect.objectContaining({ correlation_id: "corr-xyz" }),
    );
  });

  it("fetchSuccess logs info with duration and metadata", () => {
    resultsLogger.fetchSuccess("run-123", 150, { pointCount: 2000, tradeCount: 500 });
    // eslint-disable-next-line no-console -- asserting-on-logger-console-output
    expect(console.info).toHaveBeenCalledWith(
      expect.stringContaining("fetched successfully"),
      expect.objectContaining({
        run_id: "run-123",
        duration_ms: 150,
        equity_point_count: 2000,
        trade_count: 500,
        result: "success",
      }),
    );
  });

  it("fetchSuccess propagates correlationId when provided", () => {
    resultsLogger.fetchSuccess("run-123", 150, { pointCount: 100, tradeCount: 10 }, "corr-def");
    // eslint-disable-next-line no-console -- asserting-on-logger-console-output
    expect(console.info).toHaveBeenCalledWith(
      expect.any(String),
      expect.objectContaining({ correlation_id: "corr-def" }),
    );
  });

  it("fetchFailure logs error and reports to Sentry", () => {
    const error = new Error("Network failed");
    resultsLogger.fetchFailure("run-123", error, 200);
    expect(console.error).toHaveBeenCalledWith(
      expect.stringContaining("fetch failed"),
      expect.objectContaining({ run_id: "run-123", result: "failure", duration_ms: 200 }),
    );
    expect(Sentry.captureException).toHaveBeenCalledWith(
      error,
      expect.objectContaining({
        tags: expect.objectContaining({ feature: "ResultsExplorer" }),
      }),
    );
  });

  it("fetchFailure propagates correlationId to Sentry context", () => {
    const error = new Error("fail");
    resultsLogger.fetchFailure("run-123", error, 100, "corr-sentry");
    expect(Sentry.captureException).toHaveBeenCalledWith(
      error,
      expect.objectContaining({
        contexts: expect.objectContaining({
          results: expect.objectContaining({ correlation_id: "corr-sentry" }),
        }),
      }),
    );
  });

  it("fetchFailure handles non-Error values gracefully", () => {
    resultsLogger.fetchFailure("run-123", "string error", 100);
    expect(console.error).toHaveBeenCalledWith(
      expect.any(String),
      expect.objectContaining({ error: "string error" }),
    );
  });

  // -------------------------------------------------------------------------
  // Validation
  // -------------------------------------------------------------------------

  it("validationFailure logs warning and reports to Sentry", () => {
    resultsLogger.validationFailure("run-123", [{ path: ["run_id"] }]);
    expect(console.warn).toHaveBeenCalled();
    expect(Sentry.captureException).toHaveBeenCalled();
  });

  it("validationFailure includes error count in message", () => {
    resultsLogger.validationFailure("run-123", [
      { path: ["a"], message: "err1" },
      { path: ["b"], message: "err2" },
    ]);
    expect(console.warn).toHaveBeenCalledWith(
      expect.stringContaining("2 issue(s)"),
      expect.objectContaining({ validation_error_count: 2 }),
    );
  });

  it("validationFailure propagates correlationId when provided", () => {
    resultsLogger.validationFailure("run-123", [], "corr-val");
    expect(console.warn).toHaveBeenCalledWith(
      expect.any(String),
      expect.objectContaining({ correlation_id: "corr-val" }),
    );
  });

  // -------------------------------------------------------------------------
  // Download lifecycle
  // -------------------------------------------------------------------------

  it("downloadStart logs info", () => {
    resultsLogger.downloadStart("run-123");
    // eslint-disable-next-line no-console -- asserting-on-logger-console-output
    expect(console.info).toHaveBeenCalledWith(
      expect.stringContaining("Starting export"),
      expect.objectContaining({ run_id: "run-123" }),
    );
  });

  it("downloadSuccess logs info with size", () => {
    resultsLogger.downloadSuccess("run-123", 3000, 1_048_576);
    // eslint-disable-next-line no-console -- asserting-on-logger-console-output
    expect(console.info).toHaveBeenCalledWith(
      expect.stringContaining("downloaded successfully"),
      expect.objectContaining({ size_bytes: 1_048_576 }),
    );
  });

  it("downloadFailure logs error and reports to Sentry", () => {
    const error = new Error("Timeout");
    resultsLogger.downloadFailure("run-123", error, 60000);
    expect(console.error).toHaveBeenCalled();
    expect(Sentry.captureException).toHaveBeenCalledWith(
      error,
      expect.objectContaining({
        tags: expect.objectContaining({ operation: "download_export" }),
      }),
    );
  });

  it("downloadAborted logs info with abort result", () => {
    resultsLogger.downloadAborted("run-123");
    // eslint-disable-next-line no-console -- asserting-on-logger-console-output
    expect(console.info).toHaveBeenCalledWith(
      expect.stringContaining("aborted"),
      expect.objectContaining({ result: "abort" }),
    );
  });

  // -------------------------------------------------------------------------
  // Page lifecycle
  // -------------------------------------------------------------------------

  it("pageMount logs info", () => {
    resultsLogger.pageMount("run-123");
    // eslint-disable-next-line no-console -- asserting-on-logger-console-output
    expect(console.info).toHaveBeenCalledWith(
      expect.stringContaining("mounted"),
      expect.objectContaining({ component: "RunResultsPage" }),
    );
  });

  it("pageUnmount logs debug", () => {
    resultsLogger.pageUnmount("run-123");
    // eslint-disable-next-line no-console -- asserting-on-logger-console-output
    expect(console.debug).toHaveBeenCalledWith(
      expect.stringContaining("unmounting"),
      expect.objectContaining({ component: "RunResultsPage" }),
    );
  });

  // -------------------------------------------------------------------------
  // Sentry breadcrumb integration
  // -------------------------------------------------------------------------

  it("every log method adds a Sentry breadcrumb", () => {
    resultsLogger.fetchStart("r1");
    resultsLogger.fetchSuccess("r1", 100, { pointCount: 10, tradeCount: 5 });
    resultsLogger.downloadStart("r1");
    resultsLogger.downloadAborted("r1");
    resultsLogger.pageMount("r1");
    resultsLogger.pageUnmount("r1");

    // 6 calls above — each should produce a breadcrumb.
    expect(Sentry.addBreadcrumb).toHaveBeenCalledTimes(6);
  });

  it("Sentry breadcrumb contains operation and run_id", () => {
    resultsLogger.downloadStart("run-456");
    expect(Sentry.addBreadcrumb).toHaveBeenCalledWith(
      expect.objectContaining({
        data: expect.objectContaining({
          operation: "results.download_export_bundle",
          run_id: "run-456",
        }),
      }),
    );
  });

  // -------------------------------------------------------------------------
  // Structured fields
  // -------------------------------------------------------------------------

  it("all emitted entries include a timestamp", () => {
    resultsLogger.fetchStart("run-ts");
    // eslint-disable-next-line no-console -- asserting-on-logger-console-output
    const call = vi.mocked(console.info).mock.calls[0];
    const entry = call[1] as Record<string, unknown>;
    expect(entry.timestamp).toBeDefined();
    // Should be a valid ISO timestamp.
    expect(new Date(entry.timestamp as string).toISOString()).toBe(entry.timestamp);
  });
});
