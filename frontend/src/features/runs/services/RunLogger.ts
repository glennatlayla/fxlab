/**
 * RunLogger — structured logging for run monitor events.
 *
 * Purpose:
 *   Provide structured, fire-and-forget logging for all run lifecycle
 *   events per CLAUDE.md §8. Each log event includes correlation ID,
 *   component identifier, operation name, duration, and result status.
 *
 * Responsibilities:
 *   - Emit structured log events for poll, submission, and cancellation lifecycle.
 *   - Propagate correlation ID from entry point through all log events.
 *   - Never block user actions (fire-and-forget, non-throwing).
 *   - Gracefully degrade on logging failures.
 *
 * Does NOT:
 *   - Log secrets, PII, or credentials (see §8 rules).
 *   - Replace server-side logging (defense in depth).
 *   - Queue events on failure (best-effort only).
 *   - Contain business logic.
 *
 * Dependencies:
 *   - @/api/client: Pre-configured Axios instance with auth injection.
 *
 * Error conditions:
 *   Never throws. All errors are caught and logged to console.warn.
 *
 * Example:
 *   const logger = new RunLogger();
 *   await logger.logPollStarted(runId, intervalMs);
 *   await logger.logPollSucceeded(runId, "running", 150);
 */

import { apiClient } from "@/api/client";

// ---------------------------------------------------------------------------
// Event types
// ---------------------------------------------------------------------------

/**
 * Run lifecycle event types.
 *
 * Categories:
 *   - run.poll_*: Polling lifecycle events (§8 table: external call events)
 *   - run.submission_*: Submission lifecycle events
 *   - run.cancellation_*: Cancellation events
 *   - run.terminal_*: Terminal status reached
 *   - run.stale_*: Stale data detection
 */
export type RunLogEventType =
  | "run.poll_started"
  | "run.poll_succeeded"
  | "run.poll_failed"
  | "run.terminal_reached"
  | "run.submission_started"
  | "run.submission_succeeded"
  | "run.submission_failed"
  | "run.cancellation_requested"
  | "run.cancellation_failed"
  | "run.stale_detected";

/**
 * Structured log event payload sent to the backend.
 *
 * Follows the required structured fields from CLAUDE.md §8:
 * operation, correlation_id, component, duration_ms, result.
 */
export interface RunLogEvent {
  /** Event type identifier. */
  event: RunLogEventType;
  /** Actor is "system" for automated events, user ID for user-initiated. */
  actor: string;
  /** ISO 8601 timestamp. */
  timestamp: string;
  /** Correlation ID for distributed tracing. */
  correlationId: string;
  /** Structured metadata with required §8 fields. */
  metadata: {
    /** snake_case operation name. */
    operation: string;
    /** Component or module name. */
    component: string;
    /** Result status. */
    result?: "success" | "failure" | "partial";
    /** Duration in milliseconds for timed operations. */
    duration_ms?: number;
    /** Additional domain-specific fields. */
    [key: string]: unknown;
  };
}

// ---------------------------------------------------------------------------
// Logger class
// ---------------------------------------------------------------------------

/**
 * Structured logger for run monitor events.
 *
 * Instantiate with a correlation ID to link all events in a polling session.
 * Each method is fire-and-forget: it sends the event to the audit endpoint
 * and resolves even on failure.
 *
 * Example:
 *   const logger = new RunLogger("session-uuid");
 *   await logger.logPollStarted(runId, 2000);
 */
export class RunLogger {
  /** Correlation ID propagated across all events in this session. */
  public readonly correlationId: string;

  /**
   * Create a new RunLogger.
   *
   * Args:
   *   correlationId: UUID for distributed tracing. Auto-generated if omitted.
   */
  constructor(correlationId?: string) {
    this.correlationId = correlationId ?? crypto.randomUUID();
  }

  // ── Polling events ──────────────────────────────────────────────────

  /**
   * Log that a poll cycle has started.
   *
   * Args:
   *   runId: ULID of the run being polled.
   *   intervalMs: Current polling interval in milliseconds.
   */
  async logPollStarted(runId: string, intervalMs: number): Promise<void> {
    await this.emit({
      event: "run.poll_started",
      actor: "system",
      metadata: {
        operation: "run_poll_started",
        component: "RunMonitor",
        run_id: runId,
        interval_ms: intervalMs,
      },
    });
  }

  /**
   * Log that a poll cycle succeeded.
   *
   * Args:
   *   runId: ULID of the run.
   *   runStatus: Current status after poll.
   *   durationMs: Time taken for the API call in milliseconds.
   */
  async logPollSucceeded(runId: string, runStatus: string, durationMs: number): Promise<void> {
    await this.emit({
      event: "run.poll_succeeded",
      actor: "system",
      metadata: {
        operation: "run_poll_succeeded",
        component: "RunMonitor",
        result: "success",
        run_id: runId,
        run_status: runStatus,
        duration_ms: durationMs,
      },
    });
  }

