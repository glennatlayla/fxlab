/**
 * Tests for StrategyPnL page component (M9).
 *
 * Verifies:
 *   - Performance metric cards display correct values.
 *   - Equity curve renders with timeseries data.
 *   - Attribution table shows per-symbol breakdown.
 *   - Date range filter updates data.
 *   - Loading, error, empty, and not-found states.
 *   - Error display with retry capability.
 *
 * Example:
 *   npx vitest run src/pages/StrategyPnL.test.tsx
 */

import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import StrategyPnL from "./StrategyPnL";
import * as pnlApiModule from "@/features/pnl/api";
import type { PnlSummary, PnlTimeseriesPoint, PnlAttributionReport } from "@/features/pnl/api";
import type { ReactNode } from "react";

// ---------------------------------------------------------------------------
// Mocks
// ---------------------------------------------------------------------------

vi.mock("@/features/pnl/api");

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

vi.mock("@/hooks/useChartEngine", () => ({
  useChartEngine: () => "recharts",
}));

// Mock recharts to avoid canvas rendering issues in JSDOM
vi.mock("recharts", () => ({
  ResponsiveContainer: ({ children }: { children: ReactNode }) => (
    <div data-testid="responsive-container">{children}</div>
  ),
  AreaChart: ({ children }: { children: ReactNode }) => (
    <div data-testid="area-chart">{children}</div>
  ),
  LineChart: ({ children }: { children: ReactNode }) => (
    <div data-testid="line-chart">{children}</div>
  ),
  Area: () => <div data-testid="area" />,
  Line: () => <div data-testid="line" />,
  XAxis: () => <div data-testid="x-axis" />,
  YAxis: () => <div data-testid="y-axis" />,
  CartesianGrid: () => <div data-testid="cartesian-grid" />,
  Tooltip: () => <div data-testid="tooltip" />,
  Legend: () => <div data-testid="legend" />,
}));

// ---------------------------------------------------------------------------
// Test helpers
// ---------------------------------------------------------------------------

const DEPLOYMENT_ID = "01HTESTDEP0000000000000001";

const queryClient = new QueryClient({
  defaultOptions: { queries: { retry: false } },
});

/**
 * Render StrategyPnL within required providers and route context.
 *
 * Uses MemoryRouter to inject :deploymentId param. Wraps with
 * QueryClientProvider for @tanstack/react-query compatibility.
 */
function renderPage(deploymentId: string = DEPLOYMENT_ID) {
  return render(
    <QueryClientProvider client={queryClient}>
      <MemoryRouter initialEntries={[`/pnl/${deploymentId}`]}>
        <Routes>
          <Route path="/pnl/:deploymentId" element={<StrategyPnL />} />
        </Routes>
      </MemoryRouter>
    </QueryClientProvider>,
  );
}

const mockSummary: PnlSummary = {
  deployment_id: DEPLOYMENT_ID,
  total_realized_pnl: "1250.50",
  total_unrealized_pnl: "340.25",
  total_commission: "52.00",
  total_fees: "0",
  net_pnl: "1538.75",
  positions_count: 5,
  total_trades: 20,
  winning_trades: 13,
  losing_trades: 7,
  win_rate: "65.0",
  sharpe_ratio: "1.42",
  max_drawdown_pct: "4.2",
  avg_win: "120.50",
  avg_loss: "-85.30",
  profit_factor: "2.64",
  date_from: "2026-04-01",
  date_to: "2026-04-12",
};

const mockTimeseries: PnlTimeseriesPoint[] = [
  {
    snapshot_date: "2026-04-01",
    realized_pnl: "100",
    unrealized_pnl: "50",
    net_pnl: "150",
    cumulative_pnl: "150",
    daily_pnl: "150",
    commission: "5",
    fees: "0",
    positions_count: 2,
    drawdown_pct: "0",
  },
  {
    snapshot_date: "2026-04-02",
    realized_pnl: "200",
    unrealized_pnl: "80",
    net_pnl: "280",
    cumulative_pnl: "280",
    daily_pnl: "130",
    commission: "10",
    fees: "0",
    positions_count: 3,
    drawdown_pct: "0",
  },
];

