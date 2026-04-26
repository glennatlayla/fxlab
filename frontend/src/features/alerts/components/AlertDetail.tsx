/**
 * AlertDetail — Detailed alert view in BottomSheet.
 *
 * Purpose:
 *   Display full alert information including message, metadata,
 *   timeline, and acknowledge action.
 *
 * Responsibilities:
 *   - Render alert title, full message, and metadata.
 *   - Display timestamp and source information.
 *   - Show acknowledge button (if not already acknowledged).
 *   - Display acknowledger info and time (if acknowledged).
 *   - Format and present unstructured metadata.
 *
 * Does NOT:
 *   - Manage modal state.
 *   - Make API calls directly (caller handles onAcknowledge callback).
 *   - Mutate alert data locally.
 *
 * Dependencies:
 *   - React
 *   - lucide-react (Check, Clock, User icons)
 *   - clsx
 *   - Alert type from ../types
 *
 * Error conditions:
 *   - Missing metadata: renders gracefully, skips metadata section.
 *   - Complex nested metadata: renders as JSON string.
 *
 * Example:
 *   <AlertDetail
 *     alert={alert}
 *     onAcknowledge={(alertId) => handleAcknowledge(alertId)}
 *   />
 */

import React from "react";
import { Check, Clock, User } from "lucide-react";
import clsx from "clsx";
import type { Alert } from "../types";

export interface AlertDetailProps {
  /** Alert to display. */
  alert: Alert;
  /** Callback when acknowledge button is clicked. */
  onAcknowledge: (alertId: string) => void;
}

/**
 * Format ISO timestamp to readable date-time string.
 */
function formatDateTime(isoString: string): string {
  try {
    const date = new Date(isoString);
    return date.toLocaleString("en-US", {
      month: "short",
      day: "numeric",
      year: "numeric",
      hour: "2-digit",
      minute: "2-digit",
      second: "2-digit",
      hour12: true,
    });
  } catch {
    return isoString;
  }
}

/**
 * Format metadata value for display.
 *
 * Converts numbers to strings with appropriate formatting,
 * objects to JSON strings, etc.
 */
function formatMetadataValue(value: unknown): string {
  if (value === null || value === undefined) {
    return "—";
  }
  if (typeof value === "number") {
    // Format numbers with up to 4 decimal places
    return Number.isInteger(value) ? value.toString() : value.toFixed(4);
  }
  if (typeof value === "string") {
    return value;
  }
  if (typeof value === "boolean") {
    return value ? "true" : "false";
  }
  // Objects, arrays, etc.
  return JSON.stringify(value);
}

/**
 * AlertDetail component.
 *
 * Renders full alert details in a vertically scrollable view suitable
 * for display in a BottomSheet.
 *
 * Example:
 *   <AlertDetail
 *     alert={{
 *       id: "alert-001",
 *       severity: "critical",
 *       title: "VaR Breach",
 *       message: "Portfolio VaR (6.2%) exceeds threshold (5.0%)",
 *       source: "risk-gate",
 *       created_at: "2026-04-13T12:00:00Z",
 *       acknowledged: false,
 *       metadata: {
 *         current_value: 6.2,
 *         threshold_value: 5.0,
 *       },
 *     }}
 *     onAcknowledge={(id) => console.log(`Acknowledged ${id}`)}
 *   />
 */
export function AlertDetail({ alert, onAcknowledge }: AlertDetailProps): React.ReactElement {
  const hasMetadata = alert.metadata && Object.keys(alert.metadata).length > 0;

  return (
    <div className="flex flex-col gap-6">
      {/* Header with Title and Status */}
      <div>
        <h2 className="text-xl font-bold text-surface-900">{alert.title}</h2>
        {alert.acknowledged && (
          <div className="mt-2 flex w-fit items-center gap-2 rounded-full bg-green-50 px-3 py-1">
            <Check className="h-4 w-4 text-green-600" />
            <span className="text-sm font-medium text-green-700">Acknowledged</span>
          </div>
        )}
      </div>

      {/* Full Message */}
      <div>
        <h3 className="mb-2 font-semibold text-surface-900">Message</h3>
        <p className="whitespace-pre-wrap text-sm text-surface-700">{alert.message}</p>
      </div>

      {/* Timeline / Event Info */}
      <div className="space-y-3 rounded-lg bg-surface-50 p-4">
        {/* Created */}
        <div className="flex items-start gap-3">
          <Clock className="h-4 w-4 flex-shrink-0 pt-0.5 text-surface-500" />
          <div className="min-w-0 flex-1">
            <p className="text-xs font-medium uppercase tracking-wide text-surface-600">Created</p>
            <p className="mt-1 text-sm text-surface-900">{formatDateTime(alert.created_at)}</p>
          </div>
        </div>

        {/* Source */}
        <div className="flex items-start gap-3 border-t border-surface-200 pt-3">
          <div className="h-4 w-4 flex-shrink-0" />
          <div className="min-w-0 flex-1">
            <p className="text-xs font-medium uppercase tracking-wide text-surface-600">Source</p>
            <p className="mt-1 text-sm text-surface-900">{alert.source}</p>
          </div>
        </div>

        {/* Acknowledged By (if acknowledged) */}
        {alert.acknowledged && alert.acknowledged_by && (
          <div className="flex items-start gap-3 border-t border-surface-200 pt-3">
            <User className="h-4 w-4 flex-shrink-0 pt-0.5 text-surface-500" />
            <div className="min-w-0 flex-1">
              <p className="text-xs font-medium uppercase tracking-wide text-surface-600">
                Acknowledged By
              </p>
              <p className="mt-1 text-sm text-surface-900">{alert.acknowledged_by}</p>
              {alert.acknowledged_at && (
                <p className="mt-1 text-xs text-surface-500">
                  {formatDateTime(alert.acknowledged_at)}
                </p>
              )}
            </div>
          </div>
        )}
      </div>

      {/* Metadata Section */}
      {hasMetadata && (
        <div>
          <h3 className="mb-3 font-semibold text-surface-900">Details</h3>
          <div className="space-y-2">
            {Object.entries(alert.metadata!).map(([key, value]) => (
              <div
                key={key}
                className="flex items-start justify-between rounded-lg bg-surface-50 px-3 py-2"
              >
                <span className="text-sm font-medium text-surface-700">
                  {key.replace(/_/g, " ")}
                </span>
                <span className="ml-2 truncate text-right text-sm text-surface-900">
                  {formatMetadataValue(value)}
                </span>
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Acknowledge Button */}
      {!alert.acknowledged && (
        <button
          onClick={() => onAcknowledge(alert.id)}
          className={clsx(
            "w-full rounded-lg border border-transparent px-4 py-3 font-semibold text-white",
            "transition-colors hover:opacity-90 active:opacity-80",
            "bg-blue-600 hover:bg-blue-700",
          )}
        >
          Acknowledge Alert
        </button>
      )}
    </div>
  );
}
