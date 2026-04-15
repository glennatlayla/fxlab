/**
 * Alert Feed feature types and contracts.
 *
 * Purpose:
 *   Define the alert domain models and API contracts for the alert feed.
 *   Represents alerts that can be displayed, filtered, and acknowledged.
 *
 * Responsibilities:
 *   - Define Alert domain model with severity, metadata, and timestamps.
 *   - Define AlertListResponse for API pagination.
 *   - Define filter and UI-specific types.
 *
 * Does NOT:
 *   - Contain business logic.
 *   - Perform I/O or API calls.
 *
 * Dependencies:
 *   - None (pure TypeScript types).
 *
 * Error conditions:
 *   - None; used for type validation at compile-time.
 *
 * Example:
 *   const alert: Alert = {
 *     id: "alert-001",
 *     severity: "critical",
 *     title: "VaR Breach",
 *     ...
 *   }
 */

/**
 * Alert severity level.
 *
 * critical: Risk or system failure requires immediate action.
 * warning: Anomaly detected; monitor closely.
 * info: Informational; normal operational event.
 */
export type AlertSeverity = "critical" | "warning" | "info";

/**
 * Source system identifier for the alert.
 *
 * Identifies which component generated the alert:
 * risk-gate: Risk alert service (VaR, concentration, correlation).
 * kill-switch: Emergency kill switch activity.
 * data-quality: Data quality check failure.
 * execution: Trade execution error or anomaly.
 * other: Unknown or unclassified source.
 */
export type AlertSource = "risk-gate" | "kill-switch" | "data-quality" | "execution" | "other";

/**
 * Alert domain model — represents a single alert/notification.
 *
 * Attributes:
 *   id: Globally unique identifier.
 *   severity: Alert severity level (critical, warning, info).
 *   title: Short title or headline.
 *   message: Full alert message.
 *   source: System that generated the alert.
 *   created_at: ISO-8601 timestamp when alert was created.
 *   acknowledged: Whether the alert has been acknowledged by a user.
 *   acknowledged_by: User ID or name of acknowledger.
 *   acknowledged_at: ISO-8601 timestamp of acknowledgment.
 *   metadata: Optional unstructured data (VaR threshold, symbol, etc.).
 *
 * Example:
 *   const alert: Alert = {
 *     id: "alert-001",
 *     severity: "critical",
 *     title: "VaR Breach Detected",
 *     message: "Portfolio VaR exceeds 5% threshold",
 *     source: "risk-gate",
 *     created_at: "2026-04-13T12:00:00Z",
 *     acknowledged: false,
 *   }
 */
export interface Alert {
  id: string;
  severity: AlertSeverity;
  title: string;
  message: string;
  source: AlertSource;
  created_at: string;
  acknowledged: boolean;
  acknowledged_by?: string;
  acknowledged_at?: string;
  metadata?: Record<string, unknown>;
}

/**
 * API response for paginated alert list.
 *
 * Attributes:
 *   alerts: Array of alerts in this page.
 *   total: Total number of alerts available (may exceed page size).
 *   next_cursor: Opaque cursor for fetching next page (undefined if no more).
 *
 * Example:
 *   const response: AlertListResponse = {
 *     alerts: [alert1, alert2],
 *     total: 42,
 *     next_cursor: "cursor-123",
 *   }
 */
export interface AlertListResponse {
  alerts: Alert[];
  total: number;
  next_cursor?: string;
}

/**
 * Alert filter state for the feed UI.
 *
 * Used to control which alerts are displayed:
 * - all: Show all alerts.
 * - critical: Only critical severity.
 * - warning: Only warning severity.
 * - info: Only info severity.
 */
export type AlertFilterType = "all" | "critical" | "warning" | "info";
