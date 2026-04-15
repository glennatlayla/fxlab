/**
 * DeploymentDetail — full paper trading deployment details and controls.
 *
 * Purpose:
 *   Display complete details of a paper trading deployment including account
 *   summary, positions list, orders list, and freeze/unfreeze toggle.
 *   Designed as a BottomSheet or modal overlay.
 *
 * Responsibilities:
 *   - Display account summary: equity, P&L breakdown, date started.
 *   - Display positions list with symbol, side, quantity, entry/current price, P&L.
 *   - Display orders list with symbol, type, quantity, price, status.
 *   - Show freeze/unfreeze button based on current status.
 *   - Handle freeze/unfreeze button clicks (delegate to parent via callbacks).
 *   - Show loading state while operation is in flight.
 *   - Render empty states when no positions or orders.
 *
 * Does NOT:
 *   - Fetch data (receives positions and orders as props).
 *   - Manage internal state (parent manages isLoading, etc).
 *   - Navigate (parent handles routing).
 *
 * Dependencies:
 *   - PaperDeploymentSummary, PaperPosition, PaperOrder types.
 *   - Lucide-react icons.
 *
 * Example:
 *   <DeploymentDetail
 *     deployment={deployment}
 *     positions={positions}
 *     orders={orders}
 *     isLoading={isLoading}
 *     onFreeze={() => handleFreeze()}
 *     onUnfreeze={() => handleUnfreeze()}
 *   />
 */

import { Loader2 } from "lucide-react";
import type {
  PaperDeploymentSummary,
  PaperPosition,
  PaperOrder,
} from "../types";
import { PAPER_DEPLOYMENT_STATUS } from "../types";

interface DeploymentDetailProps {
  /** The paper trading deployment. */
  deployment: PaperDeploymentSummary;
  /** List of open positions. */
  positions: PaperPosition[];
  /** List of orders (pending and completed). */
  orders: PaperOrder[];
  /** Whether a freeze/unfreeze operation is in progress. */
  isLoading: boolean;
  /** Callback to freeze the deployment. */
  onFreeze: () => void;
  /** Callback to unfreeze the deployment. */
  onUnfreeze: () => void;
  /** Optional additional CSS class names. */
  className?: string;
}

/**
 * Format a number as currency string with two decimal places.
 */
function formatCurrency(value: number): string {
  return new Intl.NumberFormat("en-US", {
    style: "currency",
    currency: "USD",
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  }).format(value);
}

/**
 * Render the full deployment detail view.
 */
