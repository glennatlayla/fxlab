/**
 * Alerts page — system and trading alerts dashboard.
 *
 * Purpose:
 *   Display system alerts, trading alerts, and notifications
 *   in a centralized, mobile-friendly view.
 *
 * Responsibilities:
 *   - Show list of recent alerts and notifications.
 *   - Filter and search alerts by category or severity.
 *   - Provide alert details and history.
 *
 * Does NOT:
 *   - Contain business logic for alert generation (that's in services).
 *   - Store alert history locally (delegates to API).
 *   - Send notifications (delegates to backend).
 *
 * Example:
 *   import Alerts from "@/pages/Alerts";
 *   <Route path="/alerts" element={<Alerts />} />
 *
 * Routes:
 *   GET /api/v1/alerts — Fetch alerts (pagination)
 *   GET /api/v1/alerts/:alertId — Get alert details
 */

import React from "react";
import { AlertsPage } from "@/features/alerts/AlertsPage";

/**
 * Default Alerts page entry point.
 *
 * Renders the alert feed for the primary deployment.
 * The deployment ID is currently hardcoded but can be made dynamic
 * once a deployment context is established.
 *
 * TODO: FE-13.3 — Integrate deployment selection once DeploymentContext exists
 */
export default function Alerts(): React.ReactElement {
  // For now, use a placeholder deployment ID. This will be replaced with
  // dynamic deployment selection once DeploymentContext is available.
  const DEPLOYMENT_ID = "primary";

  return <AlertsPage deploymentId={DEPLOYMENT_ID} />;
}
