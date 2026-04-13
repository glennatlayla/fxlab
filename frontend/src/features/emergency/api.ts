/**
 * Emergency controls API module.
 *
 * Purpose:
 *   Encapsulate all HTTP calls to kill switch endpoints.
 *   Provide a clean, type-safe interface for API operations.
 *
 * Responsibilities:
 *   - Call /kill-switch/* endpoints via apiClient.
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
 *   - types: KillSwitchStatus, HaltEventResponse.
 *
 * Error conditions:
 *   - Network errors: thrown by apiClient (caller handles retry).
 *   - 409 Conflict: kill switch already active.
 *   - 404 Not Found: kill switch or target does not exist.
 *   - 422 Invalid: malformed request body or scope.
 *
 * Example:
 *   const status = await emergencyApi.getStatus();
 *   const event = await emergencyApi.activateGlobal("Market halted");
 */

import { apiClient } from "@/api/client";
import type { KillSwitchStatus, HaltEventResponse } from "./types";

/**
 * Emergency controls API client.
 *
 * All endpoints return AxiosResponse<T> which is awaited by callers.
 * Error responses are thrown by apiClient interceptors or caller handling.
 */
export const emergencyApi = {
  /**
   * Fetch all active kill switches.
   *
   * Returns:
   *   Promise<KillSwitchStatus[]> — list of active kill switches.
   *
   * Example:
   *   const switches = await emergencyApi.getStatus();
   */
  async getStatus(): Promise<KillSwitchStatus[]> {
    const response = await apiClient.get<KillSwitchStatus[]>("/kill-switch/status");
    return response.data;
  },

  /**
   * Activate the global kill switch.
   *
   * Args:
   *   reason: Human-readable activation reason (min 1 char).
   *
   * Returns:
   *   Promise<HaltEventResponse> — details of the halt event.
   *
   * Raises:
   *   AxiosError with 409 if already active.
   *   AxiosError with 422 if reason is invalid.
   *
   * Example:
   *   const event = await emergencyApi.activateGlobal("Emergency risk control");
   */
  async activateGlobal(reason: string): Promise<HaltEventResponse> {
    const response = await apiClient.post<HaltEventResponse>("/kill-switch/global", {
      reason,
      activated_by: "web_operator",
      trigger: "kill_switch",
    });
    return response.data;
  },

  /**
   * Activate a strategy-scoped kill switch.
   *
   * Args:
   *   strategyId: ULID of the strategy to halt.
   *   reason: Human-readable activation reason (min 1 char).
   *
   * Returns:
   *   Promise<HaltEventResponse> — details of the halt event.
   *
   * Raises:
   *   AxiosError with 404 if strategy does not exist.
   *   AxiosError with 409 if already active.
   *   AxiosError with 422 if input is invalid.
   *
   * Example:
   *   const event = await emergencyApi.activateStrategy("01HS123", "Loss limit");
   */
  async activateStrategy(strategyId: string, reason: string): Promise<HaltEventResponse> {
    const response = await apiClient.post<HaltEventResponse>(
      `/kill-switch/strategy/${strategyId}`,
      {
        reason,
        activated_by: "web_operator",
        trigger: "kill_switch",
      },
    );
    return response.data;
  },

  /**
   * Activate a symbol-scoped kill switch.
   *
   * Args:
   *   symbol: Trading symbol (e.g., "AAPL").
   *   reason: Human-readable activation reason (min 1 char).
   *
   * Returns:
   *   Promise<HaltEventResponse> — details of the halt event.
   *
   * Raises:
   *   AxiosError with 409 if already active.
   *   AxiosError with 422 if input is invalid.
   *
   * Example:
   *   const event = await emergencyApi.activateSymbol("AAPL", "Circuit breaker");
   */
  async activateSymbol(symbol: string, reason: string): Promise<HaltEventResponse> {
    const response = await apiClient.post<HaltEventResponse>(`/kill-switch/symbol/${symbol}`, {
      reason,
      activated_by: "web_operator",
      trigger: "kill_switch",
    });
    return response.data;
  },

  /**
   * Deactivate a kill switch.
   *
   * Args:
   *   scope: Kill switch scope ("global", "strategy", or "symbol").
   *   targetId: Target identifier (strategy_id, symbol, or "global").
   *
   * Returns:
   *   Promise<HaltEventResponse> — details of the deactivation event.
   *
   * Raises:
   *   AxiosError with 404 if not found.
   *   AxiosError with 422 if scope is invalid.
   *
   * Example:
   *   const event = await emergencyApi.deactivate("strategy", "01HS123");
   */
  async deactivate(scope: string, targetId: string): Promise<HaltEventResponse> {
    const response = await apiClient.delete<HaltEventResponse>(`/kill-switch/${scope}/${targetId}`);
    return response.data;
  },
};
