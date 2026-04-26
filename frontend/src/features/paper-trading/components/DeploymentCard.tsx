/**
 * DeploymentCard — mobile-optimized card displaying a single paper trading deployment.
 *
 * Purpose:
 *   Render a compact, full-width card representing a single paper trading
 *   deployment in the PaperTradingOverview list. Designed for mobile screens
 *   with touch-friendly tap targets.
 *
 * Responsibilities:
 *   - Display strategy name and deployment status badge.
 *   - Display total P&L (color-coded green for profit, red for loss).
 *   - Display equity vs initial equity comparison with visual bar.
 *   - Display open positions and orders counts.
 *   - Show last trade timestamp.
 *   - Handle click events (onClick callback).
 *   - Provide visual affordance (chevron icon) indicating clickability.
 *
 * Does NOT:
 *   - Fetch data (receives deployment as prop).
 *   - Manage internal state.
 *   - Navigate (parent component handles navigation).
 *
 * Dependencies:
 *   - lucide-react (for ChevronRight icon).
 *   - PaperDeploymentSummary type (from @/features/paper-trading/types).
 *
 * Example:
 *   <DeploymentCard
 *     deployment={deployment}
 *     onClick={(id) => navigate(`/paper/${id}`)}
 *   />
 */

import { ChevronRight } from "lucide-react";
import type { PaperDeploymentSummary } from "../types";

interface DeploymentCardProps {
  /** The paper trading deployment to display. */
  deployment: PaperDeploymentSummary;
  /** Callback fired when the card is clicked, receives the deployment ID. */
  onClick: (deploymentId: string) => void;
  /** Optional additional CSS class names. */
  className?: string;
}

/**
 * Format a timestamp to a human-readable relative time string.
 *
 * Args:
 *   isoTimestamp: ISO-8601 timestamp string.
 *
 * Returns:
 *   Human-readable string (e.g., "2 hours ago", "Apr 13").
 */
function formatTimestamp(isoTimestamp: string): string {
  const date = new Date(isoTimestamp);
  const now = new Date();
  const diffMs = now.getTime() - date.getTime();
  const diffMins = Math.floor(diffMs / 60000);
  const diffHours = Math.floor(diffMins / 60);
  const diffDays = Math.floor(diffHours / 24);

  if (diffMins < 1) return "just now";
  if (diffMins < 60) return `${diffMins}m ago`;
  if (diffHours < 24) return `${diffHours}h ago`;
  if (diffDays < 7) return `${diffDays}d ago`;

  // Fallback to short date format for older timestamps
  return date.toLocaleDateString("en-US", { month: "short", day: "numeric" });
}

/**
 * Format a number as currency string with two decimal places.
 *
 * Args:
 *   value: Numeric value to format.
 *
 * Returns:
 *   Currency string (e.g., "$1,500.00").
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
 * Render a mobile-optimized card for a single paper trading deployment.
 *
 * Args:
 *   deployment: The paper trading deployment to display.
 *   onClick: Callback when card is clicked.
 *   className: Optional additional CSS classes.
 */
export function DeploymentCard({ deployment, onClick, className = "" }: DeploymentCardProps) {
  const equityPercentage = (deployment.equity / deployment.initial_equity) * 100;
  const equityPercentageClamp = Math.min(100, Math.max(10, equityPercentage));

  return (
    <button
      onClick={() => onClick(deployment.id)}
      data-testid="deployment-card"
      className={`w-full rounded-lg border border-gray-700 bg-gray-800 p-3 text-left transition-colors hover:bg-gray-700 active:bg-gray-600 ${className}`.trim()}
      aria-label={`Deployment ${deployment.id}, strategy: ${deployment.strategy_name}, status: ${deployment.status}`}
    >
      {/* Top row: Strategy name + Status Badge */}
      <div className="mb-2 flex items-center justify-between gap-2">
        <span className="text-sm font-medium text-gray-100">{deployment.strategy_name}</span>
        <span
          role="status"
          className={`rounded-full px-2 py-0.5 text-xs font-semibold ${getStatusBadgeColor(
            deployment.status,
          )}`}
        >
          {deployment.status}
        </span>
      </div>

      {/* Second row: P&L breakdown */}
      <div className="mb-3 grid grid-cols-3 gap-2 text-xs">
        <div>
          <span className="text-gray-500">Total P&L</span>
          <div
            className={`font-semibold ${
              deployment.total_pnl >= 0 ? "text-green-400" : "text-red-400"
            }`}
          >
            {formatCurrency(deployment.total_pnl)}
          </div>
        </div>
        <div>
          <span className="text-gray-500">Unrealized</span>
          <div
            className={`font-semibold ${
              deployment.unrealized_pnl >= 0 ? "text-green-400" : "text-red-400"
            }`}
          >
            {formatCurrency(deployment.unrealized_pnl)}
          </div>
        </div>
        <div>
          <span className="text-gray-500">Realized</span>
          <div
            className={`font-semibold ${
              deployment.realized_pnl >= 0 ? "text-green-400" : "text-red-400"
            }`}
          >
            {formatCurrency(deployment.realized_pnl)}
          </div>
        </div>
      </div>

      {/* Equity bar: visual comparison */}
      <div className="mb-2">
        <div className="mb-1 flex justify-between text-xs text-gray-400">
          <span>Equity: {formatCurrency(deployment.equity)}</span>
          <span className="text-gray-500">vs {formatCurrency(deployment.initial_equity)}</span>
        </div>
        <div className="h-1.5 rounded-full bg-gray-700">
          <div
            className="h-1.5 rounded-full bg-blue-500 transition-all"
            style={{ width: `${equityPercentageClamp}%` }}
            role="progressbar"
            aria-valuenow={equityPercentageClamp}
            aria-valuemin={0}
            aria-valuemax={100}
          />
        </div>
      </div>

      {/* Bottom row: Positions, Orders, Last Trade + Chevron */}
      <div className="flex items-center justify-between gap-2">
        <div className="flex gap-4 text-xs text-gray-400">
          <span>
            {deployment.open_positions} {deployment.open_positions === 1 ? "position" : "positions"}
          </span>
          <span>
            {deployment.open_orders} {deployment.open_orders === 1 ? "order" : "orders"}
          </span>
        </div>
        <div className="flex items-center gap-1">
          <span className="text-xs text-gray-500">
            {deployment.last_trade_at ? formatTimestamp(deployment.last_trade_at) : "never"}
          </span>
          <ChevronRight className="h-4 w-4 text-gray-500" aria-hidden="true" />
        </div>
      </div>
    </button>
  );
}

/**
 * Get Tailwind color classes for a deployment status badge.
 *
 * Args:
 *   status: Deployment status string.
 *
 * Returns:
 *   Tailwind className string for the badge.
 */
function getStatusBadgeColor(status: string): string {
  switch (status) {
    case "active":
      return "bg-green-500/20 text-green-300";
    case "paused":
      return "bg-yellow-500/20 text-yellow-300";
    case "frozen":
      return "bg-blue-500/20 text-blue-300";
    case "stopped":
      return "bg-gray-500/20 text-gray-300";
    default:
      return "bg-gray-500/20 text-gray-300";
  }
}
