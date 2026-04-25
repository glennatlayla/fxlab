/**
 * Tests for the RunResults page component (M2.D4).
 *
 * Verifies:
 *   - All three sections (metrics tiles, equity-curve + drawdown chart pair,
 *     trade blotter) render with mocked API responses.
 *   - Metrics tiles show correctly formatted numbers (Sharpe to 2 decimals,
 *     returns as % with 2 decimals, win rate as %, etc.).
 *   - Equity-curve chart renders SVG path elements (recharts emits these
 *     for the LineChart series).
 *   - Blotter table renders 100 trades for page 1, advances to page 2 on
 *     "Next" click, and shows "No trades on this page" for an out-of-range
 *     page.
 *   - 404 from any of the three endpoints surfaces an error banner that
 *     contains the offending run_id.
 *
 * Example:
 *   npx vitest run src/pages/RunResults.test.tsx
 */

import { describe, it, expect, vi, beforeEach } from "vitest";
import { fireEvent, render, screen, waitFor, within } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import React, { type ReactNode } from "react";
import RunResults from "./RunResults";
import * as runResultsApi from "@/api/run_results";
import type {
  EquityCurveResponse,
  RunMetrics,
  TradeBlotterEntry,
  TradeBlotterPage,
} from "@/types/run_results";

// ---------------------------------------------------------------------------
// Mocks
// ---------------------------------------------------------------------------

vi.mock("@/api/run_results", async (importOriginal) => {
  const original = await importOriginal<typeof import("@/api/run_results")>();
  return {
    ...original,
    getMetrics: vi.fn(),
    getEquityCurve: vi.fn(),
    getBlotter: vi.fn(),
  };
});

vi.mock("@/auth/useAuth", () => ({
  useAuth: () => ({
    user: { id: "test-user", email: "trader@fxlab.test" },
    isAuthenticated: true,
    accessToken: "test-token",
    isLoading: false,
    logout: vi.fn(),
    login: vi.fn(),
    hasScope: vi.fn(() => true),
  }),
}));

// Replace recharts' ResponsiveContainer with a fixed-size pass-through so
// the inner LineChart / AreaChart receive non-zero dimensions in JSDOM and
// emit real <path> SVG elements (the spec asserts recharts emits these).
// We deliberately leave LineChart, AreaChart, Line, Area, etc. unmocked
// so the SVG paths under data-testid="equity-curve" are real.
vi.mock("recharts", async (importOriginal) => {
  const original = await importOriginal<typeof import("recharts")>();
  return {
    ...original,
    ResponsiveContainer: ({ children }: { children: ReactNode }) => {
      // Inject explicit dimensions into the chart child so recharts can
      // draw without relying on ResizeObserver (which is a no-op shim
      // in JSDOM and reports zero dimensions).
      const child = children as React.ReactElement<{ width?: number; height?: number }>;
      if (child && typeof child === "object" && "props" in child) {
        return (
          <div data-testid="responsive-container">
            {React.cloneElement(child, { width: 600, height: 300 })}
          </div>
        );
      }
      return <div data-testid="responsive-container">{children}</div>;
    },
  };
});

// ---------------------------------------------------------------------------
// Fixtures
// ---------------------------------------------------------------------------

const RUN_ID = "01HRUN0000000000000000000A";

function makeMetrics(overrides: Partial<RunMetrics> = {}): RunMetrics {
  return {
    run_id: RUN_ID,
    completed_at: "2026-04-12T12:34:56Z",
    total_return_pct: 15.5,
    annualized_return_pct: 12.3,
    max_drawdown_pct: -4.25,
    sharpe_ratio: 1.4567,
    total_trades: 250,
    win_rate: 0.6234,
    profit_factor: 2.6432,
    final_equity: 115500.0,
    bars_processed: 5000,
    summary_metrics: { custom: 1 },
    ...overrides,
  };
}

function makeEquityCurve(pointCount: number = 5): EquityCurveResponse {
  const points = Array.from({ length: pointCount }, (_, i) => ({
    timestamp: new Date(2026, 0, 1 + i).toISOString(),
    equity: 100000 + i * 500,
  }));
  return {
    run_id: RUN_ID,
    point_count: points.length,
    points,
  };
}

function makeTrade(index: number): TradeBlotterEntry {
  const minutes = index;
  const ts = new Date(Date.UTC(2026, 0, 1, 9, 30 + minutes, 0)).toISOString();
  return {
    trade_id: `trade-${String(index).padStart(6, "0")}`,
    timestamp: ts,
    symbol: index % 2 === 0 ? "EUR_USD" : "USD_JPY",
    side: index % 2 === 0 ? "buy" : "sell",
    quantity: 100 + index,
    price: 1.05 + index * 0.0001,
    commission: 0.5,
    slippage: 0.1,
  };
}

