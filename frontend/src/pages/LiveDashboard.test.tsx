/**
 * Unit tests for LiveDashboard component (M7 — Real-Time Position Dashboard).
 *
 * Verifies:
 *   - Renders header with deployment ID.
 *   - Displays connection status indicator.
 *   - Account summary cards show placeholder when no data.
 *   - Account summary cards populate on account_update message.
 *   - Positions table renders rows with correct P&L coloring.
 *   - Empty positions state displays "No open positions".
 *   - Orders list renders with correct status badges.
 *   - Empty orders state displays "No recent orders".
 *   - P&L update merges into existing account state.
 *   - Order updates replace existing orders by clientOrderId.
 *   - Total unrealized P&L row aggregates across positions.
 *   - Reconnect button appears when disconnected with attempts > 0.
 *
 * Dependencies:
 *   - vitest for mocking
 *   - @testing-library/react for rendering
 *   - Mock useAuth and useWebSocket hooks
 */

import { render, screen, within, act } from "@testing-library/react";
import { describe, it, expect, vi, beforeEach } from "vitest";
import LiveDashboard from "./LiveDashboard";
import type { UseWebSocketReturn, UseWebSocketOptions } from "@/hooks/useWebSocket";

// ---------------------------------------------------------------------------
// Mocks
// ---------------------------------------------------------------------------

// Track the last onMessage callback so tests can push messages
let capturedOnMessage: ((data: Record<string, unknown>) => void) | undefined;
let mockWsReturn: UseWebSocketReturn;

vi.mock("@/auth/useAuth", () => ({
  useAuth: () => ({
    accessToken: "test-jwt-token",
    user: { id: "user-001", email: "test@example.com" },
    isAuthenticated: true,
    isLoading: false,
    login: vi.fn(),
    logout: vi.fn(),
    hasScope: () => true,
  }),
}));

vi.mock("@/hooks/useWebSocket", () => ({
  useWebSocket: (opts: UseWebSocketOptions) => {
    capturedOnMessage = opts.onMessage;
    return mockWsReturn;
  },
}));

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

function sendMessage(data: Record<string, unknown>) {
  if (!capturedOnMessage) throw new Error("onMessage not captured — component not mounted?");
  act(() => {
    capturedOnMessage!(data);
  });
}

function renderDashboard(overrides?: Partial<UseWebSocketReturn>) {
  mockWsReturn = {
    status: "connected",
    lastMessage: null,
    sendMessage: vi.fn(),
    reconnect: vi.fn(),
    reconnectAttempts: 0,
    isConnected: true,
    isReconnecting: false,
    ...overrides,
  };

  return render(<LiveDashboard deploymentId="deploy-001" wsBaseUrl="ws://test-host" />);
}

// ---------------------------------------------------------------------------
// Tests
// ---------------------------------------------------------------------------

