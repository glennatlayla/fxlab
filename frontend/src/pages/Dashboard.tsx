/**
 * Dashboard page — mobile-optimized landing page after authentication (FE-03).
 *
 * Purpose:
 *   Display a mobile-first summary of key trading metrics: active runs,
 *   pending approvals, P&L, kill switch status, and recent alerts.
 *   Auto-refetches every 30 seconds for real-time updates.
 *
 * Responsibilities:
 *   - Fetch mobile dashboard summary from GET /mobile/dashboard endpoint.
 *   - Display summary cards in 2-column grid (mobile) / 4-column (desktop).
 *   - Show alert banner for critical/warning severity levels.
 *   - Show kill switch warning when active_kill_switches > 0.
 *   - Format P&L as currency; display — for null values.
 *   - Provide quick-action links to key pages.
 *   - Handle loading, error, and empty states.
 *
 * Does NOT:
 *   - Contain business logic beyond data presentation.
 *   - Call repositories or external APIs directly.
 *   - Manage authentication (delegated to AuthProvider).
 *
 * Dependencies:
 *   - React 18, @tanstack/react-query, react-router-dom.
 *   - dashboardApi from @/features/dashboard/api.
 *   - useAuth from @/auth/useAuth.
 *   - Tailwind CSS for styling.
 *   - lucide-react for icons (Play, CheckCircle, Shield, TrendingUp, AlertTriangle).
 *
 * Error conditions:
 *   - Network failure: displays error message with retry button.
 *   - 401 Unauthorized: handled globally by apiClient (triggers logout).
 *   - 5xx Server error: displayed as error state.
 *
 * Example:
 *   <Dashboard />
 *   // Renders dashboard with 4 metric cards, optional alerts, quick actions.
 */

import { useQuery } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import {
  Play,
  CheckCircle,
  ShieldCheck,
  TrendingUp,
  AlertTriangle,
  AlertCircle,
  RefreshCw,
} from "lucide-react";
import { clsx } from "clsx";
import { useAuth } from "@/auth/useAuth";
import { dashboardApi } from "@/features/dashboard/api";
import type { MobileDashboardSummary } from "@/features/dashboard/types";

/**
 * Format a number as USD currency.
 *
 * Args:
 *   value: The numeric value to format.
 *
 * Returns:
 *   Formatted string: "+$1,250.50" for positive, "-$500.25" for negative.
 *
 * Example:
 *   formatCurrency(1250.5) // "+$1,250.50"
 *   formatCurrency(-500.25) // "-$500.25"
 */
function formatCurrency(value: number): string {
  const isNegative = value < 0;
  const absValue = Math.abs(value);
  const formatted = absValue.toLocaleString("en-US", {
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  });
  return isNegative ? `-$${formatted}` : `+$${formatted}`;
}

/**
 * Parse ISO 8601 timestamp and return human-readable "last updated" text.
 *
 * Args:
 *   isoString: ISO 8601 timestamp string.
 *
 * Returns:
 *   Human-readable time relative to now (e.g., "just now", "5m ago", "2h ago").
 *
 * Example:
 *   getRelativeTime("2026-04-13T14:30:00Z") // "just now" if within 1 minute
 */
function getRelativeTime(isoString: string): string {
  const timestamp = new Date(isoString);
  const now = new Date();
  const diffMs = now.getTime() - timestamp.getTime();
  const diffSeconds = Math.floor(diffMs / 1000);
  const diffMinutes = Math.floor(diffSeconds / 60);
  const diffHours = Math.floor(diffMinutes / 60);
  const diffDays = Math.floor(diffHours / 24);

  if (diffSeconds < 60) return "just now";
  if (diffMinutes < 60) return `${diffMinutes}m ago`;
  if (diffHours < 24) return `${diffHours}h ago`;
  return `${diffDays}d ago`;
}