function makeBlotterPage(
  page: number,
  pageSize: number = 100,
  totalCount: number = 250,
): TradeBlotterPage {
  const totalPages = Math.ceil(totalCount / pageSize);
  if (page > totalPages) {
    return {
      run_id: RUN_ID,
      page,
      page_size: pageSize,
      total_count: totalCount,
      total_pages: totalPages,
      trades: [],
    };
  }
  const startIndex = (page - 1) * pageSize + 1;
  const endIndex = Math.min(startIndex + pageSize - 1, totalCount);
  const trades = Array.from({ length: endIndex - startIndex + 1 }, (_, i) =>
    makeTrade(startIndex + i),
  );
  return {
    run_id: RUN_ID,
    page,
    page_size: pageSize,
    total_count: totalCount,
    total_pages: totalPages,
    trades,
  };
}

// ---------------------------------------------------------------------------
// Render helper
// ---------------------------------------------------------------------------

function renderPage(runId: string = RUN_ID) {
  return render(
    <MemoryRouter initialEntries={[`/runs/${runId}/results`]}>
      <Routes>
        <Route path="/runs/:runId/results" element={<RunResults />} />
      </Routes>
    </MemoryRouter>,
  );
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("RunResults page (M2.D4)", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("renders all three sections (metrics tiles, charts, blotter) with mocked API responses", async () => {
    vi.mocked(runResultsApi.getMetrics).mockResolvedValue(makeMetrics());
    vi.mocked(runResultsApi.getEquityCurve).mockResolvedValue(makeEquityCurve(10));
    vi.mocked(runResultsApi.getBlotter).mockResolvedValue(makeBlotterPage(1, 100, 250));

    renderPage();

    await waitFor(() => {
      expect(screen.getByTestId("metrics-grid")).toBeInTheDocument();
    });

    expect(screen.getByTestId("metrics-grid")).toBeInTheDocument();
    expect(screen.getByTestId("equity-curve")).toBeInTheDocument();
    expect(screen.getByTestId("drawdown-curve")).toBeInTheDocument();
    expect(screen.getByTestId("trade-blotter")).toBeInTheDocument();

    // Verify the API calls were made with the right parameters.
    expect(runResultsApi.getMetrics).toHaveBeenCalledWith(RUN_ID, expect.anything());
    expect(runResultsApi.getEquityCurve).toHaveBeenCalledWith(RUN_ID, expect.anything());
    expect(runResultsApi.getBlotter).toHaveBeenCalledWith(RUN_ID, 1, 100, expect.anything());
  });

  it("formats metric tile values correctly (Sharpe to 2 decimals, returns/win rate as %)", async () => {
    vi.mocked(runResultsApi.getMetrics).mockResolvedValue(makeMetrics());
    vi.mocked(runResultsApi.getEquityCurve).mockResolvedValue(makeEquityCurve(3));
    vi.mocked(runResultsApi.getBlotter).mockResolvedValue(makeBlotterPage(1, 100, 250));

    renderPage();

    await waitFor(() => {
      expect(screen.getByTestId("metric-sharpe")).toBeInTheDocument();
    });

    // Sharpe Ratio: 1.4567 → "1.46" (2 decimals).
    expect(screen.getByTestId("metric-sharpe")).toHaveTextContent("1.46");
    // Total Return: 15.5 → "15.50%".
    expect(screen.getByTestId("metric-total-return")).toHaveTextContent("15.50%");
    // Max Drawdown: -4.25 → "-4.25%".
    expect(screen.getByTestId("metric-max-drawdown")).toHaveTextContent("-4.25%");
    // Win Rate (fraction 0..1): 0.6234 → "62.34%".
    expect(screen.getByTestId("metric-win-rate")).toHaveTextContent("62.34%");
    // Profit Factor: 2.6432 → "2.64".
    expect(screen.getByTestId("metric-profit-factor")).toHaveTextContent("2.64");
    // Trade Count: 250.
    expect(screen.getByTestId("metric-trade-count")).toHaveTextContent("250");
  });

  it("renders the equity-curve chart with real recharts SVG path elements", async () => {
    vi.mocked(runResultsApi.getMetrics).mockResolvedValue(makeMetrics());
    vi.mocked(runResultsApi.getEquityCurve).mockResolvedValue(makeEquityCurve(20));
    vi.mocked(runResultsApi.getBlotter).mockResolvedValue(makeBlotterPage(1, 100, 250));

    renderPage();

    await waitFor(() => {
      expect(screen.getByTestId("equity-curve")).toBeInTheDocument();
    });

    // recharts emits <path> SVG elements for the LineChart series; assert
    // at least one path renders inside the equity-curve container.
    const equityChart = screen.getByTestId("equity-curve");
    const paths = equityChart.querySelectorAll("path");
    expect(paths.length).toBeGreaterThan(0);
  });

  it("renders 100 trades when page_size=100 and advances to page 2 on Next click", async () => {
    vi.mocked(runResultsApi.getMetrics).mockResolvedValue(makeMetrics());
    vi.mocked(runResultsApi.getEquityCurve).mockResolvedValue(makeEquityCurve(5));
    vi.mocked(runResultsApi.getBlotter).mockImplementation(
      async (_runId: string, page: number, pageSize?: number) =>
        makeBlotterPage(page, pageSize ?? 100, 250),
    );

    renderPage();

    await waitFor(() => {
      expect(screen.getByTestId("trade-blotter")).toBeInTheDocument();
    });

    // 100 rows on page 1.
    const page1Rows = screen.getAllByTestId(/^blotter-row-trade-/);
    expect(page1Rows).toHaveLength(100);
    expect(screen.getByTestId("blotter-page")).toHaveTextContent("1");
    expect(screen.getByTestId("blotter-total-pages")).toHaveTextContent("3");
    expect(screen.getByTestId("blotter-total-count")).toHaveTextContent("250");

    // Click Next → page 2 fetched with the page_size=100 query param.
    fireEvent.click(screen.getByTestId("blotter-next"));

    await waitFor(() => {
      expect(screen.getByTestId("blotter-page")).toHaveTextContent("2");
    });

    expect(runResultsApi.getBlotter).toHaveBeenCalledWith(RUN_ID, 2, 100);
    const page2Rows = screen.getAllByTestId(/^blotter-row-trade-/);
    expect(page2Rows).toHaveLength(100);
  });

  it("shows 'No trades on this page' for an out-of-range page", async () => {
    vi.mocked(runResultsApi.getMetrics).mockResolvedValue(makeMetrics());
    vi.mocked(runResultsApi.getEquityCurve).mockResolvedValue(makeEquityCurve(3));
    // Initial page 1 → 100 trades; subsequent click returns an empty
    // out-of-range page (mirroring the M2.C3 contract).
    let callCount = 0;
    vi.mocked(runResultsApi.getBlotter).mockImplementation(async () => {
      callCount += 1;
      if (callCount === 1) return makeBlotterPage(1, 100, 100);
      // After paginating past total_pages: empty trades list.
      return makeBlotterPage(2, 100, 100);
    });

    renderPage();

    await waitFor(() => {
      expect(screen.getByTestId("trade-blotter")).toBeInTheDocument();
    });

    fireEvent.click(screen.getByTestId("blotter-next"));

    await waitFor(() => {
      expect(screen.getByTestId("blotter-empty-row")).toBeInTheDocument();
    });

    const emptyRow = screen.getByTestId("blotter-empty-row");
    expect(within(emptyRow).getByText(/No trades on this page/i)).toBeInTheDocument();
  });

  it("shows an error banner with the run_id when the metrics endpoint returns 404", async () => {
    const notFound = new runResultsApi.RunResultsNotFoundError(RUN_ID);
    vi.mocked(runResultsApi.getMetrics).mockRejectedValue(notFound);
    vi.mocked(runResultsApi.getEquityCurve).mockResolvedValue(makeEquityCurve(3));
    vi.mocked(runResultsApi.getBlotter).mockResolvedValue(makeBlotterPage(1, 100, 250));

    renderPage();

    await waitFor(() => {
      expect(screen.getByTestId("run-results-error")).toBeInTheDocument();
    });

    const banner = screen.getByTestId("run-results-error");
    expect(banner).toHaveTextContent(RUN_ID);
    expect(banner).toHaveTextContent(/not found/i);
  });

  it("shows an error banner with the run_id when the equity-curve endpoint returns 404", async () => {
    const notFound = new runResultsApi.RunResultsNotFoundError(RUN_ID);
    vi.mocked(runResultsApi.getMetrics).mockResolvedValue(makeMetrics());
    vi.mocked(runResultsApi.getEquityCurve).mockRejectedValue(notFound);
    vi.mocked(runResultsApi.getBlotter).mockResolvedValue(makeBlotterPage(1, 100, 250));

    renderPage();

    await waitFor(() => {
      expect(screen.getByTestId("run-results-error")).toBeInTheDocument();
    });

    expect(screen.getByTestId("run-results-error")).toHaveTextContent(RUN_ID);
  });

  it("shows an error banner with the run_id when the blotter endpoint returns 404", async () => {
    const notFound = new runResultsApi.RunResultsNotFoundError(RUN_ID);
    vi.mocked(runResultsApi.getMetrics).mockResolvedValue(makeMetrics());
    vi.mocked(runResultsApi.getEquityCurve).mockResolvedValue(makeEquityCurve(3));
    vi.mocked(runResultsApi.getBlotter).mockRejectedValue(notFound);

    renderPage();

    await waitFor(() => {
      expect(screen.getByTestId("run-results-error")).toBeInTheDocument();
    });

    expect(screen.getByTestId("run-results-error")).toHaveTextContent(RUN_ID);
  });
});
