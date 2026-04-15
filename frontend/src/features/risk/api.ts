/**
 * Risk settings API module.
 *
 * Purpose:
 *   Encapsulate all HTTP calls to risk limit endpoints.
 *   Provide a clean, type-safe interface for API operations.
 *
 * Responsibilities:
 *   - Call /deployments/{id}/risk-limits endpoints via apiClient.
 *   - Return typed responses.
 *   - Let apiClient handle auth headers, correlation IDs, timeouts.
 *
 * Does NOT:
 *   - Contain business logic.
 *   - Manage state.
 *   - Handle retries (apiClient + caller are responsible).
 *
 * Dependencies:
 *   - apiClient: configured Axios instance with auth + correlation IDs.
 *   - types: RiskSettings, RiskSettingsUpdate.
 *
 * Error conditions:
 *   - Network errors: thrown by apiClient (caller handles retry).
 *   - 404 Not Found: deployment or risk limits do not exist.
 *   - 422 Invalid: malformed request body or invalid values.
 *
 * Example:
 *   const settings = await riskApi.getSettings("01HDEPLOY...");
 *   await riskApi.updateSettings("01HDEPLOY...", { max_position_size: "15000" });
 */

import { apiClient } from "@/api/client";
import type { RiskSettings, RiskSettingsUpdate } from "./types";

/**
 * Risk settings API client.
 *
 * All endpoints return typed responses. Error responses are thrown by
 * apiClient interceptors or caller handling.
 */
export const riskApi = {
  /**
   * Fetch current risk settings for a deployment.
   *
   * Args:
   *   deploymentId: ULID of the deployment.
   *
   * Returns:
   *   Promise<RiskSettings> — current risk limits.
   *
   * Raises:
   *   AxiosError with 404 if deployment or limits not found.
   *   AxiosError with 5xx on server error.
   *
   * Example:
   *   const settings = await riskApi.getSettings("01HDEPLOY123");
   */
  async getSettings(deploymentId: string): Promise<RiskSettings> {
    const response = await apiClient.get<RiskSettings>(`/deployments/${deploymentId}/risk-limits`);
    return response.data;
  },

  /**
   * Update risk settings for a deployment.
   *
   * Args:
   *   deploymentId: ULID of the deployment.
   *   updates: Partial RiskSettingsUpdate object (only specified fields updated).
   *
   * Returns:
   *   Promise<RiskSettings> — updated risk limits.
   *
   * Raises:
   *   AxiosError with 404 if deployment or limits not found.
   *   AxiosError with 422 if values are invalid.
   *   AxiosError with 5xx on server error.
   *
   * Example:
   *   const updated = await riskApi.updateSettings("01HDEPLOY123", {
   *     max_position_size: "15000",
   *   });
   */
  async updateSettings(deploymentId: string, updates: RiskSettingsUpdate): Promise<RiskSettings> {
    const response = await apiClient.put<RiskSettings>(
      `/deployments/${deploymentId}/risk-limits`,
      updates,
    );
    return response.data;
  },
};
