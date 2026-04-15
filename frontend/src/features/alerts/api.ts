/**
 * Alert Feed feature API layer — data fetching and mutations.
 *
 * Purpose:
 *   Fetch alerts from the backend risk alert evaluation endpoint.
 *   Handle alert listing, detail retrieval, and acknowledgment.
 *
 * Responsibilities:
 *   - GET /risk/alerts/evaluate/{deployment_id} — fetch alert evaluation.
 *   - Translate backend RiskAlert/RiskAlertEvaluation into Alert domain model.
 *   - POST acknowledge endpoint when implemented.
 *   - Propagate X-Correlation-Id headers per CLAUDE.md §8.
 *   - Handle transient errors via apiClient retry policy.
 *
 * Does NOT:
 *   - Contain business logic or UI rendering.
 *   - Bypass the shared apiClient (auth, base URL, 401 handling).
 *   - Implement retry logic directly (delegated to apiClient).
 *
 * Dependencies:
 *   - apiClient from @/api/client.
 *   - Alert, AlertListResponse types from ./types.
 *   - RiskAlertEvaluation contract from backend.
 *
 * Error conditions:
 *   - Network failures: propagated by apiClient.
 *   - 401 Unauthorized: handled globally by apiClient response interceptor.
 *   - 404 Not found: indicates deployment does not exist.
 *   - 5xx Server errors: propagated to caller (handled by useQuery retry).
 *
 * Example:
 *   const alerts = await alertsApi.listAlerts({
 *     deploymentId: "deploy-001",
 *     cursor: undefined,
 *   });
 *   // Returns: { alerts: [...], total: 42, next_cursor: "..." }
 */

import { apiClient } from "@/api/client";
import type { Alert, AlertListResponse } from "./types";

/**
 * Backend RiskAlert contract (mirror of Pydantic RiskAlert).
 */
interface RiskAlert {
  alert_type: string;
  message: string;
  current_value: number;
  threshold_value: number;
  symbol?: string;
  symbol_b?: string;
}

/**
 * Backend RiskAlertEvaluation contract (mirror of Pydantic RiskAlertEvaluation).
 */
interface RiskAlertEvaluation {
  deployment_id: string;
  alerts_triggered: RiskAlert[];
  total_rules_checked: number;
  evaluated_at: string;
}

/**
 * Translate backend RiskAlert to frontend Alert.
 *
 * Maps risk alert type to severity and constructs the alert domain model.
 *
 * Args:
 *   riskAlert: Backend RiskAlert from evaluation result.
 *   deploymentId: The deployment this alert was evaluated for (used for ID generation).
 *
 * Returns:
 *   Translated Alert domain model.
 *
 * Example:
 *   const alert = translateRiskAlert(
 *     { alert_type: "var_breach", message: "VaR exceeds threshold", ... },
 *     "deploy-001"
 *   );
 */
function translateRiskAlert(
  riskAlert: RiskAlert,
  deploymentId: string,
  index: number,
  timestamp: string,
): Alert {
  // Map alert_type to severity: var_breach and concentration_breach → critical,
  // correlation_spike → warning
  const severityMap: Record<string, "critical" | "warning" | "info"> = {
    var_breach: "critical",
    concentration_breach: "critical",
    correlation_spike: "warning",
  };

  const severity = severityMap[riskAlert.alert_type] || "info";

  // Map alert_type to title
  const titleMap: Record<string, string> = {
    var_breach: "VaR Breach",
    concentration_breach: "Concentration Alert",
    correlation_spike: "High Correlation",
  };

  const title = titleMap[riskAlert.alert_type] || "Risk Alert";

  return {
    id: `${deploymentId}-${riskAlert.alert_type}-${index}`,
    severity,
    title,
    message: riskAlert.message,
    source: "risk-gate",
    created_at: timestamp,
    acknowledged: false,
    metadata: {
      alert_type: riskAlert.alert_type,
      current_value: riskAlert.current_value,
      threshold_value: riskAlert.threshold_value,
      symbol: riskAlert.symbol,
      symbol_b: riskAlert.symbol_b,
    },
  };
}

/**
 * Alert API endpoints.
 *
 * Provides methods for fetching and managing alerts.
 */
export const alertsApi = {
  /**
   * List alerts for a deployment (via risk alert evaluation).
   *
   * Fetches the current alert state by evaluating all risk rules for the
   * deployment. Returns alerts with pagination cursor (for now, single page).
   *
   * Args:
   *   deploymentId: Target deployment ID.
   *   cursor: Optional cursor for next page (not yet implemented; kept for future).
   *   limit: Optional page size limit (not yet implemented; kept for future).
   *
   * Returns:
   *   Promise resolving to AlertListResponse.
   *
   * Raises:
   *   AxiosError if the request fails (network, timeout, 5xx, etc.).
   *   401 errors are handled globally by apiClient response interceptor.
   *   404 indicates deployment does not exist.
   *
   * Example:
   *     const result = await alertsApi.listAlerts({
   *       deploymentId: "deploy-001",
   *     });
   *     // result: { alerts: [...], total: 3, next_cursor: undefined }
   */
  listAlerts: async (params: {
    deploymentId: string;
    cursor?: string;
    limit?: number;
  }): Promise<AlertListResponse> => {
    const response = await apiClient.get<RiskAlertEvaluation>(
      `/risk/alerts/evaluate/${params.deploymentId}`,
    );

    const evaluation = response.data;

    // Translate backend alerts to frontend Alert model
    const alerts: Alert[] = evaluation.alerts_triggered.map((riskAlert, index) =>
      translateRiskAlert(riskAlert, params.deploymentId, index, evaluation.evaluated_at),
    );

    return {
      alerts,
      total: alerts.length,
      next_cursor: undefined, // Not paginated in first implementation
    };
  },

  /**
   * Acknowledge an alert.
   *
   * Marks an alert as acknowledged by the current user.
   * Returns updated alert state.
   *
   * Args:
   *   alertId: Alert to acknowledge.
   *
   * Returns:
   *   Promise resolving to updated Alert.
   *
   * Raises:
   *   AxiosError if the request fails.
   *
   * Example:
   *   const updated = await alertsApi.acknowledgeAlert("alert-001");
   */
  acknowledgeAlert: async (alertId: string): Promise<Alert> => {
    // TODO: FE-13.1 — Implement once backend endpoint exists
    // For now, return optimistic update (caller should handle locally)
    const alert: Alert = {
      id: alertId,
      severity: "info",
      title: "Alert",
      message: "Acknowledged",
      source: "other",
      created_at: new Date().toISOString(),
      acknowledged: true,
    };
    return alert;
  },

  /**
   * Get alert detail.
   *
   * Fetch full details for a single alert.
   *
   * Args:
   *   alertId: Alert to fetch.
   *
   * Returns:
   *   Promise resolving to Alert.
   *
   * Raises:
   *   AxiosError if the request fails.
   *
   * Example:
   *   const alert = await alertsApi.getAlertDetail("alert-001");
   */
  getAlertDetail: async (alertId: string): Promise<Alert> => {
    // TODO: FE-13.2 — Implement once backend endpoint exists
    // For now, return a stub alert (caller should cache from listAlerts)
    const alert: Alert = {
      id: alertId,
      severity: "info",
      title: "Alert",
      message: "Detail",
      source: "other",
      created_at: new Date().toISOString(),
      acknowledged: false,
    };
    return alert;
  },
};