  /**
   * Log that a poll cycle failed.
   *
   * Args:
   *   runId: ULID of the run.
   *   error: Error from the failed poll.
   *   httpStatus: HTTP status code (if available).
   *   retryCount: Number of consecutive failures.
   */
  async logPollFailed(
    runId: string,
    error: Error,
    httpStatus: number | undefined,
    retryCount: number,
  ): Promise<void> {
    await this.emit({
      event: "run.poll_failed",
      actor: "system",
      metadata: {
        operation: "run_poll_failed",
        component: "RunMonitor",
        result: "failure",
        run_id: runId,
        error_message: error.message,
        http_status: httpStatus,
        retry_count: retryCount,
      },
    });
  }

  /**
   * Log that a run reached a terminal status and polling stopped.
   *
   * Args:
   *   runId: ULID of the run.
   *   finalStatus: Terminal status (complete/failed/cancelled).
   *   totalPollDurationMs: Total time spent polling from first poll to terminal.
   */
  async logTerminalReached(
    runId: string,
    finalStatus: string,
    totalPollDurationMs: number,
  ): Promise<void> {
    await this.emit({
      event: "run.terminal_reached",
      actor: "system",
      metadata: {
        operation: "run_terminal_reached",
        component: "RunMonitor",
        result: "success",
        run_id: runId,
        run_status: finalStatus,
        total_poll_duration_ms: totalPollDurationMs,
      },
    });
  }

  // ── Submission events ───────────────────────────────────────────────

  /**
   * Log that a run submission was initiated.
   *
   * Args:
   *   runType: "research" or "optimization".
   *   strategyBuildId: ULID of the strategy build.
   */
  async logSubmissionStarted(runType: string, strategyBuildId: string): Promise<void> {
    await this.emit({
      event: "run.submission_started",
      actor: "system",
      metadata: {
        operation: "run_submission_started",
        component: "RunMonitor",
        run_type: runType,
        strategy_build_id: strategyBuildId,
      },
    });
  }

  /**
   * Log that a run submission succeeded.
   *
   * Args:
   *   runId: ULID of the created run.
   *   runType: "research" or "optimization".
   *   durationMs: Time taken for the submission API call.
   */
  async logSubmissionSucceeded(runId: string, runType: string, durationMs: number): Promise<void> {
    await this.emit({
      event: "run.submission_succeeded",
      actor: "system",
      metadata: {
        operation: "run_submission_succeeded",
        component: "RunMonitor",
        result: "success",
        run_id: runId,
        run_type: runType,
        duration_ms: durationMs,
      },
    });
  }

  /**
   * Log that a run submission failed.
   *
   * Args:
   *   runType: "research" or "optimization".
   *   error: Error from the failed submission.
   *   durationMs: Time taken before failure.
   */
  async logSubmissionFailed(runType: string, error: Error, durationMs: number): Promise<void> {
    await this.emit({
      event: "run.submission_failed",
      actor: "system",
      metadata: {
        operation: "run_submission_failed",
        component: "RunMonitor",
        result: "failure",
        run_type: runType,
        error_message: error.message,
        duration_ms: durationMs,
      },
    });
  }

  // ── Cancellation events ─────────────────────────────────────────────

  /**
   * Log that a run cancellation was requested.
   *
   * Args:
   *   runId: ULID of the run to cancel.
   *   reason: Cancellation reason.
   */
  async logCancellation(runId: string, reason: string): Promise<void> {
    await this.emit({
      event: "run.cancellation_requested",
      actor: "system",
      metadata: {
        operation: "run_cancellation_requested",
        component: "RunMonitor",
        run_id: runId,
        reason,
      },
    });
  }

  /**
   * Log that a run cancellation failed.
   *
   * Args:
   *   runId: ULID of the run.
   *   error: Error from the failed cancellation.
   */
  async logCancellationFailed(runId: string, error: Error): Promise<void> {
    await this.emit({
      event: "run.cancellation_failed",
      actor: "system",
      metadata: {
        operation: "run_cancellation_failed",
        component: "RunMonitor",
        result: "failure",
        run_id: runId,
        error_message: error.message,
      },
    });
  }

  // ── Stale data events ───────────────────────────────────────────────

  /**
   * Log that stale data was detected.
   *
   * Args:
   *   runId: ULID of the run.
   *   elapsedSinceSuccessMs: Time since last successful poll in ms.
   */
  async logStaleDetected(runId: string, elapsedSinceSuccessMs: number): Promise<void> {
    await this.emit({
      event: "run.stale_detected",
      actor: "system",
      metadata: {
        operation: "run_stale_detected",
        component: "RunMonitor",
        run_id: runId,
        elapsed_since_success_ms: elapsedSinceSuccessMs,
      },
    });
  }

  // ── Internal emit ───────────────────────────────────────────────────

  /**
   * Fire-and-forget event emission.
   *
   * Adds timestamp and correlation ID, posts to audit endpoint.
   * Never throws — all errors are caught and logged locally.
   *
   * Args:
   *   partial: Event without timestamp and correlationId (added here).
   */
  private async emit(partial: Omit<RunLogEvent, "timestamp" | "correlationId">): Promise<void> {
    const event: RunLogEvent = {
      ...partial,
      timestamp: new Date().toISOString(),
      correlationId: this.correlationId,
    };

    try {
      await apiClient.post("/audit/events", event);
    } catch (error) {
      // Fire-and-forget: log locally but never block user flow (§8 rule).
      console.warn("[RunLogger] Failed to send event", {
        event: event.event,
        error: error instanceof Error ? error.message : String(error),
      });
    }
  }
}
