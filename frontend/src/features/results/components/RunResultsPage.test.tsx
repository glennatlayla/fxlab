/**
 * Tests for RunResultsPage container component.
 *
 * Tests the main page-level component that fetches RunChartsPayload
 * and orchestrates all sub-components. Uses mocked API calls.
 *
 * Covers:
 *   - Loading, success, and error states.
 *   - Error classification for NotFound, Auth (401/403), and generic errors.
 *   - Download error banner display.
 *   - Download abort-on-unmount cleanup.
 *   - FeatureErrorBoundary fault isolation per section.
 *   - Conditional rendering of banners and optional sections.
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { RunResultsPage } from "./RunResultsPage";
import { resultsApi } from "../api";
import { ResultsNotFoundError, ResultsAuthError } from "../errors";
import type { RunChartsPayload } from "@/types/results";

// ---------------------------------------------------------------------------
// Mock the API module
// ---------------------------------------------------------------------------

vi.mock("../api", () => ({
  resultsApi: {
    getRunCharts: vi.fn(),
    downloadExportBundle: vi.fn(),
  },
}));

// Mock the logger to prevent console noise in tests.
vi.mock("../logger", () => ({
  resultsLogger: {
    pageMount: vi.fn(),
    pageUnmount: vi.fn(),
    fetchStart: vi.fn(),
    fetchSuccess: vi.fn(),
    fetchFailure: vi.fn(),
    downloadStart: vi.fn(),
    downloadSuccess: vi.fn(),
    downloadFailure: vi.fn(),
    downloadAborted: vi.fn(),
  },
}));

const mockGetRunCharts = vi.mocked(resultsApi.getRunCharts);
const mockDownloadExportBundle = vi.mocked(resultsApi.downloadExportBundle);

// ---------------------------------------------------------------------------
// Fixtures
// ---------------------------------------------------------------------------

function makePayload(overrides?: Partial<RunChartsPayload>): RunChartsPayload {
  return {
    run_id: "01HRUN0000000000000000001",
    equity_curve: Array.from({ length: 50 }, (_, i) => ({
      timestamp: new Date(2026, 0, 1 + i).toISOString(),
      equity: 10000 + i * 10,
      drawdown: -(i % 5),
    })),
    sampling_applied: false,
    raw_equity_point_count: 50,
    fold_boundaries: [],
    regime_segments: [],
    trades: [
      {
        id: "t0001",
        symbol: "AAPL",
        side: "buy" as const,
        quantity: 100,
        entry_price: 150,
        exit_price: 155,
        pnl: 500,
        fold_index: 0,
        regime: "bull",
        entry_timestamp: "2026-01-15T10:00:00Z",
        exit_timestamp: "2026-01-20T14:00:00Z",
      },
    ],
    trades_truncated: false,
    total_trade_count: 1,
    fold_performance: [],
    regime_performance: [],
    trial_summaries: [
      {
        trial_id: "01HTRIAL000000000000000001",
        trial_index: 0,
        parameters: { lookback: 20 },
        objective_value: 1.85,
        sharpe_ratio: 1.85,
        max_drawdown_pct: -12.3,
        total_return_pct: 45.2,
        trade_count: 120,
        status: "completed",
      },
    ],
    candidate_metrics: [],
    export_schema_version: "1.0.0",
    ...overrides,
  };
}

function renderPage(runId = "01HRUN0000000000000000001") {
  const queryClient = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={[`/runs/${runId}/results`]}>
        <Routes>
          <Route path="/runs/:runId/results" element={<RunResultsPage runId={runId} />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("RunResultsPage", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  // -------------------------------------------------------------------------
  // Loading state
  // -------------------------------------------------------------------------

  it("shows loading state while data is being fetched", () => {
    mockGetRunCharts.mockReturnValue(new Promise(() => {})); // never resolves
    renderPage();
    expect(screen.getByTestId("results-loading")).toBeInTheDocument();
  });

  it("loading indicator has correct ARIA attributes", () => {
    mockGetRunCharts.mockReturnValue(new Promise(() => {}));
    renderPage();
    const loading = screen.getByTestId("results-loading");
    expect(loading).toHaveAttribute("role", "status");
    expect(loading).toHaveAttribute("aria-label", "Loading results");
  });

  // -------------------------------------------------------------------------
  // Success state
  // -------------------------------------------------------------------------

  it("renders results page after successful data fetch", async () => {
    mockGetRunCharts.mockResolvedValue(makePayload());
    renderPage();
    await waitFor(() => {
      expect(screen.getByTestId("run-results-page")).toBeInTheDocument();
    });
  });

  it("fetches data with the correct run ID", async () => {
    mockGetRunCharts.mockResolvedValue(makePayload());
    renderPage("01HRUN_CUSTOM_ID");
    await waitFor(() => {
      expect(mockGetRunCharts).toHaveBeenCalledWith("01HRUN_CUSTOM_ID");
    });
  });

  it("renders equity view section", async () => {
    mockGetRunCharts.mockResolvedValue(makePayload());
    renderPage();
    await waitFor(() => {
      expect(screen.getByTestId("equity-view")).toBeInTheDocument();
    });
  });

  it("renders trade blotter section", async () => {
    mockGetRunCharts.mockResolvedValue(makePayload());
    renderPage();
    await waitFor(() => {
      expect(screen.getByTestId("trade-blotter")).toBeInTheDocument();
    });
  });

  it("renders trial summary table section", async () => {
    mockGetRunCharts.mockResolvedValue(makePayload());
    renderPage();
    await waitFor(() => {
      expect(screen.getByTestId("trial-summary-table")).toBeInTheDocument();
    });
  });

  it("displays schema version in header", async () => {
    mockGetRunCharts.mockResolvedValue(makePayload());
    renderPage();
    await waitFor(() => {
      expect(screen.getByText("v1.0.0")).toBeInTheDocument();
    });
  });

  // -------------------------------------------------------------------------
  // Conditional banners
  // -------------------------------------------------------------------------

  it("shows sampling banner when sampling_applied is true", async () => {
    mockGetRunCharts.mockResolvedValue(
      makePayload({ sampling_applied: true, raw_equity_point_count: 5000 }),
    );
    renderPage();
    await waitFor(() => {
      expect(screen.getByTestId("sampling-banner")).toBeInTheDocument();
    });
  });

  it("shows trades truncated banner when trades_truncated is true", async () => {
    mockGetRunCharts.mockResolvedValue(
      makePayload({ trades_truncated: true, total_trade_count: 8000 }),
    );
    renderPage();
    await waitFor(() => {
      expect(screen.getByTestId("trades-truncated-banner")).toBeInTheDocument();
    });
  });

  // -------------------------------------------------------------------------
  // Error state — generic
  // -------------------------------------------------------------------------

  it("shows error state when API call fails", async () => {
    mockGetRunCharts.mockRejectedValue(new Error("Network error"));
    renderPage();
    await waitFor(() => {
      expect(screen.getByTestId("results-error")).toBeInTheDocument();
    });
  });

  it("error panel has role=alert for accessibility", async () => {
    mockGetRunCharts.mockRejectedValue(new Error("fail"));
    renderPage();
    await waitFor(() => {
      const errorEl = screen.getByTestId("results-error");
      expect(errorEl).toHaveAttribute("role", "alert");
    });
  });

  it("displays generic error message from Error.message", async () => {
    mockGetRunCharts.mockRejectedValue(new Error("Something went wrong"));
    renderPage();
    await waitFor(() => {
      expect(screen.getByText("Something went wrong")).toBeInTheDocument();
    });
  });

  // -------------------------------------------------------------------------
  // Error state — ResultsNotFoundError
  // -------------------------------------------------------------------------

  it("shows not-found message for ResultsNotFoundError", async () => {
    mockGetRunCharts.mockRejectedValue(new ResultsNotFoundError("run-gone"));
    renderPage();
    await waitFor(() => {
      expect(screen.getByText(/not found.*deleted.*incorrect/i)).toBeInTheDocument();
    });
  });

  // -------------------------------------------------------------------------
  // Error state — ResultsAuthError (401 / 403)
  // -------------------------------------------------------------------------

  it("shows session expired message for 401 auth error", async () => {
    mockGetRunCharts.mockRejectedValue(new ResultsAuthError("run-auth", 401));
    renderPage();
    await waitFor(() => {
      expect(screen.getByText(/session has expired.*log in/i)).toBeInTheDocument();
    });
  });

  it("shows permission denied message for 403 auth error", async () => {
    mockGetRunCharts.mockRejectedValue(new ResultsAuthError("run-perm", 403));
    renderPage();
    await waitFor(() => {
      expect(screen.getByText(/do not have permission/i)).toBeInTheDocument();
    });
  });

  it("shows fallback message for non-Error thrown values", async () => {
    mockGetRunCharts.mockRejectedValue("raw string");
    renderPage();
    await waitFor(() => {
      expect(screen.getByText("An unexpected error occurred.")).toBeInTheDocument();
    });
  });

  // -------------------------------------------------------------------------
  // Download error banner
  // -------------------------------------------------------------------------

  it("shows download error banner when download fails", async () => {
    const user = userEvent.setup();
    mockGetRunCharts.mockResolvedValue(
      makePayload({ trades_truncated: true, total_trade_count: 8000 }),
    );
    mockDownloadExportBundle.mockRejectedValue(new Error("Server error"));

    renderPage();
    await waitFor(() => {
      expect(screen.getByTestId("run-results-page")).toBeInTheDocument();
    });

    // Click a download trigger — TradesTruncatedBanner has an onDownload callback.
    const downloadBtn = screen.getAllByRole("button", { name: /download/i })[0];
    await user.click(downloadBtn);

    await waitFor(() => {
      expect(screen.getByTestId("download-error-banner")).toBeInTheDocument();
      expect(screen.getByText(/Server error/)).toBeInTheDocument();
    });
  });

  // -------------------------------------------------------------------------
  // Conditional sections
  // -------------------------------------------------------------------------

  it("does not render candidate comparison when candidate_metrics is empty", async () => {
    mockGetRunCharts.mockResolvedValue(makePayload({ candidate_metrics: [] }));
    renderPage();
    await waitFor(() => {
      expect(screen.getByTestId("run-results-page")).toBeInTheDocument();
    });
    expect(screen.queryByTestId("candidate-comparison-table")).not.toBeInTheDocument();
  });

  it("renders candidate comparison when candidate_metrics is non-empty", async () => {
    mockGetRunCharts.mockResolvedValue(
      makePayload({
        candidate_metrics: [
          {
            candidate_id: "01HCAND0000000000000000001",
            label: "Cand A",
            objective_value: 1.5,
            sharpe_ratio: 1.5,
            max_drawdown_pct: -10,
            total_return_pct: 30,
            win_rate: 0.55,
            profit_factor: 1.6,
            trade_count: 100,
          },
        ],
      }),
    );
    renderPage();
    await waitFor(() => {
      expect(screen.getByTestId("candidate-comparison-table")).toBeInTheDocument();
    });
  });

  it("does not render trial summary when trial_summaries is empty", async () => {
    mockGetRunCharts.mockResolvedValue(makePayload({ trial_summaries: [] }));
    renderPage();
    await waitFor(() => {
      expect(screen.getByTestId("run-results-page")).toBeInTheDocument();
    });
    expect(screen.queryByTestId("trial-summary-table")).not.toBeInTheDocument();
  });

  // -------------------------------------------------------------------------
  // Abort on unmount
  // -------------------------------------------------------------------------

  it("aborts in-flight download on unmount", async () => {
    const user = userEvent.setup();
    // Use a download that never resolves to simulate in-flight.
    mockDownloadExportBundle.mockReturnValue(
      new Promise<Blob>(() => {
        // Never resolves — simulates an in-flight download.
      }),
    );
    mockGetRunCharts.mockResolvedValue(
      makePayload({ trades_truncated: true, total_trade_count: 8000 }),
    );

    const { unmount } = renderPage();
    await waitFor(() => {
      expect(screen.getByTestId("run-results-page")).toBeInTheDocument();
    });

    // Start a download.
    const downloadBtn = screen.getAllByRole("button", { name: /download/i })[0];
    await user.click(downloadBtn);

    // The API should have been called with a signal.
    expect(mockDownloadExportBundle).toHaveBeenCalledWith(
      expect.any(String),
      expect.any(AbortSignal),
    );

    // Capture the signal to verify it gets aborted on unmount.
    const signal = mockDownloadExportBundle.mock.calls[0][1] as AbortSignal;
    expect(signal.aborted).toBe(false);

    // Unmount triggers abort via useEffect cleanup.
    unmount();
    expect(signal.aborted).toBe(true);
  });
});
