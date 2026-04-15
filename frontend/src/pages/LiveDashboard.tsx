/**
 * Live Trading Dashboard — real-time position, order, and P&L display.
 *
 * Responsibilities:
 * - Connect to the WebSocket endpoint for real-time position updates.
 * - Display positions table with live P&L (unrealized, realized).
 * - Show account summary (equity, cash, buying power, daily P&L).
 * - Show recent order status updates.
 * - Display connection status indicator.
 * - Color-code: green (profit), red (loss), yellow (pending).
 *
 * Does NOT:
 * - Submit or cancel orders (use the live trading API for that).
 * - Handle authentication (uses useAuth context).
 * - Manage WebSocket lifecycle directly (delegated to useWebSocket hook).
 *
 * Dependencies:
 * - useAuth: Access token and user identity.
 * - useWebSocket: WebSocket connection with auto-reconnect.
 * - React state: Local state for positions, orders, account data.
 *
 * Example:
 *   <Route path="/live/:deploymentId" element={<LiveDashboard />} />
 */

import { useCallback, useState } from "react";
import { useAuth } from "@/auth/useAuth";
import { useWebSocket } from "@/hooks/useWebSocket";
import type { WsStatus } from "@/hooks/useWebSocket";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

interface Position {
  symbol: string;
  quantity: number;
  averageEntryPrice: number;
  marketPrice: number;
  marketValue: number;
  unrealizedPnl: number;
  realizedPnl: number;
}

interface OrderUpdate {
  clientOrderId: string;
  symbol: string;
  side: string;
  status: string;
  quantity: number;
  filledQuantity: number;
  averageFillPrice: number | null;
  submittedAt: string | null;
}

interface AccountSummary {
  equity: number;
  cash: number;
  buyingPower: number;
  dailyPnl: number;
  positionsCount: number;
}

// ---------------------------------------------------------------------------
// Props
// ---------------------------------------------------------------------------

export interface LiveDashboardProps {
  /** Deployment ID to subscribe to. */
  deploymentId: string;
  /** WebSocket base URL override for testing. */
  wsBaseUrl?: string;
}

// ---------------------------------------------------------------------------
// Helpers
// ---------------------------------------------------------------------------

/** Format a number as currency. */
function formatCurrency(value: number): string {
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
    minimumFractionDigits: 2,
  }).format(value);
}

/** Get CSS class for P&L coloring. */
function pnlClass(value: number): string {
  if (value > 0) return "text-green-600";
  if (value < 0) return "text-red-600";
  return "text-surface-500";
}

/** Get CSS class for order status badge. */
function statusBadgeClass(status: string): string {
  switch (status.toLowerCase()) {
    case "filled":
      return "bg-green-100 text-green-800";
    case "cancelled":
    case "rejected":
    case "expired":
      return "bg-red-100 text-red-800";
    case "pending":
    case "submitted":
      return "bg-yellow-100 text-yellow-800";
    default:
      return "bg-surface-100 text-surface-800";
  }
}

