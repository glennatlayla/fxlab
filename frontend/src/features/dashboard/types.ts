/**
 * Dashboard feature types — contracts for mobile dashboard API responses.
 *
 * Purpose:
 *   Define TypeScript types that correspond to the Python Pydantic models
 *   in libs/contracts/mobile_dashboard.py. Ensures type safety across
 *   frontend API calls and component props.
 *
 * Responsibilities:
 *   - Define MobileDashboardSummary interface matching backend contract.
 *   - Provide TypeScript type guards and validation helpers.
 *
 * Does NOT:
 *   - Contain business logic.
 *   - Make API calls.
 *   - Render UI.
 *
 * Dependencies:
 *   - TypeScript standard library only.
 *
 * Example:
 *   const summary: MobileDashboardSummary = {
 *     active_runs: 3,
 *     completed_runs_24h: 5,
 *     pending_approvals: 2,
 *     active_kill_switches: 0,
 *     pnl_today_usd: 1250.50,
 *     last_alert_severity: "warning",
 *     last_alert_message: "Position delta exceeds threshold",
 *     generated_at: "2026-04-13T14:30:00+00:00",
 *   };
 */

/**
 * Aggregated metrics for mobile dashboard display.
 *
 * Attributes:
 *   active_runs: Count of currently executing research runs.
 *   completed_runs_24h: Count of research runs completed in the last 24 hours.
 *   pending_approvals: Count of promotion requests awaiting approval.
 *   active_kill_switches: Count of currently active kill switches (any scope).
 *   pnl_today_usd: Today's profit/loss in USD. Null if unavailable.
 *   last_alert_severity: Severity of most recent alert ("info", "warning",
 *     "critical", or null if no alerts exist).
 *   last_alert_message: Human-readable message from the most recent alert
 *     (or null if no alerts exist).
 *   generated_at: ISO 8601 timestamp when this summary was generated.
 */
export interface MobileDashboardSummary {
  active_runs: number;
  completed_runs_24h: number;
  pending_approvals: number;
  active_kill_switches: number;
  pnl_today_usd: number | null;
  last_alert_severity: string | null;
  last_alert_message: string | null;
  generated_at: string;
}
