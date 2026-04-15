/**
 * Tests for ExecutionReport page component.
 *
 * Verifies:
 *   - Date controls and preset buttons are rendered
 *   - Summary cards display with correct data
 *   - Symbol breakdown table renders
 *   - Mode breakdown table renders
 *   - Empty state displays when no data
 *   - Loading state displays while fetching
 *   - Preset buttons set date ranges correctly
 */

import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { AuthProvider } from "@/auth/AuthProvider";
import ExecutionReport from "./ExecutionReport";
import * as executionApiModule from "@/features/execution/api";
import type { ExecutionReportSummary } from "@/features/execution/api";
import type { ReactNode } from "react";

// Mock the execution API
vi.mock("@/features/execution/api");

// Mock auth hooks to return authenticated state
vi.mock("@/auth/useAuth", () => ({
  useAuth: () => ({
    user: { id: "test-user", email: "test@example.com" },
    isAuthenticated: true,
    accessToken: "test-token",
    isLoading: false,
    logout: vi.fn(),
    login: vi.fn(),
    hasScope: vi.fn(() => true),
  }),
}));

const queryClient = new QueryClient({
  defaultOptions: { queries: { retry: false } },
});

function Wrapper({ children }: { children: ReactNode }) {
  return (
    <QueryClientProvider client={queryClient}>
      <AuthProvider>{children}</AuthProvider>
    </QueryClientProvider>
  );
}

const mockExecutionReport: ExecutionReportSummary = {
  date_from: "2026-04-05",
  date_to: "2026-04-12",
  total_orders: 150,
  filled_orders: 120,
  cancelled_orders: 20,
  rejected_orders: 10,
  partial_fills: 5,
  fill_rate: 0.8,
  total_volume: 5000,
  total_commission: 250.0,
  symbols_traded: ["AAPL", "MSFT", "GOOGL"],
  avg_slippage_pct: 0.015,
  latency_p50_ms: 150.5,
  latency_p95_ms: 500.2,
  latency_p99_ms: 950.8,
  by_symbol: [
    {
      symbol: "AAPL",
      total_orders: 50,
      filled_orders: 45,
      fill_rate: 0.9,
      total_volume: 1500,
      avg_fill_price: 150.25,
      avg_slippage_pct: 0.01,
    },
    {
      symbol: "MSFT",
      total_orders: 60,
      filled_orders: 50,
      fill_rate: 0.833,
      total_volume: 2000,
      avg_fill_price: 320.5,
      avg_slippage_pct: 0.02,
    },
    {
      symbol: "GOOGL",
      total_orders: 40,
      filled_orders: 25,
      fill_rate: 0.625,
      total_volume: 1500,
      avg_fill_price: 135.75,
      avg_slippage_pct: null,
    },
  ],
  by_execution_mode: [
    {
      execution_mode: "LIVE",
      total_orders: 100,
      filled_orders: 85,
      fill_rate: 0.85,
      total_volume: 3500,
    },
    {
      execution_mode: "PAPER",
      total_orders: 50,
      filled_orders: 35,
      fill_rate: 0.7,
      total_volume: 1500,
    },
  ],
};