export function DeploymentDetail({
  deployment,
  positions,
  orders,
  isLoading,
  onFreeze,
  onUnfreeze,
  className = "",
}: DeploymentDetailProps) {
  const isFrozen = deployment.status === PAPER_DEPLOYMENT_STATUS.FROZEN;
  const isActive = deployment.status === PAPER_DEPLOYMENT_STATUS.ACTIVE;

  return (
    <div
      className={`flex flex-col gap-4 rounded-lg bg-gray-800 p-4 ${className}`.trim()}
    >
      {/* Header: Strategy name and status */}
      <div className="border-b border-gray-700 pb-3">
        <h2 className="text-lg font-semibold text-gray-100">
          {deployment.strategy_name}
        </h2>
        <p className="text-xs text-gray-500">
          Status: <span className="text-gray-400">{deployment.status}</span>
        </p>
      </div>

      {/* Account Summary Card */}
      <div className="rounded-lg bg-gray-700 p-3">
        <h3 className="mb-2 text-sm font-semibold text-gray-100">
          Account Summary
        </h3>
        <div className="grid grid-cols-2 gap-3 text-xs">
          <div>
            <span className="text-gray-500">Current Equity</span>
            <div className="text-sm font-semibold text-gray-100">
              {formatCurrency(deployment.equity)}
            </div>
          </div>
          <div>
            <span className="text-gray-500">Initial Equity</span>
            <div className="text-sm font-semibold text-gray-100">
              {formatCurrency(deployment.initial_equity)}
            </div>
          </div>
          <div>
            <span className="text-gray-500">Total P&L</span>
            <div
              className={`text-sm font-semibold ${
                deployment.total_pnl >= 0
                  ? "text-green-400"
                  : "text-red-400"
              }`}
            >
              {formatCurrency(deployment.total_pnl)}
            </div>
          </div>
          <div>
            <span className="text-gray-500">Unrealized P&L</span>
            <div
              className={`text-sm font-semibold ${
                deployment.unrealized_pnl >= 0
                  ? "text-green-400"
                  : "text-red-400"
              }`}
            >
              {formatCurrency(deployment.unrealized_pnl)}
            </div>
          </div>
        </div>
      </div>

      {/* Positions Section */}
      <div>
        <h3 className="mb-2 text-sm font-semibold text-gray-100">
          Positions ({positions.length})
        </h3>
        {positions.length === 0 ? (
          <div className="rounded bg-gray-700 p-2 text-xs text-gray-400">
            No open positions
          </div>
        ) : (
          <div className="space-y-2">
            {positions.map((position) => (
              <div
                key={position.symbol}
                className="rounded bg-gray-700 p-2 text-xs"
              >
                <div className="mb-1 flex items-center justify-between">
                  <span className="font-semibold text-gray-100">
                    {position.symbol}
                  </span>
                  <span
                    className={`rounded px-1.5 py-0.5 text-xs font-semibold ${
                      position.side === "long"
                        ? "bg-green-500/20 text-green-300"
                        : "bg-red-500/20 text-red-300"
                    }`}
                  >
                    {position.side}
                  </span>
                </div>
                <div className="grid grid-cols-2 gap-1 text-gray-400">
                  <span>Qty: {position.quantity}</span>
                  <span>Entry: {formatCurrency(position.entry_price)}</span>
                  <span>Current: {formatCurrency(position.current_price)}</span>
                  <span
                    className={`font-semibold ${
                      position.unrealized_pnl >= 0
                        ? "text-green-400"
                        : "text-red-400"
                    }`}
                  >
                    P&L: {formatCurrency(position.unrealized_pnl)} (
                    {position.pnl_pct.toFixed(2)}%)
                  </span>
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Orders Section */}
      <div>
        <h3 className="mb-2 text-sm font-semibold text-gray-100">
          Orders ({orders.length})
        </h3>
        {orders.length === 0 ? (
          <div className="rounded bg-gray-700 p-2 text-xs text-gray-400">
            No orders
          </div>
        ) : (
          <div className="space-y-2">
            {orders.map((order) => (
              <div
                key={order.id}
                className="rounded bg-gray-700 p-2 text-xs"
              >
                <div className="mb-1 flex items-center justify-between">
                  <span className="font-semibold text-gray-100">
                    {order.symbol}
                  </span>
                  <span
                    className={`rounded px-1.5 py-0.5 text-xs font-semibold ${getOrderStatusBadgeColor(
                      order.status
                    )}`}
                  >
                    {order.status}
                  </span>
                </div>
                <div className="grid grid-cols-2 gap-1 text-gray-400">
                  <span>
                    {order.side} {order.quantity} @ {order.type}
                  </span>
                  {order.price && (
                    <span>{formatCurrency(order.price)}</span>
                  )}
                </div>
              </div>
            ))}
          </div>
        )}
      </div>

      {/* Freeze/Unfreeze Button */}
      <div className="border-t border-gray-700 pt-3">
        {isActive ? (
          <button
            onClick={onFreeze}
            disabled={isLoading}
            className="flex w-full items-center justify-center gap-2 rounded bg-blue-600 px-3 py-2 text-sm font-semibold text-white hover:bg-blue-700 disabled:opacity-50"
            role="button"
            aria-label="Freeze deployment"
          >
            {isLoading && <Loader2 className="h-4 w-4 animate-spin" />}
            Freeze Deployment
          </button>
        ) : isFrozen ? (
          <button
            onClick={onUnfreeze}
            disabled={isLoading}
            className="flex w-full items-center justify-center gap-2 rounded bg-green-600 px-3 py-2 text-sm font-semibold text-white hover:bg-green-700 disabled:opacity-50"
            role="button"
            aria-label="Unfreeze deployment"
          >
            {isLoading && <Loader2 className="h-4 w-4 animate-spin" />}
            Unfreeze Deployment
          </button>
        ) : null}
      </div>
    </div>
  );
}

/**
 * Get Tailwind color classes for an order status badge.
 */
function getOrderStatusBadgeColor(status: string): string {
  switch (status) {
    case "pending":
      return "bg-yellow-500/20 text-yellow-300";
    case "filled":
      return "bg-green-500/20 text-green-300";
    case "cancelled":
      return "bg-red-500/20 text-red-300";
    default:
      return "bg-gray-500/20 text-gray-300";
  }
}
