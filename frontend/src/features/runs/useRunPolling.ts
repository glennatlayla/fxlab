/**
 * useRunPolling — Exponential-backoff polling hook for run status monitoring.
 *
 * Purpose:
 *   Poll GET /runs/{run_id} with exponential backoff (§8.1) and expose
 *   the latest RunRecord, loading state, error state, and stale-data
 *   indicator to the RunPage component tree.
 *
 * Responsibilities:
 *   - Start polling on mount with INITIAL_POLL_INTERVAL_MS (2s).
 *   - Delegate backoff calculation, terminal detection, and stale checks
 *     to RunMonitorService (§4 onion architecture — business logic in service layer).
 *   - Fire structured log events via RunLogger (§8).
 *   - Stop polling when run reaches a terminal status (complete/failed/cancelled).
 *   - Track time since last successful poll; set isStale when it exceeds
 *     STALE_INDICATOR_THRESHOLD_MS (5s) after a poll failure.
 *   - Reset backoff interval on manual refresh.
 *   - Guard all state updates with isMountedRef to prevent memory leaks.
 *   - Clear pending timeouts before scheduling new ones (race condition fix).
 *
 * Does NOT:
 *   - Contain business logic (delegated to RunMonitorService).
 *   - Manage run submission (see useRunSubmission).
 *   - Handle trial list fetching (see separate query in RunPage).
 *
 * Dependencies:
 *   - runsApi.getRunStatus for HTTP calls (repository layer).
 *   - RunMonitorService for business logic (service layer).
 *   - RunLogger for structured logging (infrastructure layer).
 *   - @/types/run for RunRecord type and polling constants.
 *
 * Error conditions:
 *   - Network failure → sets error, increments backoff, sets isStale after threshold.
 *   - 404 → sets error, stops polling (run does not exist).
 *   - Zod validation failure → sets error, increments backoff.
 *
 * Example:
 *   const { run, isLoading, isStale, error, refresh } = useRunPolling(runId);
 *   if (isStale) showStaleIndicator(run.updated_at);
 *   if (run?.status === "complete") navigateToResults(run.result_uri);
 */

import { useState, useEffect, useRef, useCallback } from "react";
import type { RunRecord } from "@/types/run";
import {
  INITIAL_POLL_INTERVAL_MS,
  MAX_POLL_INTERVAL_MS,
  POLL_BACKOFF_MULTIPLIER,
  STALE_INDICATOR_THRESHOLD_MS,
} from "@/types/run";
import { runsApi } from "./api";
import { calculateNextInterval, isTerminalStatus, isStaleData } from "./services/RunMonitorService";
import { RunLogger } from "./services/RunLogger";

// ---------------------------------------------------------------------------
// Hook return type
// ---------------------------------------------------------------------------