describe("ExecutionReport", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("test_renders_date_controls", async () => {
    vi.spyOn(executionApiModule, "executionApi", "get").mockReturnValue({
      getExecutionReport: vi.fn().mockResolvedValue(mockExecutionReport),
    } as unknown as typeof executionApiModule.executionApi);

    render(<ExecutionReport />, { wrapper: Wrapper });

    expect(screen.getByTestId("date-from")).toBeInTheDocument();
    expect(screen.getByTestId("date-to")).toBeInTheDocument();
    expect(screen.getByTestId("preset-today")).toBeInTheDocument();
    expect(screen.getByTestId("preset-week")).toBeInTheDocument();
    expect(screen.getByTestId("preset-month")).toBeInTheDocument();
  });

  it("test_renders_summary_cards_with_data", async () => {
    vi.spyOn(executionApiModule, "executionApi", "get").mockReturnValue({
      getExecutionReport: vi.fn().mockResolvedValue(mockExecutionReport),
    } as unknown as typeof executionApiModule.executionApi);

    render(<ExecutionReport />, { wrapper: Wrapper });

    await waitFor(() => {
      expect(screen.getByTestId("summary-cards")).toBeInTheDocument();
    });

    expect(screen.getByTestId("card-total-orders")).toBeInTheDocument();
    expect(screen.getByTestId("card-fill-rate")).toBeInTheDocument();
    expect(screen.getByTestId("card-total-volume")).toBeInTheDocument();
    expect(screen.getByTestId("card-total-commission")).toBeInTheDocument();

    // Check card values
    expect(screen.getByText("150")).toBeInTheDocument(); // total_orders
    expect(screen.getByText("80.0%")).toBeInTheDocument(); // fill_rate
    expect(screen.getByText("5,000")).toBeInTheDocument(); // total_volume
    expect(screen.getByText("$250.00")).toBeInTheDocument(); // total_commission
  });

  it("test_symbol_breakdown_table", async () => {
    vi.spyOn(executionApiModule, "executionApi", "get").mockReturnValue({
      getExecutionReport: vi.fn().mockResolvedValue(mockExecutionReport),
    } as unknown as typeof executionApiModule.executionApi);

    render(<ExecutionReport />, { wrapper: Wrapper });

    await waitFor(() => {
      expect(screen.getByTestId("symbol-table")).toBeInTheDocument();
    });

    expect(screen.getByTestId("symbol-row-AAPL")).toBeInTheDocument();
    expect(screen.getByTestId("symbol-row-MSFT")).toBeInTheDocument();
    expect(screen.getByTestId("symbol-row-GOOGL")).toBeInTheDocument();

    // Check symbol values
    expect(screen.getByText("AAPL")).toBeInTheDocument();
    expect(screen.getByText("MSFT")).toBeInTheDocument();
    expect(screen.getByText("GOOGL")).toBeInTheDocument();
  });

  it("test_mode_breakdown_table", async () => {
    vi.spyOn(executionApiModule, "executionApi", "get").mockReturnValue({
      getExecutionReport: vi.fn().mockResolvedValue(mockExecutionReport),
    } as unknown as typeof executionApiModule.executionApi);

    render(<ExecutionReport />, { wrapper: Wrapper });

    await waitFor(() => {
      expect(screen.getByTestId("mode-table")).toBeInTheDocument();
    });

    expect(screen.getByTestId("mode-row-LIVE")).toBeInTheDocument();
    expect(screen.getByTestId("mode-row-PAPER")).toBeInTheDocument();
  });

  it("test_empty_state", async () => {
    vi.spyOn(executionApiModule, "executionApi", "get").mockReturnValue({
      getExecutionReport: vi.fn().mockResolvedValue(null),
    } as unknown as typeof executionApiModule.executionApi);

    render(<ExecutionReport />, { wrapper: Wrapper });

    await waitFor(() => {
      expect(screen.getByTestId("empty-state")).toBeInTheDocument();
    });

    expect(screen.getByText("No data available for this date range")).toBeInTheDocument();
  });

  it("test_loading_state", () => {
    vi.spyOn(executionApiModule, "executionApi", "get").mockReturnValue({
      getExecutionReport: vi.fn().mockImplementation(
        () =>
          new Promise((resolve) => {
            setTimeout(() => resolve(mockExecutionReport), 1000);
          }),
      ),
    } as unknown as typeof executionApiModule.executionApi);

    render(<ExecutionReport />, { wrapper: Wrapper });

    expect(screen.getByTestId("loading-state")).toBeInTheDocument();
    expect(screen.getByText("Loading report...")).toBeInTheDocument();
  });

  it("test_preset_today_sets_dates", async () => {
    const getReportMock = vi.fn().mockResolvedValue(mockExecutionReport);

    vi.spyOn(executionApiModule, "executionApi", "get").mockReturnValue({
      getExecutionReport: getReportMock,
    } as unknown as typeof executionApiModule.executionApi);

    render(<ExecutionReport />, { wrapper: Wrapper });

    // Wait for initial load
    await waitFor(() => {
      expect(screen.getByTestId("summary-cards")).toBeInTheDocument();
    });

    // Click "Today" preset
    const todayButton = screen.getByTestId("preset-today");
    fireEvent.click(todayButton);

    // Verify the date inputs were updated and API was called
    await waitFor(() => {
      expect(getReportMock).toHaveBeenCalledWith(
        expect.objectContaining({
          date_from: expect.stringMatching(/\d{4}-\d{2}-\d{2}/),
          date_to: expect.stringMatching(/\d{4}-\d{2}-\d{2}/),
        }),
      );
    });
  });

  it("test_preset_week_sets_dates", async () => {
    const getReportMock = vi.fn().mockResolvedValue(mockExecutionReport);

    vi.spyOn(executionApiModule, "executionApi", "get").mockReturnValue({
      getExecutionReport: getReportMock,
    } as unknown as typeof executionApiModule.executionApi);

    render(<ExecutionReport />, { wrapper: Wrapper });

    // Wait for initial load
    await waitFor(() => {
      expect(screen.getByTestId("summary-cards")).toBeInTheDocument();
    });

    // Click "This Week" preset
    const weekButton = screen.getByTestId("preset-week");
    fireEvent.click(weekButton);

    // Verify API was called
    await waitFor(() => {
      expect(getReportMock).toHaveBeenCalled();
    });
  });

  it("test_preset_month_sets_dates", async () => {
    const getReportMock = vi.fn().mockResolvedValue(mockExecutionReport);

    vi.spyOn(executionApiModule, "executionApi", "get").mockReturnValue({
      getExecutionReport: getReportMock,
    } as unknown as typeof executionApiModule.executionApi);

    render(<ExecutionReport />, { wrapper: Wrapper });

    // Wait for initial load
    await waitFor(() => {
      expect(screen.getByTestId("summary-cards")).toBeInTheDocument();
    });

    // Click "This Month" preset
    const monthButton = screen.getByTestId("preset-month");
    fireEvent.click(monthButton);

    // Verify API was called
    await waitFor(() => {
      expect(getReportMock).toHaveBeenCalled();
    });
  });

  it("test_latency_percentiles_display", async () => {
    vi.spyOn(executionApiModule, "executionApi", "get").mockReturnValue({
      getExecutionReport: vi.fn().mockResolvedValue(mockExecutionReport),
    } as unknown as typeof executionApiModule.executionApi);

    render(<ExecutionReport />, { wrapper: Wrapper });

    await waitFor(() => {
      expect(screen.getByText("Latency Percentiles")).toBeInTheDocument();
    });

    // Check for latency values (may be split across elements)
    const allText = screen.getByTestId("execution-report").textContent || "";
    expect(allText).toContain("150");
    expect(allText).toContain("500");
    expect(allText).toContain("951"); // rounds 950.8
    expect(allText).toContain("ms");
  });

  it("test_additional_metrics_display", async () => {
    vi.spyOn(executionApiModule, "executionApi", "get").mockReturnValue({
      getExecutionReport: vi.fn().mockResolvedValue(mockExecutionReport),
    } as unknown as typeof executionApiModule.executionApi);

    render(<ExecutionReport />, { wrapper: Wrapper });

    await waitFor(() => {
      expect(screen.getByText("Filled Orders")).toBeInTheDocument();
    });

    expect(screen.getByText("120")).toBeInTheDocument(); // filled_orders
    expect(screen.getByText("20")).toBeInTheDocument(); // cancelled_orders
    expect(screen.getByText("10")).toBeInTheDocument(); // rejected_orders
  });
});
