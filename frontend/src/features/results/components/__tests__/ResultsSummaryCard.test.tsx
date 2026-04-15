/**
 * Tests for ResultsSummaryCard component.
 *
 * AC-1: Card fetches and displays key metrics for a completed run.
 * AC-2: Shows loading skeleton while fetching.
 * AC-3: Shows error state with retry button on API failure.
 * AC-4: Total return is green when positive, red when negative.
 * AC-5: Sharpe ratio is color-coded: >1.5 green, 0.5-1.5 amber, <0.5 red.
 * AC-6: Max drawdown always red-tinted, intensity increases with magnitude.
 * AC-7: Win rate is green if >50%, red if <=50%.
 * AC-8: "View Full Results" button calls onViewFull when provided.
 * AC-9: "View Full Results" button is hidden when onViewFull not provided.
 */

import { describe, it, expect, vi } from "vitest";
import { render, screen, waitFor, fireEvent } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { ResultsSummaryCard } from "../ResultsSummaryCard";
import type { RunChartsPayload } from "@/types/results";

// Mock resultsApi
vi.mock("../../api", () => ({
  resultsApi: {
    getRunCharts: vi.fn(),
  },
}));

import { resultsApi } from "../../api";

// ---------------------------------------------------------------------------
// Fixtures
// ---------------------------------------------------------------------------

function makeRunCharts(overrides?: Partial<RunChartsPayload>): RunChartsPayload {
  return {
    run_id: "test-run-id",
    equity_curve: [
      { timestamp: "2026-01-01T00:00:00Z", equity: 10000, drawdown: 0 },
      { timestamp: "2026-01-02T00:00:00Z", equity: 10500, drawdown: -2.5 },
      { timestamp: "2026-01-03T00:00:00Z", equity: 10200, drawdown: -5.0 },
    ],
    sampling_applied: false,
    raw_equity_point_count: 3,
    fold_boundaries: [],
    regime_segments: [],
    trades: [
      {
        id: "trade-1",
        symbol: "AAPL",
        side: "buy",
        quantity: 100,
        entry_price: 150,
        exit_price: 155,
        pnl: 500,
        fold_index: null,
        regime: null,
        entry_timestamp: "2026-01-01T10:00:00Z",
        exit_timestamp: "2026-01-02T10:00:00Z",
      },
      {
        id: "trade-2",
        symbol: "AAPL",
        side: "sell",
        quantity: 100,
        entry_price: 155,
        exit_price: 152,
        pnl: 300,
        fold_index: null,
        regime: null,
        entry_timestamp: "2026-01-02T11:00:00Z",
        exit_timestamp: "2026-01-03T11:00:00Z",
      },
    ],
    trades_truncated: false,
    total_trade_count: 2,
    fold_performance: [],
    regime_performance: [],
    trial_summaries: [],
    candidate_metrics: [],
    export_schema_version: "1.0",
    ...overrides,
  };
}

