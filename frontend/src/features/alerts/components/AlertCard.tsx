/**
 * AlertCard — Single alert card in the alert feed.
 *
 * Purpose:
 *   Display a single alert with severity-coded styling, source badge,
 *   and timestamp. Tappable to open detail view in BottomSheet.
 *
 * Responsibilities:
 *   - Render alert title, message, source, and timestamp.
 *   - Apply severity-based left border color and icon.
 *   - Show acknowledged state (dimmed, check badge).
 *   - Truncate long messages to 2 lines with ellipsis.
 *   - Call onClick handler when card is tapped.
 *
 * Does NOT:
 *   - Manage modal/detail state (parent component responsibility).
 *   - Make API calls.
 *   - Store alert data locally.
 *
 * Dependencies:
 *   - React
 *   - lucide-react (AlertTriangle, AlertCircle, Info, Check icons)
 *   - clsx (className helper)
 *   - Alert type from ../types
 *
 * Error conditions:
 *   - None; component renders gracefully with missing fields.
 *
 * Example:
 *   <AlertCard
 *     alert={alert}
 *     onClick={(alert) => setSelectedAlert(alert)}
 *   />
 */

import React from "react";
import { AlertTriangle, AlertCircle, Info, Check } from "lucide-react";
import clsx from "clsx";
import type { Alert } from "../types";

export interface AlertCardProps {
  /** Alert to display. */
  alert: Alert;
  /** Callback when card is clicked. */
  onClick: (alert: Alert) => void;
}

/**
 * Map severity to border color and icon.
 */
function getSeverityStyles(severity: Alert["severity"]): {
  borderColor: string;
  Icon: React.ComponentType<{ className?: string }>;
  iconColor: string;
} {
  switch (severity) {
    case "critical":
      return {
        borderColor: "border-l-red-600",
        Icon: AlertTriangle,
        iconColor: "text-red-600",
      };
    case "warning":
      return {
        borderColor: "border-l-amber-600",
        Icon: AlertCircle,
        iconColor: "text-amber-600",
      };
    case "info":
    default:
      return {
        borderColor: "border-l-blue-600",
        Icon: Info,
        iconColor: "text-blue-600",
      };
  }
}

/**
 * Format relative time (e.g., "2 hours ago", "just now").
 */
function formatRelativeTime(isoString: string): string {
  try {
    const created = new Date(isoString);
    const now = new Date();
    const diffMs = now.getTime() - created.getTime();
    const diffSeconds = Math.floor(diffMs / 1000);
    const diffMinutes = Math.floor(diffSeconds / 60);
    const diffHours = Math.floor(diffMinutes / 60);
    const diffDays = Math.floor(diffHours / 24);

    if (diffSeconds < 60) {
      return "just now";
    }
    if (diffMinutes < 60) {
      return `${diffMinutes} minute${diffMinutes > 1 ? "s" : ""} ago`;
    }
    if (diffHours < 24) {
      return `${diffHours} hour${diffHours > 1 ? "s" : ""} ago`;
    }
    if (diffDays < 7) {
      return `${diffDays} day${diffDays > 1 ? "s" : ""} ago`;
    }
    // Fall back to date format
    return created.toLocaleDateString("en-US", {
      month: "short",
      day: "numeric",
    });
  } catch {
    return "unknown time";
  }
}

/**
 * AlertCard component.
 *
 * Renders a horizontal card with left border indicating severity.
 * Shows icon, title, message, source badge, and timestamp.
 * Acknowledged alerts are dimmed with a check badge.
 *
 * Example:
 *   <AlertCard
 *     alert={{
 *       id: "alert-001",
 *       severity: "critical",
 *       title: "VaR Breach",
 *       message: "Portfolio VaR exceeds threshold",
 *       source: "risk-gate",
 *       created_at: "2026-04-13T12:00:00Z",
 *       acknowledged: false,
 *     }}
 *     onClick={(alert) => console.log(alert)}
 *   />
 */
export function AlertCard({ alert, onClick }: AlertCardProps): React.ReactElement {
  const { borderColor, Icon, iconColor } = getSeverityStyles(alert.severity);
  const relativeTime = formatRelativeTime(alert.created_at);

  return (
    <button
      data-testid="alert-card"
      onClick={() => onClick(alert)}
      className={clsx(
        "w-full rounded-lg border-b border-l-4 border-r border-t border-surface-200 bg-white p-4 text-left transition-all hover:bg-surface-50 active:bg-surface-100",
        borderColor,
        alert.acknowledged && "opacity-60",
      )}
      aria-pressed={alert.acknowledged}
    >
      <div className="flex gap-3">
        {/* Severity Icon */}
        <div data-testid="alert-icon" className="flex-shrink-0 pt-1">
          <Icon className={clsx("h-5 w-5", iconColor)} />
        </div>

        {/* Content */}
        <div className="min-w-0 flex-1">
          {/* Title and Source Row */}
          <div className="flex items-center justify-between gap-2">
            <h3 className="font-semibold text-surface-900">{alert.title}</h3>
            <span className="flex-shrink-0 rounded-full bg-surface-100 px-2 py-0.5 text-xs font-medium text-surface-700">
              {alert.source}
            </span>
          </div>

          {/* Message */}
          <p data-testid="alert-message" className="mt-1 line-clamp-2 text-sm text-surface-600">
            {alert.message}
          </p>

          {/* Timestamp */}
          <p className="mt-2 text-xs text-surface-500">{relativeTime}</p>
        </div>

        {/* Acknowledged Badge */}
        {alert.acknowledged && (
          <div
            data-testid="acknowledged-badge"
            className="flex h-6 w-6 flex-shrink-0 items-center justify-center rounded-full bg-green-100"
          >
            <Check className="h-4 w-4 text-green-600" />
          </div>
        )}
      </div>
    </button>
  );
}