/** Get connection status indicator. */
function connectionIndicator(status: WsStatus): { color: string; label: string } {
  switch (status) {
    case "connected":
      return { color: "bg-green-500", label: "Connected" };
    case "connecting":
      return { color: "bg-yellow-500", label: "Connecting..." };
    case "error":
      return { color: "bg-red-500", label: "Error" };
    default:
      return { color: "bg-surface-400", label: "Disconnected" };
  }
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

/**
 * LiveDashboard displays real-time trading data for a deployment.
 *
 * Connects to the WebSocket endpoint and renders:
 * - Connection status indicator
 * - Account summary cards (equity, cash, buying power, daily P&L)
 * - Positions table with live P&L
 * - Recent order updates list
 */
export default function LiveDashboard({ deploymentId, wsBaseUrl }: LiveDashboardProps) {
  const { accessToken } = useAuth();
  const [positions, setPositions] = useState<Position[]>([]);
  const [orders, setOrders] = useState<OrderUpdate[]>([]);
  const [account, setAccount] = useState<AccountSummary | null>(null);

  const baseUrl =
    wsBaseUrl ??
    `${window.location.protocol === "https:" ? "wss:" : "ws:"}//${window.location.host}`;

  const handleMessage = useCallback((data: Record<string, unknown>) => {
    const msgType = data.msg_type as string;
    const payload = (data.payload ?? {}) as Record<string, unknown>;

    switch (msgType) {
      case "position_update": {
        const rawPositions = (payload.positions ?? []) as Array<Record<string, unknown>>;
        setPositions(
          rawPositions.map((p) => ({
            symbol: String(p.symbol ?? ""),
            quantity: Number(p.quantity ?? 0),
            averageEntryPrice: Number(p.average_entry_price ?? 0),
            marketPrice: Number(p.market_price ?? 0),
            marketValue: Number(p.market_value ?? 0),
            unrealizedPnl: Number(p.unrealized_pnl ?? 0),
            realizedPnl: Number(p.realized_pnl ?? 0),
          })),
        );
        break;
      }
      case "order_update": {
        const order: OrderUpdate = {
          clientOrderId: String(payload.client_order_id ?? ""),
          symbol: String(payload.symbol ?? ""),
          side: String(payload.side ?? ""),
          status: String(payload.status ?? ""),
          quantity: Number(payload.quantity ?? 0),
          filledQuantity: Number(payload.filled_quantity ?? 0),
          averageFillPrice: payload.average_fill_price ? Number(payload.average_fill_price) : null,
          submittedAt: payload.submitted_at ? String(payload.submitted_at) : null,
        };
        setOrders((prev) => {
          // Replace existing order or prepend new one, keep max 20
          const idx = prev.findIndex((o) => o.clientOrderId === order.clientOrderId);
          if (idx >= 0) {
            const updated = [...prev];
            updated[idx] = order;
            return updated;
          }
          return [order, ...prev].slice(0, 20);
        });
        break;
      }
      case "account_update": {
        setAccount({
          equity: Number(payload.equity ?? 0),
          cash: Number(payload.cash ?? 0),
          buyingPower: Number(payload.buying_power ?? 0),
          dailyPnl: Number(payload.daily_pnl ?? 0),
          positionsCount: Number(payload.positions_count ?? 0),
        });
        break;
      }
      case "pnl_update": {
        setAccount((prev) =>
          prev
            ? {
                ...prev,
                dailyPnl: Number(payload.daily_pnl ?? prev.dailyPnl),
                equity: Number(payload.total_equity ?? prev.equity),
              }
            : null,
        );
        break;
      }
      default:
        break;
    }
  }, []);

  const { status, reconnectAttempts, reconnect } = useWebSocket({
    url: `${baseUrl}/ws/positions/${deploymentId}`,
    token: accessToken,
    onMessage: handleMessage,
  });

  const indicator = connectionIndicator(status);

  const totalUnrealizedPnl = positions.reduce((sum, p) => sum + p.unrealizedPnl, 0);

  return (
    <div className="space-y-6" data-testid="live-dashboard">
      {/* Header with connection status */}
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-2xl font-bold text-surface-900">Live Dashboard</h1>
          <p className="mt-1 text-sm text-surface-500">Deployment: {deploymentId}</p>
        </div>
        <div className="flex items-center gap-2" data-testid="connection-status">
          <div className={`h-3 w-3 rounded-full ${indicator.color}`} />
          <span className="text-sm text-surface-600">{indicator.label}</span>
          {status === "disconnected" && reconnectAttempts > 0 && (
            <button
              onClick={reconnect}
              className="ml-2 text-sm text-blue-600 hover:text-blue-800"
              data-testid="reconnect-button"
            >
              Reconnect
            </button>
          )}
        </div>
      </div>

      {/* Account Summary Cards */}
      <div
        className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4"
        data-testid="account-summary"
      >
        <div className="card">
          <p className="text-sm text-surface-500">Equity</p>
          <p className="mt-1 text-2xl font-semibold text-surface-900">
            {account ? formatCurrency(account.equity) : "—"}
          </p>
        </div>
        <div className="card">
          <p className="text-sm text-surface-500">Cash</p>
          <p className="mt-1 text-2xl font-semibold text-surface-900">
            {account ? formatCurrency(account.cash) : "—"}
          </p>
        </div>
        <div className="card">
          <p className="text-sm text-surface-500">Buying Power</p>
          <p className="mt-1 text-2xl font-semibold text-surface-900">
            {account ? formatCurrency(account.buyingPower) : "—"}
          </p>
        </div>
        <div className="card">
          <p className="text-sm text-surface-500">Daily P&amp;L</p>
          <p
            className={`mt-1 text-2xl font-semibold ${account ? pnlClass(account.dailyPnl) : "text-surface-900"}`}
          >
            {account ? formatCurrency(account.dailyPnl) : "—"}
          </p>
        </div>
      </div>

      {/* Positions Table */}
      <div className="card" data-testid="positions-table">
        <h2 className="mb-4 text-lg font-semibold text-surface-900">Positions</h2>
        {positions.length === 0 ? (
          <p className="text-sm text-surface-400">No open positions</p>
        ) : (
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead>
                <tr className="border-b border-surface-200 text-left text-surface-500">
                  <th className="pb-2 pr-4">Symbol</th>
                  <th className="pb-2 pr-4 text-right">Qty</th>
                  <th className="pb-2 pr-4 text-right">Avg Entry</th>
                  <th className="pb-2 pr-4 text-right">Mkt Price</th>
                  <th className="pb-2 pr-4 text-right">Mkt Value</th>
                  <th className="pb-2 text-right">Unrealized P&amp;L</th>
                </tr>
              </thead>
              <tbody>
                {positions.map((pos) => (
                  <tr
                    key={pos.symbol}
                    className="border-b border-surface-100"
                    data-testid={`position-row-${pos.symbol}`}
                  >
                    <td className="py-2 pr-4 font-medium text-surface-900">{pos.symbol}</td>
                    <td className="py-2 pr-4 text-right text-surface-700">{pos.quantity}</td>
                    <td className="py-2 pr-4 text-right text-surface-700">
                      {formatCurrency(pos.averageEntryPrice)}
                    </td>
                    <td className="py-2 pr-4 text-right text-surface-700">
                      {formatCurrency(pos.marketPrice)}
                    </td>
                    <td className="py-2 pr-4 text-right text-surface-700">
                      {formatCurrency(pos.marketValue)}
                    </td>
                    <td className={`py-2 text-right font-medium ${pnlClass(pos.unrealizedPnl)}`}>
                      {formatCurrency(pos.unrealizedPnl)}
                    </td>
                  </tr>
                ))}
              </tbody>
              <tfoot>
                <tr className="border-t-2 border-surface-300">
                  <td colSpan={5} className="py-2 pr-4 text-right font-medium text-surface-700">
                    Total Unrealized P&amp;L
                  </td>
                  <td className={`py-2 text-right font-bold ${pnlClass(totalUnrealizedPnl)}`}>
                    {formatCurrency(totalUnrealizedPnl)}
                  </td>
                </tr>
              </tfoot>
            </table>
          </div>
        )}
      </div>

      {/* Recent Orders */}
      <div className="card" data-testid="recent-orders">
        <h2 className="mb-4 text-lg font-semibold text-surface-900">Recent Orders</h2>
        {orders.length === 0 ? (
          <p className="text-sm text-surface-400">No recent orders</p>
        ) : (
          <div className="space-y-2">
            {orders.map((order) => (
              <div
                key={order.clientOrderId}
                className="flex items-center justify-between border-b border-surface-100 pb-2"
                data-testid={`order-row-${order.clientOrderId}`}
              >
                <div className="flex items-center gap-3">
                  <span
                    className={`inline-flex items-center rounded-full px-2 py-0.5 text-xs font-medium ${statusBadgeClass(order.status)}`}
                  >
                    {order.status}
                  </span>
                  <span className="font-medium text-surface-900">
                    {order.side.toUpperCase()} {order.quantity} {order.symbol}
                  </span>
                </div>
                <div className="text-sm text-surface-500">
                  {order.filledQuantity > 0 && (
                    <span>
                      Filled: {order.filledQuantity}
                      {order.averageFillPrice ? ` @ ${formatCurrency(order.averageFillPrice)}` : ""}
                    </span>
                  )}
                </div>
              </div>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