/**
 * SummaryCard — individual metric card with icon and label.
 *
 * Props:
 *   icon: React component (lucide-react icon).
 *   label: Display label (e.g., "Active Runs").
 *   value: Numeric value to display, or string for non-numeric values.
 *   href?: Optional link to navigate to on click.
 *   color?: CSS class suffix for icon color (e.g., "blue" for text-blue-600).
 *
 * Example:
 *   <SummaryCard
 *     icon={Play}
 *     label="Active Runs"
 *     value={3}
 *     href="/runs"
 *     color="blue"
 *   />
 */
function SummaryCard({
  icon: Icon,
  label,
  value,
  href,
  color = "surface",
}: {
  icon: typeof Play;
  label: string;
  value: number | string;
  href?: string;
  color?: string;
}) {
  const navigate = useNavigate();
  const handleClick = () => href && navigate(href);

  return (
    <button
      onClick={handleClick}
      disabled={!href}
      className={clsx(
        "card flex flex-col items-start gap-2 text-left transition-all",
        href && "cursor-pointer hover:border-surface-300 hover:shadow-md",
        !href && "cursor-default",
      )}
    >
      <div className={clsx("rounded-lg p-2", `bg-${color}-50`)}>
        <Icon className={clsx("h-5 w-5", `text-${color}-600`)} />
      </div>
      <p className="text-xs uppercase tracking-wide text-surface-500">{label}</p>
      <p className="text-2xl font-semibold text-surface-900">{value}</p>
    </button>
  );
}

