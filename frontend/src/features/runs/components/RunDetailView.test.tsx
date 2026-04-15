/**
 * Tests for RunDetailView component.
 *
 * Verifies the main orchestration component wires together polling,
 * sub-components, and service layer correctly. Tests loading, error,
 * terminal states, URI validation, safe date parsing, and metrics memoization.
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { RunDetailView } from "./RunDetailView";
import type { RunRecord } from "@/types/run";

// ---------------------------------------------------------------------------
// Mock dependencies
// ---------------------------------------------------------------------------

const mockRefresh = vi.fn();
const mockPollingResult = {
  run: null as RunRecord | null,
  isLoading: true,
  isStale: false,
  error: null as Error | null,
  lastUpdatedAt: null as string | null,
  refresh: mockRefresh,
  isTerminal: false,
};

vi.mock("../useRunPolling", () => ({
  useRunPolling: () => mockPollingResult,
}));

vi.mock("../api", () => ({
  runsApi: {
    cancelRun: vi.fn().mockResolvedValue({}),
  },
}));

vi.mock("../services/RunLogger", () => ({
  RunLogger: vi.fn().mockImplementation(() => ({
    logCancellation: vi.fn(),
  })),
}));

vi.mock("react-router-dom", () => ({
  useNavigate: () => vi.fn(),
}));

vi.mock("@/hooks/useMediaQuery", () => ({
  useIsMobile: () => false,
  useIsDesktop: () => true,
}));

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function makeRun(overrides: Partial<RunRecord> = {}): RunRecord {
  return {
    id: "01HZ0000000000000000000001",
    strategy_build_id: "01HZ0000000000000000000002",
    run_type: "research",
    status: "running",
    config: {},
    result_uri: null,
    created_by: "user-001",
    created_at: "2026-04-04T10:00:00Z",
    updated_at: "2026-04-04T10:05:00Z",
    started_at: "2026-04-04T10:01:00Z",
    completed_at: null,
    ...overrides,
  };
}

function setPollingState(overrides: Partial<typeof mockPollingResult>) {
  Object.assign(mockPollingResult, overrides);
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("RunDetailView", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    // Reset to default loading state
    Object.assign(mockPollingResult, {
      run: null,
      isLoading: true,
      isStale: false,
      error: null,
      lastUpdatedAt: null,
      refresh: mockRefresh,
      isTerminal: false,
    });
  });

  // ── Loading state ─────────────────────────────────────────────────

  it("renders loading spinner when isLoading is true", () => {
    setPollingState({ isLoading: true, run: null });
    render(<RunDetailView runId="01HZ0000000000000000000001" />);

    expect(screen.getByTestId("run-loading")).toBeInTheDocument();
  });

  // ── Error state ───────────────────────────────────────────────────

  it("renders error message when error is present and no run data", () => {
    setPollingState({
      isLoading: false,
      run: null,
      error: new Error("Network failure"),
    });
    render(<RunDetailView runId="01HZ0000000000000000000001" />);

    expect(screen.getByTestId("run-error")).toBeInTheDocument();
    expect(screen.getByText("Network failure")).toBeInTheDocument();
  });

  it("renders retry button in error state that calls refresh", () => {
    setPollingState({
      isLoading: false,
      run: null,
      error: new Error("Timeout"),
    });
    render(<RunDetailView runId="01HZ0000000000000000000001" />);

    fireEvent.click(screen.getByText("Retry"));
    expect(mockRefresh).toHaveBeenCalledTimes(1);
  });

  // ── Normal running state ──────────────────────────────────────────

  it("renders run detail view with status badge when run is loaded", () => {
    setPollingState({ isLoading: false, run: makeRun() });
    render(<RunDetailView runId="01HZ0000000000000000000001" />);

    expect(screen.getByTestId("run-detail-view")).toBeInTheDocument();
    expect(screen.getByText(/Run 01HZ0000/)).toBeInTheDocument();
  });

  it("renders refresh button that calls refresh", () => {
    setPollingState({ isLoading: false, run: makeRun() });
    render(<RunDetailView runId="01HZ0000000000000000000001" />);

    fireEvent.click(screen.getByTestId("refresh-button"));
    expect(mockRefresh).toHaveBeenCalledTimes(1);
  });

  it("renders cancel button for non-terminal runs", () => {
    setPollingState({ isLoading: false, run: makeRun({ status: "running" }) });
    render(<RunDetailView runId="01HZ0000000000000000000001" />);

    expect(screen.getByTestId("cancel-button")).toBeInTheDocument();
  });

  it("hides cancel button for terminal runs", () => {
    setPollingState({
      isLoading: false,
      run: makeRun({ status: "complete" }),
      isTerminal: true,
    });
    render(<RunDetailView runId="01HZ0000000000000000000001" />);

    expect(screen.queryByTestId("cancel-button")).not.toBeInTheDocument();
  });

  // ── Stale data indicator ──────────────────────────────────────────

  it("renders stale data indicator when isStale and lastUpdatedAt", () => {
    setPollingState({
      isLoading: false,
      run: makeRun(),
      isStale: true,
      lastUpdatedAt: "2026-04-04T10:00:00Z",
    });
    render(<RunDetailView runId="01HZ0000000000000000000001" />);

    expect(screen.getByRole("alert")).toBeInTheDocument();
  });

  // ── Override watermarks ───────────────────────────────────────────

  it("renders override watermark badges when present", () => {
    setPollingState({
      isLoading: false,
      run: makeRun({
        override_watermarks: [
          {
            override_id: "01HZ0000000000000000000099",
            approved_by: "admin@fxlab.io",
            approved_at: "2026-04-03T12:00:00Z",
            reason: "Emergency",
            revoked: false,
          },
        ],
      }),
    });
    render(<RunDetailView runId="01HZ0000000000000000000001" />);

    expect(screen.getByTestId("override-watermark-badge")).toBeInTheDocument();
  });

  // ── Preflight failures ────────────────────────────────────────────

  it("renders preflight failure display when preflight_results present", () => {
    setPollingState({
      isLoading: false,
      run: makeRun({
        preflight_results: [
          {
            passed: false,
            blockers: [
              {
                code: "PREFLIGHT_FAILED",
                message: "Failed",
                blocker_owner: "team@fxlab.io",
                next_step: "fix",
                metadata: {},
              },
            ],
            checked_at: "2026-04-04T10:00:00Z",
          },
        ],
      }),
    });
    render(<RunDetailView runId="01HZ0000000000000000000001" />);

    expect(screen.getByTestId("preflight-failure-display")).toBeInTheDocument();
  });

  // ── Progress bar ──────────────────────────────────────────────────

  it("renders progress bar when trial counts are present", () => {
    setPollingState({
      isLoading: false,
      run: makeRun({ trial_count: 100, completed_trials: 50 }),
    });
    render(<RunDetailView runId="01HZ0000000000000000000001" />);

    expect(screen.getByRole("progressbar")).toBeInTheDocument();
  });

  // ── Terminal state ────────────────────────────────────────────────

  it("renders RunTerminalState for completed run", () => {
    setPollingState({
      isLoading: false,
      run: makeRun({ status: "complete" }),
      isTerminal: true,
    });
    render(<RunDetailView runId="01HZ0000000000000000000001" />);

    expect(screen.getByTestId("run-terminal-complete")).toBeInTheDocument();
  });

  // ── URI scheme validation (XSS prevention) ────────────────────────

  it("strips javascript: result_uri to prevent XSS", () => {
    setPollingState({
      isLoading: false,
      run: makeRun({
        status: "complete",
        result_uri: "javascript:alert(1)",
      }),
      isTerminal: true,
    });
    render(<RunDetailView runId="01HZ0000000000000000000001" />);

    // The results link should NOT be rendered because URI was stripped
    expect(screen.queryByTestId("results-link")).not.toBeInTheDocument();
  });

  it("allows safe s3:// result_uri", () => {
    setPollingState({
      isLoading: false,
      run: makeRun({
        status: "complete",
        result_uri: "s3://bucket/results.parquet",
      }),
      isTerminal: true,
    });
    render(<RunDetailView runId="01HZ0000000000000000000001" />);

    const link = screen.getByTestId("results-link");
    expect(link.getAttribute("href")).toBe("s3://bucket/results.parquet");
  });

  // ── Safe date parsing ─────────────────────────────────────────────

  it("renders dash for invalid date strings instead of 'Invalid Date'", () => {
    setPollingState({
      isLoading: false,
      run: makeRun({
        created_at: "not-a-valid-date",
        started_at: "also-invalid",
      }),
    });
    render(<RunDetailView runId="01HZ0000000000000000000001" />);

    const dashes = screen.getAllByText("—");
    // started_at renders "—" when invalid
    expect(dashes.length).toBeGreaterThanOrEqual(1);
  });

  // ── Safe JSON.stringify ───────────────────────────────────────────

  it("renders current trial params safely", () => {
    setPollingState({
      isLoading: false,
      run: makeRun({
        current_trial_params: { lookback: 20, threshold: 0.5 },
      }),
    });
    render(<RunDetailView runId="01HZ0000000000000000000001" />);

    expect(screen.getByText(/lookback/)).toBeInTheDocument();
  });

  // ── Cancel button calls API ───────────────────────────────────────

  it("calls cancelRun API when cancel button clicked", async () => {
    const { runsApi } = await import("../api");
    setPollingState({ isLoading: false, run: makeRun({ status: "running" }) });
    render(<RunDetailView runId="01HZ0000000000000000000001" />);

    fireEvent.click(screen.getByTestId("cancel-button"));

    await waitFor(() => {
      expect(runsApi.cancelRun).toHaveBeenCalledWith(
        "01HZ0000000000000000000001",
        "User requested cancellation",
      );
    });
  });

  // ── Null run after loading ────────────────────────────────────────

  it("renders nothing when run is null and not loading", () => {
    setPollingState({ isLoading: false, run: null, error: null });
    const { container } = render(<RunDetailView runId="01HZ0000000000000000000001" />);

    expect(container.firstChild).toBeNull();
  });
});
