/**
 * Alert Feed feature — public exports.
 *
 * Exports the main AlertsPage component and types for use in other modules.
 */

export { AlertsPage } from "./AlertsPage";
export { AlertCard } from "./components/AlertCard";
export { AlertDetail } from "./components/AlertDetail";
export { alertsApi } from "./api";
export type { Alert, AlertSeverity, AlertFilterType, AlertListResponse } from "./types";