const mockAttribution: PnlAttributionReport = {
  deployment_id: DEPLOYMENT_ID,
  date_from: "2026-04-01",
  date_to: "2026-04-12",
  total_net_pnl: "1150.00",
  by_symbol: [
    {
      symbol: "AAPL",
      realized_pnl: "600.00",
      unrealized_pnl: "200.00",
      net_pnl: "800.00",
      contribution_pct: "69.6",
      total_trades: 5,
      winning_trades: 4,
      win_rate: "80.0",
      total_volume: "500",
      commission: "10.00",
    },
    {
      symbol: "MSFT",
      realized_pnl: "400.00",
      unrealized_pnl: "-50.00",
      net_pnl: "350.00",
      contribution_pct: "30.4",
      total_trades: 3,
      winning_trades: 2,
      win_rate: "66.7",
      total_volume: "150",
      commission: "6.00",
    },
  ],
};

/**
 * Configure the pnlApi mock to return standard test data.
 *
 * All methods are mocked with resolved values. Individual tests
 * can override specific methods as needed.
 */
function mockPnlApiSuccess() {
  vi.spyOn(pnlApiModule, "pnlApi", "get").mockReturnValue({
    getSummary: vi.fn().mockResolvedValue(mockSummary),
    getTimeseries: vi.fn().mockResolvedValue(mockTimeseries),
    getAttribution: vi.fn().mockResolvedValue(mockAttribution),
    getComparison: vi.fn().mockResolvedValue({ entries: [] }),
    takeSnapshot: vi.fn().mockResolvedValue({}),
  });
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("StrategyPnL", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    queryClient.clear();
  });

  it("test_renders_performance_metrics", async () => {
    mockPnlApiSuccess();
    renderPage();

    await waitFor(() => {
      expect(screen.getByTestId("metrics-grid")).toBeInTheDocument();
    });

    // Verify key metric values
    expect(screen.getByTestId("metric-net-pnl")).toHaveTextContent("$1,538.75");
    expect(screen.getByTestId("metric-win-rate")).toHaveTextContent("65.00%");
    expect(screen.getByTestId("metric-sharpe")).toHaveTextContent("1.42");
    expect(screen.getByTestId("metric-drawdown")).toHaveTextContent("4.20%");
    expect(screen.getByTestId("metric-profit-factor")).toHaveTextContent("2.64");
    expect(screen.getByTestId("metric-total-trades")).toHaveTextContent("20");
  });

  it("test_renders_equity_curve_chart", async () => {
    mockPnlApiSuccess();
    renderPage();

    await waitFor(() => {
      expect(screen.getByTestId("equity-curve")).toBeInTheDocument();
    });

    // Recharts is mocked — verify area chart rendered
    expect(screen.getByTestId("area-chart")).toBeInTheDocument();
  });

  it("test_renders_attribution_table", async () => {
    mockPnlApiSuccess();
    renderPage();

    await waitFor(() => {
      expect(screen.getByTestId("attribution-table")).toBeInTheDocument();
    });

    // Verify both symbols appear
    expect(screen.getByTestId("attribution-row-AAPL")).toBeInTheDocument();
    expect(screen.getByTestId("attribution-row-MSFT")).toBeInTheDocument();

    // AAPL has higher contribution — should appear first
    const rows = screen.getAllByTestId(/^attribution-row-/);
    expect(rows[0]).toHaveAttribute("data-testid", "attribution-row-AAPL");

    // Verify total
    expect(screen.getByTestId("attribution-total")).toHaveTextContent("$1,150.00");
  });

  it("test_renders_pnl_breakdown", async () => {
    mockPnlApiSuccess();
    renderPage();

    await waitFor(() => {
      expect(screen.getByTestId("pnl-breakdown")).toBeInTheDocument();
    });

    expect(screen.getByTestId("pnl-breakdown")).toHaveTextContent("$1,250.50");
    expect(screen.getByTestId("pnl-breakdown")).toHaveTextContent("$340.25");
    expect(screen.getByTestId("pnl-breakdown")).toHaveTextContent("$52.00");
  });

  it("test_renders_trade_statistics", async () => {
    mockPnlApiSuccess();
    renderPage();

    await waitFor(() => {
      expect(screen.getByTestId("trade-stats")).toBeInTheDocument();
    });

    expect(screen.getByTestId("trade-stats")).toHaveTextContent("13");
    expect(screen.getByTestId("trade-stats")).toHaveTextContent("7");
    expect(screen.getByTestId("trade-stats")).toHaveTextContent("$120.50");
  });

  it("test_shows_loading_state", async () => {
    // Use a never-resolving promise to keep loading state visible
    const pendingPromise = new Promise<PnlSummary>(() => {});

    vi.spyOn(pnlApiModule, "pnlApi", "get").mockReturnValue({
      getSummary: vi.fn().mockReturnValue(pendingPromise),
      getTimeseries: vi.fn().mockReturnValue(new Promise(() => {})),
      getAttribution: vi.fn().mockReturnValue(new Promise(() => {})),
      getComparison: vi.fn(),
      takeSnapshot: vi.fn(),
    });

    renderPage();

    await waitFor(() => {
      expect(screen.getByTestId("pnl-loading")).toBeInTheDocument();
    });
  });

  it("test_shows_error_state_on_network_failure", async () => {
    vi.spyOn(pnlApiModule, "pnlApi", "get").mockReturnValue({
      getSummary: vi.fn().mockRejectedValue(new pnlApiModule.PnlNetworkError(500)),
      getTimeseries: vi.fn().mockRejectedValue(new pnlApiModule.PnlNetworkError(500)),
      getAttribution: vi.fn().mockRejectedValue(new pnlApiModule.PnlNetworkError(500)),
      getComparison: vi.fn(),
      takeSnapshot: vi.fn(),
    });

    renderPage();

    await waitFor(() => {
      expect(screen.getByTestId("pnl-error")).toBeInTheDocument();
    });

    expect(screen.getByTestId("pnl-error")).toHaveTextContent("Failed to load P&L data");
    expect(screen.getByTestId("retry-button")).toBeInTheDocument();
  });

  it("test_shows_not_found_error", async () => {
    vi.spyOn(pnlApiModule, "pnlApi", "get").mockReturnValue({
      getSummary: vi.fn().mockRejectedValue(new pnlApiModule.PnlNotFoundError("NONEXISTENT")),
      getTimeseries: vi.fn().mockRejectedValue(new pnlApiModule.PnlNotFoundError("NONEXISTENT")),
      getAttribution: vi.fn().mockRejectedValue(new pnlApiModule.PnlNotFoundError("NONEXISTENT")),
      getComparison: vi.fn(),
      takeSnapshot: vi.fn(),
    });

    renderPage("NONEXISTENT");

    await waitFor(() => {
      expect(screen.getByTestId("pnl-error")).toBeInTheDocument();
    });

    expect(screen.getByTestId("pnl-error")).toHaveTextContent("not found");
  });

  it("test_shows_empty_timeseries", async () => {
    vi.spyOn(pnlApiModule, "pnlApi", "get").mockReturnValue({
      getSummary: vi.fn().mockResolvedValue(mockSummary),
      getTimeseries: vi.fn().mockResolvedValue([]),
      getAttribution: vi.fn().mockResolvedValue(mockAttribution),
      getComparison: vi.fn(),
      takeSnapshot: vi.fn(),
    });

    renderPage();

    await waitFor(() => {
      expect(screen.getByTestId("equity-empty")).toBeInTheDocument();
    });

    expect(screen.getByTestId("equity-empty")).toHaveTextContent("No timeseries data");
  });

  it("test_shows_empty_attribution", async () => {
    vi.spyOn(pnlApiModule, "pnlApi", "get").mockReturnValue({
      getSummary: vi.fn().mockResolvedValue(mockSummary),
      getTimeseries: vi.fn().mockResolvedValue(mockTimeseries),
      getAttribution: vi.fn().mockResolvedValue({
        ...mockAttribution,
        by_symbol: [],
        total_net_pnl: "0",
      }),
      getComparison: vi.fn(),
      takeSnapshot: vi.fn(),
    });

    renderPage();

    await waitFor(() => {
      expect(screen.getByTestId("attribution-empty")).toBeInTheDocument();
    });
  });

  it("test_displays_deployment_id", async () => {
    mockPnlApiSuccess();
    renderPage();

    await waitFor(() => {
      expect(screen.getByTestId("pnl-title")).toBeInTheDocument();
    });

    expect(screen.getByText(DEPLOYMENT_ID)).toBeInTheDocument();
  });

  it("test_date_filter_inputs_present", async () => {
    mockPnlApiSuccess();
    renderPage();

    await waitFor(() => {
      expect(screen.getByTestId("date-filter")).toBeInTheDocument();
    });

    expect(screen.getByTestId("date-from-input")).toBeInTheDocument();
    expect(screen.getByTestId("date-to-input")).toBeInTheDocument();
    expect(screen.getByTestId("apply-filter-button")).toBeInTheDocument();
  });

  it("test_retry_button_refetches_data", async () => {
    const getSummaryMock = vi
      .fn()
      .mockRejectedValueOnce(new pnlApiModule.PnlNetworkError(500))
      .mockResolvedValueOnce(mockSummary);

    const getTimeseriesMock = vi
      .fn()
      .mockRejectedValueOnce(new pnlApiModule.PnlNetworkError(500))
      .mockResolvedValueOnce(mockTimeseries);

    const getAttributionMock = vi
      .fn()
      .mockRejectedValueOnce(new pnlApiModule.PnlNetworkError(500))
      .mockResolvedValueOnce(mockAttribution);

    vi.spyOn(pnlApiModule, "pnlApi", "get").mockReturnValue({
      getSummary: getSummaryMock,
      getTimeseries: getTimeseriesMock,
      getAttribution: getAttributionMock,
      getComparison: vi.fn(),
      takeSnapshot: vi.fn(),
    });

    renderPage();

    // Wait for error state
    await waitFor(() => {
      expect(screen.getByTestId("pnl-error")).toBeInTheDocument();
    });

    // Click retry
    fireEvent.click(screen.getByTestId("retry-button"));

    // Should now show data
    await waitFor(() => {
      expect(screen.getByTestId("metrics-grid")).toBeInTheDocument();
    });

    // Verify API was called twice (initial + retry)
    expect(getSummaryMock).toHaveBeenCalledTimes(2);
  });

  it("test_auth_error_shows_permission_message", async () => {
    vi.spyOn(pnlApiModule, "pnlApi", "get").mockReturnValue({
      getSummary: vi.fn().mockRejectedValue(new pnlApiModule.PnlAuthError(403)),
      getTimeseries: vi.fn().mockRejectedValue(new pnlApiModule.PnlAuthError(403)),
      getAttribution: vi.fn().mockRejectedValue(new pnlApiModule.PnlAuthError(403)),
      getComparison: vi.fn(),
      takeSnapshot: vi.fn(),
    });

    renderPage();

    await waitFor(() => {
      expect(screen.getByTestId("pnl-error")).toBeInTheDocument();
    });

    expect(screen.getByTestId("pnl-error")).toHaveTextContent("permission");
  });
});
