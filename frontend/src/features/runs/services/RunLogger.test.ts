/**
 * Tests for RunLogger — structured logging for run monitor events.
 *
 * Verifies CLAUDE.md §8 requirements: structured fields, correlation IDs,
 * component identification, duration tracking, and log level correctness.
 */

import { describe, it, expect, vi, beforeEach, afterEach } from "vitest";

// Mock apiClient before importing RunLogger
vi.mock("@/api/client", () => ({
  apiClient: {
    post: vi.fn().mockResolvedValue({ data: {} }),
  },
}));

import { RunLogger } from "./RunLogger";
import { apiClient } from "@/api/client";

describe("RunLogger", () => {
  let logger: RunLogger;

  beforeEach(() => {
    vi.clearAllMocks();
    logger = new RunLogger("test-correlation-id");
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  it("creates logger with provided correlation ID", () => {
    const lg = new RunLogger("custom-id");
    expect(lg.correlationId).toBe("custom-id");
  });

  it("generates correlation ID when none provided", () => {
    vi.stubGlobal("crypto", { randomUUID: () => "generated-uuid" });
    const lg = new RunLogger();
    expect(lg.correlationId).toBe("generated-uuid");
    vi.unstubAllGlobals();
  });

  it("logs poll started event with required structured fields", async () => {
    await logger.logPollStarted("01HZ0000000000000000000001", 2000);

    expect(apiClient.post).toHaveBeenCalledTimes(1);
    const [url, payload] = (apiClient.post as ReturnType<typeof vi.fn>).mock.calls[0];
    expect(url).toBe("/audit/events");
    expect(payload.event).toBe("run.poll_started");
    expect(payload.correlationId).toBe("test-correlation-id");
    expect(payload.metadata.operation).toBe("run_poll_started");
    expect(payload.metadata.component).toBe("RunMonitor");
    expect(payload.metadata.run_id).toBe("01HZ0000000000000000000001");
    expect(payload.metadata.interval_ms).toBe(2000);
    expect(payload.timestamp).toBeDefined();
  });

  it("logs poll succeeded event with duration", async () => {
    await logger.logPollSucceeded("01HZ0000000000000000000001", "running", 150);

    const [, payload] = (apiClient.post as ReturnType<typeof vi.fn>).mock.calls[0];
    expect(payload.event).toBe("run.poll_succeeded");
    expect(payload.metadata.result).toBe("success");
    expect(payload.metadata.run_status).toBe("running");
    expect(payload.metadata.duration_ms).toBe(150);
  });

  it("logs poll failed event with error details", async () => {
    await logger.logPollFailed("01HZ0000000000000000000001", new Error("Network timeout"), 500, 3);

    const [, payload] = (apiClient.post as ReturnType<typeof vi.fn>).mock.calls[0];
    expect(payload.event).toBe("run.poll_failed");
    expect(payload.metadata.result).toBe("failure");
    expect(payload.metadata.error_message).toBe("Network timeout");
    expect(payload.metadata.http_status).toBe(500);
    expect(payload.metadata.retry_count).toBe(3);
  });

  it("logs terminal status reached event", async () => {
    await logger.logTerminalReached("01HZ0000000000000000000001", "complete", 45_000);

    const [, payload] = (apiClient.post as ReturnType<typeof vi.fn>).mock.calls[0];
    expect(payload.event).toBe("run.terminal_reached");
    expect(payload.metadata.run_status).toBe("complete");
    expect(payload.metadata.total_poll_duration_ms).toBe(45_000);
  });

  it("logs submission started event", async () => {
    await logger.logSubmissionStarted("optimization", "01HZ0000000000000000000002");

    const [, payload] = (apiClient.post as ReturnType<typeof vi.fn>).mock.calls[0];
    expect(payload.event).toBe("run.submission_started");
    expect(payload.metadata.run_type).toBe("optimization");
    expect(payload.metadata.strategy_build_id).toBe("01HZ0000000000000000000002");
  });

  it("logs submission succeeded event", async () => {
    await logger.logSubmissionSucceeded("01HZ0000000000000000000001", "research", 350);

    const [, payload] = (apiClient.post as ReturnType<typeof vi.fn>).mock.calls[0];
    expect(payload.event).toBe("run.submission_succeeded");
    expect(payload.metadata.result).toBe("success");
    expect(payload.metadata.run_id).toBe("01HZ0000000000000000000001");
    expect(payload.metadata.duration_ms).toBe(350);
  });

  it("logs submission failed event", async () => {
    await logger.logSubmissionFailed("optimization", new Error("422 Validation Error"), 800);

    const [, payload] = (apiClient.post as ReturnType<typeof vi.fn>).mock.calls[0];
    expect(payload.event).toBe("run.submission_failed");
    expect(payload.metadata.result).toBe("failure");
    expect(payload.metadata.error_message).toBe("422 Validation Error");
  });

  it("logs cancellation event", async () => {
    await logger.logCancellation("01HZ0000000000000000000001", "User requested");

    const [, payload] = (apiClient.post as ReturnType<typeof vi.fn>).mock.calls[0];
    expect(payload.event).toBe("run.cancellation_requested");
    expect(payload.metadata.reason).toBe("User requested");
  });

  it("logs cancellation failed event", async () => {
    await logger.logCancellationFailed(
      "01HZ0000000000000000000001",
      new Error("Connection refused"),
    );

    const [, payload] = (apiClient.post as ReturnType<typeof vi.fn>).mock.calls[0];
    expect(payload.event).toBe("run.cancellation_failed");
    expect(payload.metadata.operation).toBe("run_cancellation_failed");
    expect(payload.metadata.component).toBe("RunMonitor");
    expect(payload.metadata.result).toBe("failure");
    expect(payload.metadata.run_id).toBe("01HZ0000000000000000000001");
    expect(payload.metadata.error_message).toBe("Connection refused");
  });

  it("logs stale data detected event", async () => {
    await logger.logStaleDetected("01HZ0000000000000000000001", 7500);

    const [, payload] = (apiClient.post as ReturnType<typeof vi.fn>).mock.calls[0];
    expect(payload.event).toBe("run.stale_detected");
    expect(payload.metadata.elapsed_since_success_ms).toBe(7500);
  });

  it("never throws on logging failure (fire-and-forget)", async () => {
    (apiClient.post as ReturnType<typeof vi.fn>).mockRejectedValue(new Error("Network down"));

    // Should not throw
    await expect(
      logger.logPollStarted("01HZ0000000000000000000001", 2000),
    ).resolves.toBeUndefined();
  });

  it("includes ISO-8601 timestamp in all events", async () => {
    await logger.logPollStarted("01HZ0000000000000000000001", 2000);

    const [, payload] = (apiClient.post as ReturnType<typeof vi.fn>).mock.calls[0];
    // Verify it's a valid ISO timestamp
    expect(new Date(payload.timestamp).toISOString()).toBe(payload.timestamp);
  });
});