export default function Dashboard() {
  const { user } = useAuth();
  const navigate = useNavigate();

  // Fetch dashboard summary with 30-second refetch interval.
  const {
    data: summary,
    isLoading,
    error,
    refetch,
    isFetching,
  } = useQuery<MobileDashboardSummary>({
    queryKey: ["mobile-dashboard"],
    queryFn: dashboardApi.getSummary,
    refetchInterval: 30000, // Refetch every 30 seconds
    retry: 3,
  });

  // Determine alert banner styling based on severity.
  const alertBgColor = summary?.last_alert_severity === "critical" ? "bg-red-50" : "bg-amber-50";
  const alertBorderColor =
    summary?.last_alert_severity === "critical" ? "border-red-200" : "border-amber-200";
  const alertIconColor =
    summary?.last_alert_severity === "critical" ? "text-red-600" : "text-amber-600";
  const alertTextColor =
    summary?.last_alert_severity === "critical" ? "text-red-900" : "text-amber-900";

  return (
    <div className="space-y-6">
      {/* Header */}
      <div>
        <h1 className="text-2xl font-bold text-surface-900">Dashboard</h1>
        <p className="mt-1 text-sm text-surface-500">Welcome back{user ? `, ${user.email}` : ""}</p>
        {summary && (
          <p className="mt-1 text-xs text-surface-400">
            Last updated: {getRelativeTime(summary.generated_at)}
            {isFetching && <span className="ml-2 inline">refreshing...</span>}
          </p>
        )}
      </div>

      {/* Alert Banner — Critical or Warning */}
      {summary?.last_alert_severity && summary?.last_alert_message && (
        <div className={clsx("card border-l-4", alertBgColor, alertBorderColor, "px-4 py-3")}>
          <div className="flex gap-3">
            <AlertTriangle className={clsx("mt-0.5 h-5 w-5 flex-shrink-0", alertIconColor)} />
            <div>
              <p className={clsx("text-sm font-semibold", alertTextColor)}>
                {summary.last_alert_severity === "critical" ? "Critical Alert" : "Warning"}
              </p>
              <p className={clsx("mt-1 text-sm", alertTextColor)}>{summary.last_alert_message}</p>
            </div>
          </div>
        </div>
      )}

      {/* Kill Switch Warning */}
      {summary && summary.active_kill_switches > 0 && (
        <button
          onClick={() => navigate("/emergency")}
          className="card cursor-pointer border-l-4 border-red-200 bg-red-50 px-4 py-3 transition-all hover:shadow-md"
        >
          <div className="flex items-start gap-3">
            <AlertCircle className="mt-0.5 h-5 w-5 flex-shrink-0 text-red-600" />
            <div className="flex-grow text-left">
              <p className="text-sm font-semibold text-red-900">
                {summary.active_kill_switches} Active Kill Switch
                {summary.active_kill_switches !== 1 ? "es" : ""}
              </p>
              <p className="mt-1 text-xs text-red-800">Click to manage emergency controls</p>
            </div>
          </div>
        </button>
      )}

      {/* Summary Cards Grid */}
      {isLoading ? (
        <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
          {[1, 2, 3, 4].map((i) => (
            <div key={i} className="card h-24 animate-pulse bg-surface-50" />
          ))}
        </div>
      ) : error ? (
        <div className="card border-l-4 border-red-200 bg-red-50 px-4 py-3">
          <div className="flex items-start justify-between gap-3">
            <div className="flex flex-grow gap-3">
              <AlertCircle className="mt-0.5 h-5 w-5 flex-shrink-0 text-red-600" />
              <div className="text-left">
                <p className="text-sm font-semibold text-red-900">Failed to load dashboard</p>
                <p className="mt-1 text-xs text-red-800">
                  {error instanceof Error ? error.message : "Unknown error"}
                </p>
              </div>
            </div>
            <button
              onClick={() => refetch()}
              className="flex-shrink-0 rounded p-1 transition-colors hover:bg-red-100"
            >
              <RefreshCw className="h-4 w-4 text-red-600" />
            </button>
          </div>
        </div>
      ) : summary ? (
        <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
          <SummaryCard
            icon={Play}
            label="Active Runs"
            value={summary.active_runs}
            href="/runs"
            color="blue"
          />
          <SummaryCard
            icon={CheckCircle}
            label="Completed (24h)"
            value={summary.completed_runs_24h}
            color="green"
          />
          <SummaryCard
            icon={ShieldCheck}
            label="Pending Approvals"
            value={summary.pending_approvals}
            href="/approvals"
            color="amber"
          />
          <SummaryCard
            icon={TrendingUp}
            label="P&L Today"
            value={summary.pnl_today_usd === null ? "—" : formatCurrency(summary.pnl_today_usd)}
            color={
              summary.pnl_today_usd === null
                ? "surface"
                : summary.pnl_today_usd >= 0
                  ? "green"
                  : "red"
            }
          />
        </div>
      ) : null}

      {/* Quick Actions */}
      {summary && !isLoading && !error && (
        <div className="grid grid-cols-2 gap-4 lg:grid-cols-4">
          <button
            onClick={() => navigate("/runs/new")}
            className="card py-4 text-center transition-all hover:border-surface-300 hover:shadow-md"
          >
            <Play className="mx-auto mb-2 h-5 w-5 text-blue-600" />
            <p className="text-sm font-medium text-surface-900">New Run</p>
          </button>
          <button
            onClick={() => navigate("/emergency")}
            className="card py-4 text-center transition-all hover:border-surface-300 hover:shadow-md"
          >
            <AlertTriangle className="mx-auto mb-2 h-5 w-5 text-red-600" />
            <p className="text-sm font-medium text-surface-900">Emergency Controls</p>
          </button>
          <button
            onClick={() => navigate("/approvals")}
            className="card py-4 text-center transition-all hover:border-surface-300 hover:shadow-md"
          >
            <ShieldCheck className="mx-auto mb-2 h-5 w-5 text-amber-600" />
            <p className="text-sm font-medium text-surface-900">Approvals</p>
          </button>
          <button
            onClick={() => navigate("/runs")}
            className="card py-4 text-center transition-all hover:border-surface-300 hover:shadow-md"
          >
            <CheckCircle className="mx-auto mb-2 h-5 w-5 text-green-600" />
            <p className="text-sm font-medium text-surface-900">View Runs</p>
          </button>
        </div>
      )}
    </div>
  );
}