describe("LiveDashboard", () => {
  beforeEach(() => {
    capturedOnMessage = undefined;
    vi.clearAllMocks();
  });

  describe("header and connection status", () => {
    it("renders the dashboard header with deployment ID", () => {
      renderDashboard();

      expect(screen.getByText("Live Dashboard")).toBeInTheDocument();
      expect(screen.getByText("Deployment: deploy-001")).toBeInTheDocument();
    });

    it("shows connected status indicator", () => {
      renderDashboard({ status: "connected" });

      const statusEl = screen.getByTestId("connection-status");
      expect(within(statusEl).getByText("Connected")).toBeInTheDocument();
    });

    it("shows connecting status indicator", () => {
      renderDashboard({ status: "connecting" });

      const statusEl = screen.getByTestId("connection-status");
      expect(within(statusEl).getByText("Connecting...")).toBeInTheDocument();
    });

    it("shows disconnected status with reconnect button when attempts > 0", () => {
      const reconnectFn = vi.fn();
      renderDashboard({
        status: "disconnected",
        reconnectAttempts: 3,
        reconnect: reconnectFn,
      });

      const statusEl = screen.getByTestId("connection-status");
      expect(within(statusEl).getByText("Disconnected")).toBeInTheDocument();

      const btn = screen.getByTestId("reconnect-button");
      expect(btn).toBeInTheDocument();
      btn.click();
      expect(reconnectFn).toHaveBeenCalledOnce();
    });

    it("hides reconnect button when disconnected with zero attempts", () => {
      renderDashboard({ status: "disconnected", reconnectAttempts: 0 });

      expect(screen.queryByTestId("reconnect-button")).not.toBeInTheDocument();
    });

    it("shows error status indicator", () => {
      renderDashboard({ status: "error" });

      const statusEl = screen.getByTestId("connection-status");
      expect(within(statusEl).getByText("Error")).toBeInTheDocument();
    });
  });

  describe("account summary cards", () => {
    it("shows placeholder dashes when no account data", () => {
      renderDashboard();

      const summary = screen.getByTestId("account-summary");
      const dashes = within(summary).getAllByText("—");
      // Four cards: Equity, Cash, Buying Power, Daily P&L
      expect(dashes).toHaveLength(4);
    });

    it("populates cards on account_update message", () => {
      renderDashboard();

      sendMessage({
        msg_type: "account_update",
        payload: {
          equity: 125000.5,
          cash: 50000.0,
          buying_power: 200000.0,
          daily_pnl: 1250.75,
          positions_count: 5,
        },
      });

      const summary = screen.getByTestId("account-summary");
      expect(within(summary).getByText("$125,000.50")).toBeInTheDocument();
      expect(within(summary).getByText("$50,000.00")).toBeInTheDocument();
      expect(within(summary).getByText("$200,000.00")).toBeInTheDocument();
      expect(within(summary).getByText("$1,250.75")).toBeInTheDocument();
    });

    it("merges pnl_update into existing account state", () => {
      renderDashboard();

      // First set up account data
      sendMessage({
        msg_type: "account_update",
        payload: {
          equity: 100000,
          cash: 50000,
          buying_power: 200000,
          daily_pnl: 500,
          positions_count: 2,
        },
      });

      // Then send a PnL update
      sendMessage({
        msg_type: "pnl_update",
        payload: {
          daily_pnl: 1500.25,
          total_equity: 101000,
        },
      });

      const summary = screen.getByTestId("account-summary");
      // Equity should be updated
      expect(within(summary).getByText("$101,000.00")).toBeInTheDocument();
      // Daily P&L should be updated
      expect(within(summary).getByText("$1,500.25")).toBeInTheDocument();
      // Cash should remain unchanged
      expect(within(summary).getByText("$50,000.00")).toBeInTheDocument();
    });

    it("ignores pnl_update when no existing account state", () => {
      renderDashboard();

      sendMessage({
        msg_type: "pnl_update",
        payload: { daily_pnl: 1500, total_equity: 101000 },
      });

      // Should still show dashes
      const summary = screen.getByTestId("account-summary");
      const dashes = within(summary).getAllByText("—");
      expect(dashes).toHaveLength(4);
    });
  });

  describe("positions table", () => {
    it("shows 'No open positions' when empty", () => {
      renderDashboard();

      const table = screen.getByTestId("positions-table");
      expect(within(table).getByText("No open positions")).toBeInTheDocument();
    });

    it("renders position rows on position_update", () => {
      renderDashboard();

      sendMessage({
        msg_type: "position_update",
        payload: {
          positions: [
            {
              symbol: "AAPL",
              quantity: 100,
              average_entry_price: 150.0,
              market_price: 155.0,
              market_value: 15500.0,
              unrealized_pnl: 500.0,
              realized_pnl: 0,
            },
            {
              symbol: "TSLA",
              quantity: 50,
              average_entry_price: 250.0,
              market_price: 240.0,
              market_value: 12000.0,
              unrealized_pnl: -500.0,
              realized_pnl: 100.0,
            },
          ],
        },
      });

      expect(screen.getByTestId("position-row-AAPL")).toBeInTheDocument();
      expect(screen.getByTestId("position-row-TSLA")).toBeInTheDocument();

      // Check AAPL row values
      const aaplRow = screen.getByTestId("position-row-AAPL");
      expect(within(aaplRow).getByText("AAPL")).toBeInTheDocument();
      expect(within(aaplRow).getByText("100")).toBeInTheDocument();
      expect(within(aaplRow).getByText("$500.00")).toBeInTheDocument();

      // Check TSLA row shows negative P&L
      const tslaRow = screen.getByTestId("position-row-TSLA");
      expect(within(tslaRow).getByText("-$500.00")).toBeInTheDocument();
    });

    it("applies green class to positive P&L", () => {
      renderDashboard();

      sendMessage({
        msg_type: "position_update",
        payload: {
          positions: [
            {
              symbol: "AAPL",
              quantity: 100,
              average_entry_price: 150,
              market_price: 155,
              market_value: 15500,
              unrealized_pnl: 500,
              realized_pnl: 0,
            },
          ],
        },
      });

      const aaplRow = screen.getByTestId("position-row-AAPL");
      // Find the cell with $500.00 — the P&L cell should have text-green-600
      const pnlCell = within(aaplRow).getByText("$500.00");
      expect(pnlCell.className).toContain("text-green-600");
    });

    it("applies red class to negative P&L", () => {
      renderDashboard();

      sendMessage({
        msg_type: "position_update",
        payload: {
          positions: [
            {
              symbol: "TSLA",
              quantity: 50,
              average_entry_price: 250,
              market_price: 240,
              market_value: 12000,
              unrealized_pnl: -500,
              realized_pnl: 0,
            },
          ],
        },
      });

      const tslaRow = screen.getByTestId("position-row-TSLA");
      const pnlCell = within(tslaRow).getByText("-$500.00");
      expect(pnlCell.className).toContain("text-red-600");
    });

    it("calculates total unrealized P&L across positions", () => {
      renderDashboard();

      sendMessage({
        msg_type: "position_update",
        payload: {
          positions: [
            {
              symbol: "AAPL",
              quantity: 100,
              average_entry_price: 150,
              market_price: 155,
              market_value: 15500,
              unrealized_pnl: 500,
              realized_pnl: 0,
            },
            {
              symbol: "TSLA",
              quantity: 50,
              average_entry_price: 250,
              market_price: 248,
              market_value: 12400,
              unrealized_pnl: -100,
              realized_pnl: 0,
            },
          ],
        },
      });

      // Total unrealized P&L: 500 + (-100) = 400
      const table = screen.getByTestId("positions-table");
      expect(within(table).getByText("$400.00")).toBeInTheDocument();
    });
  });

  describe("recent orders", () => {
    it("shows 'No recent orders' when empty", () => {
      renderDashboard();

      const orders = screen.getByTestId("recent-orders");
      expect(within(orders).getByText("No recent orders")).toBeInTheDocument();
    });

    it("renders order rows on order_update messages", () => {
      renderDashboard();

      sendMessage({
        msg_type: "order_update",
        payload: {
          client_order_id: "ord-001",
          symbol: "AAPL",
          side: "buy",
          status: "filled",
          quantity: 100,
          filled_quantity: 100,
          average_fill_price: 155.5,
          submitted_at: "2025-01-15T10:30:00Z",
        },
      });

      const orderRow = screen.getByTestId("order-row-ord-001");
      expect(orderRow).toBeInTheDocument();
      expect(within(orderRow).getByText("filled")).toBeInTheDocument();
      expect(within(orderRow).getByText("BUY 100 AAPL")).toBeInTheDocument();
      expect(within(orderRow).getByText(/Filled: 100/)).toBeInTheDocument();
      expect(within(orderRow).getByText(/\$155\.50/)).toBeInTheDocument();
    });

    it("applies green badge to filled orders", () => {
      renderDashboard();

      sendMessage({
        msg_type: "order_update",
        payload: {
          client_order_id: "ord-001",
          symbol: "AAPL",
          side: "buy",
          status: "filled",
          quantity: 100,
          filled_quantity: 100,
          average_fill_price: 155.5,
          submitted_at: null,
        },
      });

      const orderRow = screen.getByTestId("order-row-ord-001");
      const badge = within(orderRow).getByText("filled");
      expect(badge.className).toContain("bg-green-100");
    });

    it("applies red badge to cancelled orders", () => {
      renderDashboard();

      sendMessage({
        msg_type: "order_update",
        payload: {
          client_order_id: "ord-002",
          symbol: "TSLA",
          side: "sell",
          status: "cancelled",
          quantity: 50,
          filled_quantity: 0,
          average_fill_price: null,
          submitted_at: null,
        },
      });

      const orderRow = screen.getByTestId("order-row-ord-002");
      const badge = within(orderRow).getByText("cancelled");
      expect(badge.className).toContain("bg-red-100");
    });

    it("applies yellow badge to pending orders", () => {
      renderDashboard();

      sendMessage({
        msg_type: "order_update",
        payload: {
          client_order_id: "ord-003",
          symbol: "MSFT",
          side: "buy",
          status: "pending",
          quantity: 25,
          filled_quantity: 0,
          average_fill_price: null,
          submitted_at: null,
        },
      });

      const orderRow = screen.getByTestId("order-row-ord-003");
      const badge = within(orderRow).getByText("pending");
      expect(badge.className).toContain("bg-yellow-100");
    });

    it("replaces existing order by clientOrderId", () => {
      renderDashboard();

      // Submit an order
      sendMessage({
        msg_type: "order_update",
        payload: {
          client_order_id: "ord-001",
          symbol: "AAPL",
          side: "buy",
          status: "pending",
          quantity: 100,
          filled_quantity: 0,
          average_fill_price: null,
          submitted_at: null,
        },
      });

      expect(
        within(screen.getByTestId("order-row-ord-001")).getByText("pending"),
      ).toBeInTheDocument();

      // Update to filled
      sendMessage({
        msg_type: "order_update",
        payload: {
          client_order_id: "ord-001",
          symbol: "AAPL",
          side: "buy",
          status: "filled",
          quantity: 100,
          filled_quantity: 100,
          average_fill_price: 155.0,
          submitted_at: null,
        },
      });

      // Should now show filled, not pending
      expect(
        within(screen.getByTestId("order-row-ord-001")).getByText("filled"),
      ).toBeInTheDocument();
      expect(
        within(screen.getByTestId("order-row-ord-001")).queryByText("pending"),
      ).not.toBeInTheDocument();
    });

    it("does not show fill details when filledQuantity is zero", () => {
      renderDashboard();

      sendMessage({
        msg_type: "order_update",
        payload: {
          client_order_id: "ord-004",
          symbol: "GOOG",
          side: "buy",
          status: "submitted",
          quantity: 10,
          filled_quantity: 0,
          average_fill_price: null,
          submitted_at: null,
        },
      });

      const orderRow = screen.getByTestId("order-row-ord-004");
      expect(within(orderRow).queryByText(/Filled:/)).not.toBeInTheDocument();
    });
  });

  describe("unknown message types", () => {
    it("does not crash on unknown msg_type", () => {
      renderDashboard();

      // Should not throw
      sendMessage({ msg_type: "unknown_event", payload: { foo: "bar" } });

      // Dashboard should still be rendered
      expect(screen.getByTestId("live-dashboard")).toBeInTheDocument();
    });
  });
});
