/**
 * Tests for Readiness feature structured logger.
 *
 * Verifies that every logger method emits structured log entries with
 * the correct fields per CLAUDE.md §8 and adds Sentry breadcrumbs.
 * Also verifies that fetchFailure, generateFailure, and promotionFailure
 * call Sentry.captureException with appropriate tags and context.
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { readinessLogger } from "./logger";

// ---------------------------------------------------------------------------
// Mocks
// ---------------------------------------------------------------------------

vi.mock("@/infrastructure/sentry", () => ({
  Sentry: {
    addBreadcrumb: vi.fn(),
    captureException: vi.fn(),
  },
}));

import { Sentry } from "@/infrastructure/sentry";

const mockAddBreadcrumb = vi.mocked(Sentry.addBreadcrumb);
const mockCaptureException = vi.mocked(Sentry.captureException);

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/** Suppress console output during tests. */
const consoleSpy = {
  debug: vi.spyOn(console, "debug").mockImplementation(() => {}),
  info: vi.spyOn(console, "info").mockImplementation(() => {}),
  warn: vi.spyOn(console, "warn").mockImplementation(() => {}),
  error: vi.spyOn(console, "error").mockImplementation(() => {}),
};

beforeEach(() => {
  vi.clearAllMocks();
});

// ---------------------------------------------------------------------------
// Fetch lifecycle
// ---------------------------------------------------------------------------

describe("readinessLogger — fetch lifecycle", () => {
  it("fetchStart emits info log with operation and run_id", () => {
    readinessLogger.fetchStart("run-1");

    expect(consoleSpy.info).toHaveBeenCalledWith(
      "[Readiness] Fetching readiness report",
      expect.objectContaining({
        operation: "readiness.fetch_report",
        component: "readinessApi",
        run_id: "run-1",
        timestamp: expect.any(String),
      }),
    );
  });

  it("fetchStart adds Sentry breadcrumb", () => {
    readinessLogger.fetchStart("run-1");

    expect(mockAddBreadcrumb).toHaveBeenCalledWith(
      expect.objectContaining({
        category: "readiness",
        message: "Fetching readiness report",
        level: "info",
      }),
    );
  });

  it("fetchStart propagates correlationId when provided", () => {
    readinessLogger.fetchStart("run-1", "corr-123");

    expect(consoleSpy.info).toHaveBeenCalledWith(
      expect.any(String),
      expect.objectContaining({ correlation_id: "corr-123" }),
    );
  });

  it("fetchSuccess emits info log with duration and metadata", () => {
    readinessLogger.fetchSuccess("run-1", 150, {
      grade: "A",
      score: 85,
      dimensionCount: 6,
    });

    expect(consoleSpy.info).toHaveBeenCalledWith(
      "[Readiness] Readiness report fetched successfully",
      expect.objectContaining({
        operation: "readiness.fetch_report",
        result: "success",
        run_id: "run-1",
        duration_ms: 150,
        grade: "A",
        score: 85,
        dimension_count: 6,
      }),
    );
  });

  it("fetchFailure emits error log and captures Sentry exception", () => {
    const error = new Error("Network timeout");
    readinessLogger.fetchFailure("run-1", error, 3000);

    expect(consoleSpy.error).toHaveBeenCalledWith(
      "[Readiness] Readiness report fetch failed",
      expect.objectContaining({
        operation: "readiness.fetch_report",
        result: "failure",
        run_id: "run-1",
        duration_ms: 3000,
        error: "Network timeout",
      }),
    );

    expect(mockCaptureException).toHaveBeenCalledWith(error, {
      tags: { feature: "Readiness", operation: "fetch_report" },
      contexts: expect.objectContaining({
        readiness: expect.objectContaining({
          run_id: "run-1",
          duration_ms: 3000,
        }),
      }),
    });
  });

  it("fetchFailure handles non-Error values", () => {
    readinessLogger.fetchFailure("run-1", "string-error", 100);

    expect(consoleSpy.error).toHaveBeenCalledWith(
      expect.any(String),
      expect.objectContaining({ error: "string-error" }),
    );
  });

  it("fetchRetry emits warn log with attempt and delay", () => {
    readinessLogger.fetchRetry("run-1", 2, 3, 2500);

    expect(consoleSpy.warn).toHaveBeenCalledWith(
      "[Readiness] Retrying readiness fetch (attempt 2 of 3)",
      expect.objectContaining({
        operation: "readiness.fetch_report",
        run_id: "run-1",
        attempt: 2,
        max_retries: 3,
        delay_ms: 2500,
      }),
    );
  });

  it("fetchRetry adds Sentry breadcrumb at warning level", () => {
    readinessLogger.fetchRetry("run-1", 1, 3, 1000);

    expect(mockAddBreadcrumb).toHaveBeenCalledWith(
      expect.objectContaining({
        category: "readiness",
        level: "warning",
      }),
    );
  });
});

// ---------------------------------------------------------------------------
// Generate lifecycle
// ---------------------------------------------------------------------------

