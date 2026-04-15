/**
 * Dashboard feature API layer — data fetching for mobile dashboard summary.
 *
 * Purpose:
 *   Fetch the mobile dashboard summary from GET /mobile/dashboard endpoint.
 *   Implements standard error handling and timeout policies.
 *
 * Responsibilities:
 *   - GET /mobile/dashboard — fetch aggregated dashboard metrics.
 *   - Propagate X-Correlation-Id headers per CLAUDE.md §8.
 *   - Handle transient errors (network, timeout) via apiClient retry policy.
 *
 * Does NOT:
 *   - Contain business logic or UI rendering.
 *   - Bypass the shared apiClient (auth, base URL, 401 handling).
 *   - Implement retry logic directly (delegated to apiClient).
 *
 * Dependencies:
 *   - apiClient from @/api/client.
 *
 * Error conditions:
 *   - Network failures: propagated by apiClient.
 *   - 401 Unauthorized: handled globally by apiClient response interceptor.
 *   - 5xx Server errors: propagated to caller (handled by useQuery retry).
 *
 * Example:
 *   const summary = await dashboardApi.getSummary();
 *   // Returns: { active_runs: 3, completed_runs_24h: 5, ... }
 */

import { apiClient } from "@/api/client";
import type { MobileDashboardSummary } from "./types";

/**
 * Dashboard API endpoints.
 */
export const dashboardApi = {
  /**
   * Fetch mobile dashboard summary.
   *
   * Returns:
   *   Promise resolving to MobileDashboardSummary with aggregated metrics.
   *
   * Raises:
   *   AxiosError if the request fails (network, timeout, 5xx, etc.).
   *   401 errors are handled globally by apiClient response interceptor.
   *
   * Example:
   *   const summary = await dashboardApi.getSummary();
   */
  getSummary: async (): Promise<MobileDashboardSummary> => {
    const response = await apiClient.get<MobileDashboardSummary>("/mobile/dashboard");
    return response.data;
  },
};
