/**
 * Tests for OrderHistory page component.
 *
 * Verifies:
 *   - Filter controls are rendered
 *   - Order table displays data correctly
 *   - Status badges have correct colors
 *   - Pagination controls work
 *   - Empty state displays when no data
 *   - Loading state displays while fetching
 *   - CSV export button is present
 *   - Sort header clicks trigger re-fetch with sort params
 */

import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { AuthProvider } from "@/auth/AuthProvider";
import OrderHistory from "./OrderHistory";
import * as executionApiModule from "@/features/execution/api";
import type { OrderHistoryPage } from "@/features/execution/api";
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

const mockOrderPage: OrderHistoryPage = {
  items: [
    {
      order_id: "order-1",
      client_order_id: "client-1",
      broker_order_id: "broker-1",
      deployment_id: "deploy-1",
      strategy_id: "strat-1",
      symbol: "AAPL",
      side: "BUY",
      order_type: "LIMIT",
      quantity: 100,
      filled_quantity: 100,
      average_fill_price: 150.25,
      limit_price: 150.5,
      stop_price: null,
      status: "filled",
      time_in_force: "GTC",
      execution_mode: "LIVE",
      correlation_id: "corr-1",
      submitted_at: "2026-04-12T10:00:00Z",
      filled_at: "2026-04-12T10:01:00Z",
      cancelled_at: null,
      rejected_reason: null,
      created_at: "2026-04-12T09:59:00Z",
      fills: [
        {
          fill_id: "fill-1",
          price: 150.25,
          quantity: 100,
          commission: 5.0,
          filled_at: "2026-04-12T10:01:00Z",
          broker_execution_id: "exec-1",
        },
      ],
    },
    {
      order_id: "order-2",
      client_order_id: "client-2",
      broker_order_id: null,
      deployment_id: "deploy-1",
      strategy_id: "strat-1",
      symbol: "MSFT",
      side: "SELL",
      order_type: "MARKET",
      quantity: 50,
      filled_quantity: 0,
      average_fill_price: null,
      limit_price: null,
      stop_price: null,
      status: "cancelled",
      time_in_force: "IOC",
      execution_mode: "PAPER",
      correlation_id: "corr-2",
      submitted_at: "2026-04-12T11:00:00Z",
      filled_at: null,
      cancelled_at: "2026-04-12T11:05:00Z",
      rejected_reason: null,
      created_at: "2026-04-12T10:59:00Z",
      fills: [],
    },
  ],
  total: 2,
  page: 1,
  page_size: 50,
  total_pages: 1,
};

