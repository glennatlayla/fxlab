/**
 * Admin feature API layer — data fetching for user management and secret rotation.
 *
 * Purpose:
 *   Fetch and manage users (Keycloak) and secrets from the backend.
 *   Implements admin operations with proper error handling and type safety.
 *
 * Responsibilities:
 *   - List secrets metadata (GET /admin/secrets).
 *   - List expiring secrets (GET /admin/secrets/expiring).
 *   - Rotate a secret (POST /admin/secrets/{key}/rotate).
 *   - List Keycloak users (GET /admin/users).
 *   - Create a new user (POST /admin/users).
 *   - Update user roles (PUT /admin/users/{user_id}/roles).
 *   - Reset password for a user (POST /admin/users/{user_id}/reset-password).
 *
 * Does NOT:
 *   - Contain business logic, UI rendering, or React state management.
 *   - Bypass the shared apiClient (which provides auth token injection,
 *     base URL, and 401 redirect handling).
 *
 * Dependencies:
 *   - apiClient from @/api/client (shared axios instance with interceptors).
 *
 * Example:
 *   const secrets = await adminApi.listSecrets();
 *   const users = await adminApi.listUsers();
 *   await adminApi.rotateSecret("DATABASE_PASSWORD", "new-secret-value");
 */

import { apiClient } from "@/api/client";

/**
 * Metadata for a single secret.
 */
export interface SecretMetadata {
  key: string;
  source: string;
  is_set: boolean;
  last_rotated: string | null;
  description: string;
}

/**
 * Keycloak user representation.
 */
export interface KeycloakUser {
  id: string;
  username: string;
  email: string;
  firstName: string;
  lastName: string;
  enabled: boolean;
  emailVerified: boolean;
}

/**
 * Request payload for creating a new user.
 */
export interface CreateUserRequest {
  username: string;
  email: string;
  first_name: string;
  last_name: string;
  temporary_password?: string;
}

/**
 * Admin API client.
 *
 * All methods throw standard HTTP errors that are caught by the global
 * axios interceptor (401 → logout, other errors propagate).
 *
 * All endpoints require admin:manage scope.
 */
export const adminApi = {
  /**
   * List all secrets metadata.
   *
   * Returns:
   *   Array of SecretMetadata objects with rotation timestamps.
   *
   * Raises:
   *   AxiosError: On network failure or server error.
   *
   * Example:
   *   const secrets = await adminApi.listSecrets();
   */
  async listSecrets(): Promise<SecretMetadata[]> {
    const { data } = await apiClient.get<SecretMetadata[]>("/admin/secrets");
    return data;
  },

  /**
   * List secrets that are expiring (not rotated within threshold).
   *
   * Args:
   *   thresholdDays: Days since last rotation to consider expiring. Defaults to 90.
   *
   * Returns:
   *   Array of SecretMetadata objects older than threshold.
   *
   * Raises:
   *   AxiosError: On network failure or server error.
   *
   * Example:
   *   const expiring = await adminApi.listExpiringSecrets(60);
   */
  async listExpiringSecrets(thresholdDays: number = 90): Promise<SecretMetadata[]> {
    const { data } = await apiClient.get<SecretMetadata[]>(
      `/admin/secrets/expiring?threshold_days=${thresholdDays}`,
    );
    return data;
  },

  /**
   * Rotate a secret by key with a new value.
   *
   * Args:
   *   key: Secret key to rotate.
   *   newValue: New value for the secret.
   *
   * Returns:
   *   Response with key and status confirmation.
   *
   * Raises:
   *   AxiosError: On network failure or server error.
   *
   * Example:
   *   const result = await adminApi.rotateSecret("DB_PASSWORD", "new-secret");
   *   // result.key == "DB_PASSWORD", result.status == "rotated"
   */
  async rotateSecret(key: string, newValue: string): Promise<{ key: string; status: string }> {
    const { data } = await apiClient.post<{ key: string; status: string }>(
      `/admin/secrets/${encodeURIComponent(key)}/rotate`,
      { new_value: newValue },
    );
    return data;
  },

  /**
   * List all Keycloak users with pagination.
   *
   * Args:
   *   first: Index of first user to fetch. Defaults to 0.
   *   maxResults: Maximum number of results. Defaults to 100.
   *
   * Returns:
   *   Array of KeycloakUser objects.
   *
   * Raises:
   *   AxiosError: On network failure or server error.
   *
   * Example:
   *   const users = await adminApi.listUsers(0, 50);
   */
  async listUsers(first: number = 0, maxResults: number = 100): Promise<KeycloakUser[]> {
    const { data } = await apiClient.get<KeycloakUser[]>(
      `/admin/users?first=${first}&max_results=${maxResults}`,
    );
    return data;
  },

  /**
   * Create a new user in Keycloak.
   *
   * Args:
   *   req: User creation request with username, email, names, optional password.
   *
   * Returns:
   *   Response with user_id and status confirmation.
   *
   * Raises:
   *   AxiosError: On network failure or server error.
   *
   * Example:
   *   const result = await adminApi.createUser({
   *     username: "alice",
   *     email: "alice@example.com",
   *     first_name: "Alice",
   *     last_name: "Smith"
   *   });
   *   // result.user_id == "...", result.status == "created"
   */
  async createUser(req: CreateUserRequest): Promise<{ user_id: string; status: string }> {
    const { data } = await apiClient.post<{ user_id: string; status: string }>("/admin/users", req);
    return data;
  },

  /**
   * Update roles for a user.
   *
   * Args:
   *   userId: Keycloak user ID.
   *   roles: Array of role names to assign.
   *
   * Returns:
   *   Promise that resolves when complete.
   *
   * Raises:
   *   AxiosError: On network failure or server error.
   *
   * Example:
   *   await adminApi.updateUserRoles("user-123", ["admin", "trader"]);
   */
  async updateUserRoles(userId: string, roles: string[]): Promise<void> {
    await apiClient.put(`/admin/users/${encodeURIComponent(userId)}/roles`, { roles });
  },

  /**
   * Reset password for a user.
   *
   * Args:
   *   userId: Keycloak user ID.
   *
   * Returns:
   *   Promise that resolves when complete.
   *
   * Raises:
   *   AxiosError: On network failure or server error.
   *
   * Example:
   *   await adminApi.resetPassword("user-123");
   */
  async resetPassword(userId: string): Promise<void> {
    await apiClient.post(`/admin/users/${encodeURIComponent(userId)}/reset-password`, {});
  },
};