/** Return value of useRunPolling hook. */
export interface UseRunPollingResult {
  /** Current run record from the latest successful poll (null before first fetch). */
  run: RunRecord | null;
  /** True during the initial fetch before any data is available. */
  isLoading: boolean;
  /** True when the last poll failed and elapsed time since last success exceeds threshold. */
  isStale: boolean;
  /** Error from the most recent failed poll (null if last poll succeeded). */
  error: Error | null;
  /** ISO-8601 timestamp of the last successful poll (null before first success). */
  lastUpdatedAt: string | null;
  /** Trigger an immediate poll and reset the backoff interval. */
  refresh: () => void;
  /** True when the run has reached a terminal status and polling has stopped. */
  isTerminal: boolean;
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/**
 * Extract HTTP status code from an axios-style error object.
 *
 * Args:
 *   err: Unknown error from a catch block.
 *
 * Returns:
 *   HTTP status code or undefined if not available.
 */
function extractHttpStatus(err: unknown): number | undefined {
  if (
    typeof err === "object" &&
    err !== null &&
    "response" in err &&
    typeof (err as { response?: { status?: number } }).response?.status === "number"
  ) {
    return (err as { response: { status: number } }).response.status;
  }
  return undefined;
}

// ---------------------------------------------------------------------------
// Hook implementation
// ---------------------------------------------------------------------------

/**
 * Poll run status with exponential backoff per spec §8.1.
 *
 * Args:
 *   runId: ULID of the run to poll. Pass null/undefined to disable polling.
 *
 * Returns:
 *   UseRunPollingResult with run data, loading/stale/error states, and refresh.
 */
export function useRunPolling(runId: string | null | undefined): UseRunPollingResult {
  const [run, setRun] = useState<RunRecord | null>(null);
  const [isLoading, setIsLoading] = useState<boolean>(true);
  const [error, setError] = useState<Error | null>(null);
  const [lastUpdatedAt, setLastUpdatedAt] = useState<string | null>(null);
  const [isStale, setIsStale] = useState<boolean>(false);
  const [isTerminal, setIsTerminal] = useState<boolean>(false);

  // Refs for managing polling lifecycle without triggering re-renders
  const timeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const currentIntervalMs = useRef<number>(INITIAL_POLL_INTERVAL_MS);
  const lastSuccessTimestamp = useRef<number | null>(null);
  const staleCheckRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const isMountedRef = useRef<boolean>(true);
  const pollStartTimeRef = useRef<number | null>(null);
  const errorRef = useRef<Error | null>(null);
  const loggerRef = useRef<RunLogger>(new RunLogger());

  /**
   * Clear any pending poll timeout.
   * Called before scheduling a new timeout and on unmount to prevent leaks.
   */
  const clearPendingTimeout = useCallback(() => {
    if (timeoutRef.current !== null) {
      clearTimeout(timeoutRef.current);
      timeoutRef.current = null;
    }
  }, []);

  /**
   * Schedule the next poll with current backoff interval.
   * Guards against scheduling after unmount (race condition fix).
   *
   * Args:
   *   pollFn: The poll function to schedule.
   */
  const scheduleNextPoll = useCallback(
    // eslint-disable-next-line @typescript-eslint/no-explicit-any -- generic poll fn
    (pollFn: () => void) => {
      // Race condition guard: don't schedule if component unmounted
      if (!isMountedRef.current) return;

      // Clear any existing timeout before scheduling (prevents double-scheduling)
      clearPendingTimeout();

      currentIntervalMs.current = calculateNextInterval(
        currentIntervalMs.current,
        POLL_BACKOFF_MULTIPLIER,
        MAX_POLL_INTERVAL_MS,
      );

      timeoutRef.current = setTimeout(pollFn, currentIntervalMs.current);
    },
    [clearPendingTimeout],
  );

  /**
   * Execute a single poll cycle.
   *
   * Fetches run status, updates state, and schedules the next poll
   * with appropriate backoff. Handles errors by incrementing the
   * backoff interval and checking stale threshold.
   */
  const poll = useCallback(async () => {
    if (!runId) return;

    const cycleStart = Date.now();

    try {
      const data = await runsApi.getRunStatus(runId);

      // Guard against state updates after unmount
      if (!isMountedRef.current) return;

      setRun(data);
      setError(null);
      errorRef.current = null;
      setIsLoading(false);
      setIsStale(false);

      const now = new Date().toISOString();
      setLastUpdatedAt(now);
      lastSuccessTimestamp.current = Date.now();

      // Structured logging: poll succeeded (fire-and-forget)
      loggerRef.current.logPollSucceeded(runId, data.status, Date.now() - cycleStart);

      // Check for terminal status — stop polling if reached
      if (isTerminalStatus(data.status)) {
        setIsTerminal(true);
        // Log terminal reached with total poll duration
        if (pollStartTimeRef.current !== null) {
          loggerRef.current.logTerminalReached(
            runId,
            data.status,
            Date.now() - pollStartTimeRef.current,
          );
        }
        return; // Do not schedule next poll
      }

      // Schedule next poll with backoff (via service layer calculation)
      scheduleNextPoll(poll);
    } catch (err) {
      // Guard against state updates after unmount
      if (!isMountedRef.current) return;

      const pollError = err instanceof Error ? err : new Error(String(err));
      const httpStatus = extractHttpStatus(err);

      setError(pollError);
      errorRef.current = pollError;
      setIsLoading(false);

      // Structured logging: poll failed (fire-and-forget)
      loggerRef.current.logPollFailed(runId, pollError, httpStatus, 0);

      // On 404, stop polling — run does not exist
      if (httpStatus === 404) {
        setIsTerminal(true);
        return;
      }

      // Backoff on failure and schedule retry
      scheduleNextPoll(poll);
    }
  }, [runId, scheduleNextPoll]);

  /**
   * Trigger an immediate poll and reset the backoff interval.
   * Called by the user via the "Refresh" button.
   */
  const refresh = useCallback(() => {
    // Clear any pending scheduled poll
    clearPendingTimeout();

    // Reset backoff to initial interval
    currentIntervalMs.current = INITIAL_POLL_INTERVAL_MS;
    setIsStale(false);
    setError(null);
    errorRef.current = null;

    // If already terminal, allow re-poll (user explicitly asked)
    if (isTerminal) {
      setIsTerminal(false);
    }

    // Execute immediately
    poll();
  }, [poll, isTerminal, clearPendingTimeout]);

  // ---------------------------------------------------------------------------
  // Stale data checker — runs on a fixed 1s interval to check elapsed time
  // Uses service layer isStaleData() for the business logic decision.
  // ---------------------------------------------------------------------------

  useEffect(() => {
    staleCheckRef.current = setInterval(() => {
      if (!isMountedRef.current) return;

      // Read error from ref (not state) to avoid re-creating the interval
      // on every error toggle. This keeps the 1-second rhythm stable.
      const stale = isStaleData(
        lastSuccessTimestamp.current,
        errorRef.current !== null,
        STALE_INDICATOR_THRESHOLD_MS,
      );

      if (stale) {
        setIsStale(true);

        // Log stale detection once per transition
        if (runId && lastSuccessTimestamp.current !== null) {
          loggerRef.current.logStaleDetected(runId, Date.now() - lastSuccessTimestamp.current);
        }
      }
    }, 1_000);

    return () => {
      if (staleCheckRef.current) {
        clearInterval(staleCheckRef.current);
        staleCheckRef.current = null;
      }
    };
  }, [runId]);

  // ---------------------------------------------------------------------------
  // Main polling lifecycle
  // ---------------------------------------------------------------------------

  useEffect(() => {
    isMountedRef.current = true;

    if (!runId) {
      setIsLoading(false);
      return;
    }

    // Reset state for new run ID
    setRun(null);
    setIsLoading(true);
    setError(null);
    errorRef.current = null;
    setIsStale(false);
    setIsTerminal(false);
    currentIntervalMs.current = INITIAL_POLL_INTERVAL_MS;
    lastSuccessTimestamp.current = null;
    pollStartTimeRef.current = Date.now();

    // Create fresh logger for this polling session
    loggerRef.current = new RunLogger();

    // Start initial poll
    poll();

    return () => {
      // Set unmounted flag FIRST to guard in-flight callbacks
      isMountedRef.current = false;

      // Then clear pending timeouts
      clearPendingTimeout();
    };
  }, [runId, poll, clearPendingTimeout]);

  return {
    run,
    isLoading,
    isStale,
    error,
    lastUpdatedAt,
    refresh,
    isTerminal,
  };
}
