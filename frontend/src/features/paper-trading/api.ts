/**
 * Paper trading API module.
 *
 * Purpose:
 *   Encapsulate all HTTP calls to paper trading endpoints.
 *   Provide a clean, type-safe interface for API operations.
 *
 * Responsibilities:
 *   - Call /paper/{deployment_id}/register endpoint via apiClient.
 *   - Call endpoints to fetch available deployments and strategies.
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
 *   - types: PaperTradingRegisterRequest, PaperTradingRegisterResponse, etc.
 *
 * Error conditions:
 *   - Network errors: thrown by apiClient (caller handles retry).
 *   - 404 Not Found: deployment does not exist.
 *   - 422 Invalid: malformed request body or duplicate registration.
 *
 * Example:
 *   const response = await paperTradingApi.register("01HDEPLOY...", {
 *     initial_equity: "10000",
 *     market_prices: { "AAPL": "150.00" },
 *   });
 */

import { apiClient } from "@/api/client";
import type {
  PaperTradingRegisterRequest,
  PaperTradingRegisterResponse,
  DeploymentMetadata,
  StrategyBuildMetadata,
  PaperDeploymentSummary,
  PaperPosition,
  PaperOrder,
} from "./types";

/**
 * Paper trading API client.
 *
 * All endpoints return typed responses. Error responses are thrown by
 * apiClient interceptors or caught by caller.
 */
export const paperTradingApi = {
  /**
   * Register a deployment for paper trading.
   *
   * Args:
   *   deploymentId: ULID of the deployment.
   *   request: PaperTradingRegisterRequest with initial_equity, optional market_prices.
   *
   * Returns:
   *   Promise<PaperTradingRegisterResponse> — confirmation of registration.
   *
   * Raises:
   *   AxiosError with 404 if deployment not found.
   *   AxiosError with 422 if already registered or invalid values.
   *   AxiosError with 5xx on server error.
   *
   * Example:
   *   const response = await paperTradingApi.register("01HDEPLOY...", {
   *     initial_equity: "10000",
   *   });
   */
  async register(
    deploymentId: string,
    request: PaperTradingRegisterRequest,
  ): Promise<PaperTradingRegisterResponse> {
    const response = await apiClient.post<PaperTradingRegisterResponse>(
      `/paper/${deploymentId}/register`,
      request,
    );
    return response.data;
  },

  /**
   * Fetch list of available deployments for paper trading selection.
   *
   * Args:
   *   None.
   *
   * Returns:
   *   Promise<DeploymentMetadata[]> — list of deployments.
   *
   * Raises:
   *   AxiosError on network error or 5xx server error.
   *
   * Example:
   *   const deployments = await paperTradingApi.getDeployments();
   */
  async getDeployments(): Promise<DeploymentMetadata[]> {
    const response = await apiClient.get<DeploymentMetadata[]>(
      "/deployments?status=active",
    );
    return response.data;
  },

  /**
   * Fetch list of strategy builds for a deployment.
   *
   * Args:
   *   deploymentId: ULID of the deployment.
   *
   * Returns:
   *   Promise<StrategyBuildMetadata[]> — list of strategy builds.
   *
   * Raises:
   *   AxiosError with 404 if deployment not found.
   *   AxiosError on network error or 5xx server error.
   *
   * Example:
   *   const strategies = await paperTradingApi.getStrategies("01HDEPLOY...");
   */
  async getStrategies(deploymentId: string): Promise<StrategyBuildMetadata[]> {
    const response = await apiClient.get<StrategyBuildMetadata[]>(
      `/deployments/${deploymentId}/strategy-builds`,
    );
    return response.data;
  },

  /**
   * Fetch all paper trading deployments (monitoring list).
   *
   * Args:
   *   None.
   *
   * Returns:
   *   Promise<PaperDeploymentSummary[]> — list of active paper trading deployments.
   *
   * Raises:
   *   AxiosError on network error or 5xx server error.
   *
   * Example:
   *   const deployments = await paperTradingApi.listDeployments();
   */
  async listDeployments(): Promise<PaperDeploymentSummary[]> {
    const response = await apiClient.get<PaperDeploymentSummary[]>(
      "/paper/deployments",
    );
    return response.data;
  },

  /**
   * Fetch a single paper trading deployment with full details.
   *
   * Args:
   *   deploymentId: ULID of the deployment.
   *
   * Returns:
   *   Promise<PaperDeploymentSummary> — deployment details.
   *
   * Raises:
   *   AxiosError with 404 if deployment not found.
   *   AxiosError on network error or 5xx server error.
   *
   * Example:
   *   const deployment = await paperTradingApi.getDeploymentDetail("01HDEPLOY...");
   */
  async getDeploymentDetail(deploymentId: string): Promise<PaperDeploymentSummary> {
    const response = await apiClient.get<PaperDeploymentSummary>(
      `/paper/deployments/${deploymentId}`,
    );
    return response.data;
  },

  /**
   * Fetch positions for a paper trading deployment.
   *
   * Args:
   *   deploymentId: ULID of the deployment.
   *
   * Returns:
   *   Promise<PaperPosition[]> — list of open positions.
   *
   * Raises:
   *   AxiosError with 404 if deployment not found.
   *   AxiosError on network error or 5xx server error.
   *
   * Example:
   *   const positions = await paperTradingApi.getPositions("01HDEPLOY...");
   */
  async getPositions(deploymentId: string): Promise<PaperPosition[]> {
    const response = await apiClient.get<PaperPosition[]>(
      `/paper/deployments/${deploymentId}/positions`,
    );
    return response.data;
  },

  /**
   * Fetch orders for a paper trading deployment.
   *
   * Args:
   *   deploymentId: ULID of the deployment.
   *
   * Returns:
   *   Promise<PaperOrder[]> — list of orders (pending and completed).
   *
   * Raises:
   *   AxiosError with 404 if deployment not found.
   *   AxiosError on network error or 5xx server error.
   *
   * Example:
   *   const orders = await paperTradingApi.getOrders("01HDEPLOY...");
   */
  async getOrders(deploymentId: string): Promise<PaperOrder[]> {
    const response = await apiClient.get<PaperOrder[]>(
      `/paper/deployments/${deploymentId}/orders`,
    );
    return response.data;
  },

  /**
   * Freeze a paper trading deployment (pause execution).
   *
   * Args:
   *   deploymentId: ULID of the deployment.
   *
   * Returns:
   *   Promise<void>
   *
   * Raises:
   *   AxiosError with 404 if deployment not found.
   *   AxiosError with 409 if deployment is not in active state.
   *   AxiosError on network error or 5xx server error.
   *
   * Example:
   *   await paperTradingApi.freezeDeployment("01HDEPLOY...");
   */
  async freezeDeployment(deploymentId: string): Promise<void> {
    await apiClient.post(`/paper/deployments/${deploymentId}/freeze`);
  },

  /**
   * Unfreeze a paper trading deployment (resume execution).
   *
   * Args:
   *   deploymentId: ULID of the deployment.
   *
   * Returns:
   *   Promise<void>
   *
   * Raises:
   *   AxiosError with 404 if deployment not found.
   *   AxiosError with 409 if deployment is not in frozen state.
   *   AxiosError on network error or 5xx server error.
   *
   * Example:
   *   await paperTradingApi.unfreezeDeployment("01HDEPLOY...");
   */
  async unfreezeDeployment(deploymentId: string): Promise<void> {
    await apiClient.post(`/paper/deployments/${deploymentId}/unfreeze`);
  },
};