describe("OrderHistory", () => {
  beforeEach(() => {
    vi.clearAllMocks();
  });

  it("test_renders_filter_controls", async () => {
    vi.spyOn(executionApiModule, "executionApi", "get").mockReturnValue({
      getOrderHistory: vi.fn().mockResolvedValue(mockOrderPage),
    } as unknown as typeof executionApiModule.executionApi);

    render(<OrderHistory />, { wrapper: Wrapper });

    expect(screen.getByTestId("filter-symbol")).toBeInTheDocument();
    expect(screen.getByTestId("filter-side")).toBeInTheDocument();
    expect(screen.getByTestId("filter-status")).toBeInTheDocument();
    expect(screen.getByTestId("filter-mode")).toBeInTheDocument();
    expect(screen.getByTestId("filter-date-from")).toBeInTheDocument();
    expect(screen.getByTestId("filter-date-to")).toBeInTheDocument();
    expect(screen.getByTestId("search-button")).toBeInTheDocument();
    expect(screen.getByTestId("export-csv-button")).toBeInTheDocument();
  });

  it("test_renders_order_table_with_data", async () => {
    vi.spyOn(executionApiModule, "executionApi", "get").mockReturnValue({
      getOrderHistory: vi.fn().mockResolvedValue(mockOrderPage),
    } as unknown as typeof executionApiModule.executionApi);

    render(<OrderHistory />, { wrapper: Wrapper });

    await waitFor(() => {
      expect(screen.getByTestId("order-table")).toBeInTheDocument();
    });

    expect(screen.getByText("AAPL")).toBeInTheDocument();
    expect(screen.getByText("MSFT")).toBeInTheDocument();
    expect(screen.getByText("BUY")).toBeInTheDocument();
    expect(screen.getByText("SELL")).toBeInTheDocument();
  });

  it("test_status_badge_colors", async () => {
    vi.spyOn(executionApiModule, "executionApi", "get").mockReturnValue({
      getOrderHistory: vi.fn().mockResolvedValue(mockOrderPage),
    } as unknown as typeof executionApiModule.executionApi);

    render(<OrderHistory />, { wrapper: Wrapper });

    await waitFor(() => {
      expect(screen.getByTestId("order-table")).toBeInTheDocument();
    });

    // Find filled status badge (should be green)
    const filledBadge = screen.getByText("filled");
    expect(filledBadge).toHaveClass("bg-green-100");

    // Find cancelled status badge (should be red)
    const cancelledBadge = screen.getByText("cancelled");
    expect(cancelledBadge).toHaveClass("bg-red-100");
  });

  it("test_pagination_controls", async () => {
    const multiPageResult: OrderHistoryPage = {
      ...mockOrderPage,
      total: 150,
      total_pages: 3,
      page: 1,
    };

    vi.spyOn(executionApiModule, "executionApi", "get").mockReturnValue({
      getOrderHistory: vi.fn().mockResolvedValue(multiPageResult),
    } as unknown as typeof executionApiModule.executionApi);

    render(<OrderHistory />, { wrapper: Wrapper });

    await waitFor(() => {
      expect(screen.getByTestId("pagination")).toBeInTheDocument();
    });

    expect(screen.getByTestId("prev-page")).toBeInTheDocument();
    expect(screen.getByTestId("next-page")).toBeInTheDocument();
    expect(screen.getByTestId("page-info")).toBeInTheDocument();
    expect(screen.getByText(/Page 1 of 3/)).toBeInTheDocument();
  });

  it("test_empty_state", async () => {
    const emptyResult: OrderHistoryPage = {
      items: [],
      total: 0,
      page: 1,
      page_size: 50,
      total_pages: 0,
    };

    vi.spyOn(executionApiModule, "executionApi", "get").mockReturnValue({
      getOrderHistory: vi.fn().mockResolvedValue(emptyResult),
    } as unknown as typeof executionApiModule.executionApi);

    render(<OrderHistory />, { wrapper: Wrapper });

    await waitFor(() => {
      expect(screen.getByTestId("empty-state")).toBeInTheDocument();
    });

    expect(screen.getByText("No orders found")).toBeInTheDocument();
  });

  it("test_loading_state", () => {
    vi.spyOn(executionApiModule, "executionApi", "get").mockReturnValue({
      getOrderHistory: vi.fn().mockImplementation(
        () =>
          new Promise((resolve) => {
            setTimeout(() => resolve(mockOrderPage), 1000);
          }),
      ),
    } as unknown as typeof executionApiModule.executionApi);

    render(<OrderHistory />, { wrapper: Wrapper });

    expect(screen.getByTestId("loading-state")).toBeInTheDocument();
    expect(screen.getByText("Loading orders...")).toBeInTheDocument();
  });

  it("test_csv_export_button_present", async () => {
    vi.spyOn(executionApiModule, "executionApi", "get").mockReturnValue({
      getOrderHistory: vi.fn().mockResolvedValue(mockOrderPage),
      exportOrdersCsv: vi.fn().mockResolvedValue(new Blob(["csv data"])),
    } as unknown as typeof executionApiModule.executionApi);

    render(<OrderHistory />, { wrapper: Wrapper });

    await waitFor(() => {
      expect(screen.getByTestId("export-csv-button")).toBeInTheDocument();
    });
  });

  it("test_sort_header_click", async () => {
    const getOrderHistoryMock = vi.fn().mockResolvedValue(mockOrderPage);

    vi.spyOn(executionApiModule, "executionApi", "get").mockReturnValue({
      getOrderHistory: getOrderHistoryMock,
    } as unknown as typeof executionApiModule.executionApi);

    render(<OrderHistory />, { wrapper: Wrapper });

    await waitFor(() => {
      expect(screen.getByTestId("order-table")).toBeInTheDocument();
    });

    const sortButton = screen.getByTestId("sort-header-symbol");
    fireEvent.click(sortButton);

    await waitFor(() => {
      // Verify the API was called with sort params
      expect(getOrderHistoryMock).toHaveBeenCalled();
      const lastCall = getOrderHistoryMock.mock.calls[getOrderHistoryMock.mock.calls.length - 1];
      expect(lastCall[0]).toHaveProperty("sort_by", "symbol");
    });
  });

  it("test_row_expansion_shows_fills", async () => {
    vi.spyOn(executionApiModule, "executionApi", "get").mockReturnValue({
      getOrderHistory: vi.fn().mockResolvedValue(mockOrderPage),
    } as unknown as typeof executionApiModule.executionApi);

    render(<OrderHistory />, { wrapper: Wrapper });

    await waitFor(() => {
      expect(screen.getByTestId("order-table")).toBeInTheDocument();
    });

    // Find and click expand button for first order
    const expandButtons = screen.getAllByText("▶");
    fireEvent.click(expandButtons[0]);

    // Check that fills are now displayed
    await waitFor(() => {
      expect(screen.getByText("Fills:")).toBeInTheDocument();
    });
  });
});