function createWrapper() {
  const queryClient = new QueryClient({
    defaultOptions: {
      queries: { retry: false },
    },
  });
  return ({ children }: { children: React.ReactNode }) => (
    <QueryClientProvider client={queryClient}>{children}</QueryClientProvider>
  );
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("ResultsSummaryCard", () => {
  // AC-1: Renders key metrics for completed run
  it("renders key metrics from API response", async () => {
    const mockData = makeRunCharts();
    vi.mocked(resultsApi.getRunCharts).mockResolvedValueOnce(mockData);

    render(<ResultsSummaryCard runId="test-run-id" />, {
      wrapper: createWrapper(),
    });

    // Wait for data to load and metrics to display
    await waitFor(() => {
      expect(screen.getByText("Results Summary")).toBeInTheDocument();
    });

    // Check that key metrics are present
    expect(screen.getByText("Total Return")).toBeInTheDocument();
    expect(screen.getByText("Sharpe Ratio")).toBeInTheDocument();
    expect(screen.getByText("Max Drawdown")).toBeInTheDocument();
    expect(screen.getByText("Win Rate")).toBeInTheDocument();
  });

  // AC-2: Loading skeleton
  it("shows loading skeleton while fetching", () => {
    vi.mocked(resultsApi.getRunCharts).mockImplementationOnce(
      () =>
        new Promise((resolve) => {
          setTimeout(() => resolve(makeRunCharts()), 100);
        }),
    );

    render(<ResultsSummaryCard runId="test-run-id" />, {
      wrapper: createWrapper(),
    });

    const skeleton = screen.getByTestId("results-summary-skeleton");
    expect(skeleton).toBeInTheDocument();
  });

  // AC-3: Error state with retry
  it("shows error state on API failure", async () => {
    const error = new Error("Network error");
    vi.mocked(resultsApi.getRunCharts).mockRejectedValueOnce(error);

    render(<ResultsSummaryCard runId="test-run-id" />, {
      wrapper: createWrapper(),
    });

    await waitFor(() => {
      expect(screen.getByTestId("results-summary-error")).toBeInTheDocument();
    });

    const retryButton = screen.getByRole("button", { name: /retry/i });
    expect(retryButton).toBeInTheDocument();
  });

  it("retries on retry button click", async () => {
    const error = new Error("Network error");
    vi.mocked(resultsApi.getRunCharts)
      .mockRejectedValueOnce(error)
      .mockResolvedValueOnce(makeRunCharts());

    render(<ResultsSummaryCard runId="test-run-id" />, {
      wrapper: createWrapper(),
    });

    await waitFor(() => {
      expect(screen.getByTestId("results-summary-error")).toBeInTheDocument();
    });

    const retryButton = screen.getByRole("button", { name: /retry/i });
    fireEvent.click(retryButton);

    // After retry, data should load
    await waitFor(() => {
      expect(screen.queryByTestId("results-summary-error")).not.toBeInTheDocument();
    });
  });

  // AC-4: Total return color coding
  it("displays total return in green when positive", async () => {
    const mockData = makeRunCharts();
    vi.mocked(resultsApi.getRunCharts).mockResolvedValueOnce(mockData);

    const { container } = render(<ResultsSummaryCard runId="test-run-id" />, {
      wrapper: createWrapper(),
    });

    await waitFor(() => {
      expect(screen.getByText("Results Summary")).toBeInTheDocument();
    });

    // Total return is +2% (from 10000 to 10200)
    const totalReturnTile = Array.from(container.querySelectorAll("[data-sentiment]")).find(
      (el) => el.textContent.includes("Total Return"),
    );
    expect(totalReturnTile).toHaveAttribute("data-sentiment", "positive");
  });

  it("displays total return in red when negative", async () => {
    const mockData = makeRunCharts({
      equity_curve: [
        { timestamp: "2026-01-01T00:00:00Z", equity: 10000, drawdown: 0 },
        { timestamp: "2026-01-02T00:00:00Z", equity: 9800, drawdown: -2.0 },
      ],
    });
    vi.mocked(resultsApi.getRunCharts).mockResolvedValueOnce(mockData);

    const { container } = render(<ResultsSummaryCard runId="test-run-id" />, {
      wrapper: createWrapper(),
    });

    await waitFor(() => {
      expect(screen.getByText("Results Summary")).toBeInTheDocument();
    });

    const totalReturnTile = Array.from(container.querySelectorAll("[data-sentiment]")).find(
      (el) => el.textContent.includes("Total Return"),
    );
    expect(totalReturnTile).toHaveAttribute("data-sentiment", "negative");
  });

  // AC-5: Sharpe ratio color coding
  it("displays sharpe ratio in green when > 1.5", async () => {
    const mockData = makeRunCharts({
      trial_summaries: [{ trial_id: "t1", trial_index: 0, parameters: {}, objective_value: 1.8, sharpe_ratio: 1.8, max_drawdown_pct: -10, total_return_pct: 20, trade_count: 5, status: "completed" }],
    });
    vi.mocked(resultsApi.getRunCharts).mockResolvedValueOnce(mockData);

    const { container } = render(<ResultsSummaryCard runId="test-run-id" />, {
      wrapper: createWrapper(),
    });

    await waitFor(() => {
      expect(screen.getByText("Results Summary")).toBeInTheDocument();
    });

    const sharpeTile = Array.from(container.querySelectorAll("[data-sentiment]")).find(
      (el) => el.textContent.includes("Sharpe Ratio"),
    );
    expect(sharpeTile).toHaveAttribute("data-sentiment", "positive");
  });

  it("displays sharpe ratio in amber when 0.5-1.5", async () => {
    const mockData = makeRunCharts({
      trial_summaries: [{ trial_id: "t1", trial_index: 0, parameters: {}, objective_value: 0.9, sharpe_ratio: 0.9, max_drawdown_pct: -15, total_return_pct: 15, trade_count: 5, status: "completed" }],
    });
    vi.mocked(resultsApi.getRunCharts).mockResolvedValueOnce(mockData);

    const { container } = render(<ResultsSummaryCard runId="test-run-id" />, {
      wrapper: createWrapper(),
    });

    await waitFor(() => {
      expect(screen.getByText("Results Summary")).toBeInTheDocument();
    });

    const sharpeTile = Array.from(container.querySelectorAll("[data-sentiment]")).find(
      (el) => el.textContent.includes("Sharpe Ratio"),
    );
    expect(sharpeTile).toHaveAttribute("data-sentiment", "warning");
  });

  it("displays sharpe ratio in red when < 0.5", async () => {
    const mockData = makeRunCharts({
      trial_summaries: [{ trial_id: "t1", trial_index: 0, parameters: {}, objective_value: 0.3, sharpe_ratio: 0.3, max_drawdown_pct: -20, total_return_pct: 5, trade_count: 5, status: "completed" }],
    });
    vi.mocked(resultsApi.getRunCharts).mockResolvedValueOnce(mockData);

    const { container } = render(<ResultsSummaryCard runId="test-run-id" />, {
      wrapper: createWrapper(),
    });

    await waitFor(() => {
      expect(screen.getByText("Results Summary")).toBeInTheDocument();
    });

    const sharpeTile = Array.from(container.querySelectorAll("[data-sentiment]")).find(
      (el) => el.textContent.includes("Sharpe Ratio"),
    );
    expect(sharpeTile).toHaveAttribute("data-sentiment", "negative");
  });

  // AC-6: Max drawdown always red
  it("displays max drawdown in red", async () => {
    const mockData = makeRunCharts();
    vi.mocked(resultsApi.getRunCharts).mockResolvedValueOnce(mockData);

    const { container } = render(<ResultsSummaryCard runId="test-run-id" />, {
      wrapper: createWrapper(),
    });

    await waitFor(() => {
      expect(screen.getByText("Results Summary")).toBeInTheDocument();
    });

    const drawdownTile = Array.from(container.querySelectorAll("[data-sentiment]")).find(
      (el) => el.textContent.includes("Max Drawdown"),
    );
    expect(drawdownTile).toHaveAttribute("data-sentiment", "negative");
  });

  // AC-7: Win rate color coding
  it("displays win rate in green when > 50%", async () => {
    const mockData = makeRunCharts();
    vi.mocked(resultsApi.getRunCharts).mockResolvedValueOnce(mockData);

    const { container } = render(<ResultsSummaryCard runId="test-run-id" />, {
      wrapper: createWrapper(),
    });

    await waitFor(() => {
      expect(screen.getByText("Results Summary")).toBeInTheDocument();
    });

    // With 2 trades and both positive PnL, win rate is 100%
    const winRateTile = Array.from(container.querySelectorAll("[data-sentiment]")).find(
      (el) => el.textContent.includes("Win Rate"),
    );
    expect(winRateTile).toHaveAttribute("data-sentiment", "positive");
  });

  it("displays win rate in red when <= 50%", async () => {
    const mockData = makeRunCharts({
      trades: [
        {
          id: "trade-1",
          symbol: "AAPL",
          side: "buy",
          quantity: 100,
          entry_price: 150,
          exit_price: 155,
          pnl: 500,
          fold_index: null,
          regime: null,
          entry_timestamp: "2026-01-01T10:00:00Z",
          exit_timestamp: "2026-01-02T10:00:00Z",
        },
        {
          id: "trade-2",
          symbol: "AAPL",
          side: "sell",
          quantity: 100,
          entry_price: 155,
          exit_price: 152,
          pnl: -300,
          fold_index: null,
          regime: null,
          entry_timestamp: "2026-01-02T11:00:00Z",
          exit_timestamp: "2026-01-03T11:00:00Z",
        },
      ],
    });
    vi.mocked(resultsApi.getRunCharts).mockResolvedValueOnce(mockData);

    const { container } = render(<ResultsSummaryCard runId="test-run-id" />, {
      wrapper: createWrapper(),
    });

    await waitFor(() => {
      expect(screen.getByText("Results Summary")).toBeInTheDocument();
    });

    // Win rate is 50% (1 win, 1 loss)
    const winRateTile = Array.from(container.querySelectorAll("[data-sentiment]")).find(
      (el) => el.textContent.includes("Win Rate"),
    );
    expect(winRateTile).toHaveAttribute("data-sentiment", "negative");
  });

  // AC-8: View Full Results button
  it("renders View Full Results button when onViewFull provided", async () => {
    const mockData = makeRunCharts();
    const onViewFull = vi.fn();
    vi.mocked(resultsApi.getRunCharts).mockResolvedValueOnce(mockData);

    render(<ResultsSummaryCard runId="test-run-id" onViewFull={onViewFull} />, {
      wrapper: createWrapper(),
    });

    await waitFor(() => {
      const button = screen.getByRole("button", { name: /view full results/i });
      expect(button).toBeInTheDocument();
    });
  });

  it("calls onViewFull when button clicked", async () => {
    const mockData = makeRunCharts();
    const onViewFull = vi.fn();
    vi.mocked(resultsApi.getRunCharts).mockResolvedValueOnce(mockData);

    render(<ResultsSummaryCard runId="test-run-id" onViewFull={onViewFull} />, {
      wrapper: createWrapper(),
    });

    await waitFor(() => {
      const button = screen.getByRole("button", { name: /view full results/i });
      fireEvent.click(button);
    });

    expect(onViewFull).toHaveBeenCalled();
  });

  // AC-9: Hidden when no callback
  it("hides View Full Results button when onViewFull not provided", async () => {
    const mockData = makeRunCharts();
    vi.mocked(resultsApi.getRunCharts).mockResolvedValueOnce(mockData);

    render(<ResultsSummaryCard runId="test-run-id" />, {
      wrapper: createWrapper(),
    });

    await waitFor(() => {
      expect(screen.getByText("Results Summary")).toBeInTheDocument();
    });

    const button = screen.queryByRole("button", { name: /view full results/i });
    expect(button).not.toBeInTheDocument();
  });
});