describe("readinessLogger — generate lifecycle", () => {
  it("generateStart emits info log", () => {
    readinessLogger.generateStart("run-2");

    expect(consoleSpy.info).toHaveBeenCalledWith(
      "[Readiness] Generating readiness report",
      expect.objectContaining({
        operation: "readiness.generate_report",
        component: "readinessApi",
        run_id: "run-2",
      }),
    );
  });

  it("generateSuccess emits info log with grade", () => {
    readinessLogger.generateSuccess("run-2", 500, "A");

    expect(consoleSpy.info).toHaveBeenCalledWith(
      "[Readiness] Readiness report generated successfully",
      expect.objectContaining({
        operation: "readiness.generate_report",
        result: "success",
        run_id: "run-2",
        duration_ms: 500,
        grade: "A",
      }),
    );
  });

  it("generateFailure captures Sentry exception", () => {
    const error = new Error("Server error");
    readinessLogger.generateFailure("run-2", error, 1200);

    expect(mockCaptureException).toHaveBeenCalledWith(error, {
      tags: { feature: "Readiness", operation: "generate_report" },
      contexts: expect.objectContaining({
        readiness: { run_id: "run-2", duration_ms: 1200 },
      }),
    });
  });
});

// ---------------------------------------------------------------------------
// Promotion lifecycle
// ---------------------------------------------------------------------------

describe("readinessLogger — promotion lifecycle", () => {
  it("promotionStart emits info log", () => {
    readinessLogger.promotionStart("run-3");

    expect(consoleSpy.info).toHaveBeenCalledWith(
      "[Readiness] Submitting for promotion",
      expect.objectContaining({
        operation: "readiness.submit_promotion",
        run_id: "run-3",
      }),
    );
  });

  it("promotionSuccess emits info log with duration", () => {
    readinessLogger.promotionSuccess("run-3", 250);

    expect(consoleSpy.info).toHaveBeenCalledWith(
      "[Readiness] Promotion submitted successfully",
      expect.objectContaining({
        result: "success",
        duration_ms: 250,
      }),
    );
  });

  it("promotionFailure captures Sentry exception", () => {
    const error = new Error("403");
    readinessLogger.promotionFailure("run-3", error, 100);

    expect(mockCaptureException).toHaveBeenCalledWith(error, {
      tags: { feature: "Readiness", operation: "submit_promotion" },
      contexts: expect.objectContaining({
        readiness: { run_id: "run-3", duration_ms: 100 },
      }),
    });
  });
});

// ---------------------------------------------------------------------------
// Validation
// ---------------------------------------------------------------------------

describe("readinessLogger — validation", () => {
  it("validationFailure emits warn log with error count", () => {
    const issues = [
      { code: "custom", path: ["grade"], message: "Required" },
      { code: "custom", path: ["score"], message: "Expected number" },
    ];

    readinessLogger.validationFailure("run-4", issues);

    expect(consoleSpy.warn).toHaveBeenCalledWith(
      "[Readiness] Readiness report response failed schema validation (2 issue(s))",
      expect.objectContaining({
        operation: "readiness.fetch_report",
        result: "failure",
        run_id: "run-4",
        validation_error_count: 2,
      }),
    );
  });

  it("validationFailure captures Sentry exception with error count", () => {
    const issues = [{ code: "custom", path: ["grade"], message: "Required" }];

    readinessLogger.validationFailure("run-4", issues);

    expect(mockCaptureException).toHaveBeenCalledWith(
      expect.any(Error),
      expect.objectContaining({
        tags: { feature: "Readiness", operation: "schema_validation" },
        contexts: {
          readiness: { run_id: "run-4", error_count: 1 },
        },
      }),
    );
  });

  it("validationFailure handles non-array errors (counts as 1)", () => {
    readinessLogger.validationFailure("run-4", "single-error");

    expect(consoleSpy.warn).toHaveBeenCalledWith(
      expect.stringContaining("1 issue(s)"),
      expect.objectContaining({ validation_error_count: 1 }),
    );
  });
});

// ---------------------------------------------------------------------------
// Page lifecycle
// ---------------------------------------------------------------------------

describe("readinessLogger — page lifecycle", () => {
  it("pageMount emits info log", () => {
    readinessLogger.pageMount("run-5");

    expect(consoleSpy.info).toHaveBeenCalledWith(
      "[Readiness] Readiness page mounted",
      expect.objectContaining({
        operation: "readiness.render_page",
        component: "RunReadinessPage",
        run_id: "run-5",
      }),
    );
  });

  it("pageUnmount emits debug log", () => {
    readinessLogger.pageUnmount("run-5");

    expect(consoleSpy.debug).toHaveBeenCalledWith(
      "[Readiness] Readiness page unmounting",
      expect.objectContaining({
        operation: "readiness.render_page",
        component: "RunReadinessPage",
        run_id: "run-5",
      }),
    );
  });
});

// ---------------------------------------------------------------------------
// Sentry breadcrumb level mapping
// ---------------------------------------------------------------------------

describe("readinessLogger — Sentry breadcrumb level mapping", () => {
  it("maps info level to info breadcrumb", () => {
    readinessLogger.fetchStart("run-1");

    expect(mockAddBreadcrumb).toHaveBeenCalledWith(expect.objectContaining({ level: "info" }));
  });

  it("maps warn level to warning breadcrumb", () => {
    readinessLogger.fetchRetry("run-1", 1, 3, 1000);

    expect(mockAddBreadcrumb).toHaveBeenCalledWith(expect.objectContaining({ level: "warning" }));
  });

  it("maps error level to error breadcrumb", () => {
    readinessLogger.fetchFailure("run-1", new Error("fail"), 100);

    expect(mockAddBreadcrumb).toHaveBeenCalledWith(expect.objectContaining({ level: "error" }));
  });

  it("maps debug level to debug breadcrumb", () => {
    readinessLogger.pageUnmount("run-1");

    expect(mockAddBreadcrumb).toHaveBeenCalledWith(expect.objectContaining({ level: "debug" }));
  });
});
