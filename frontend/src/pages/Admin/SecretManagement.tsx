/**
 * SecretManagement page — view, rotate, and manage application secrets.
 *
 * Purpose:
 *   Display all secrets with rotation status and timestamps. Support
 *   manual secret rotation with new values. Highlight expiring secrets
 *   based on age (60+ days = yellow, 90+ days = red).
 *
 * Responsibilities:
 *   - Fetch and display secrets via adminApi.
 *   - Handle secret rotation with value input and confirmation.
 *   - Toggle between all secrets and expiring-only view.
 *   - Highlight secrets nearing expiration based on last_rotated timestamp.
 *   - Show loading and empty states.
 *   - Use useAuth to verify admin scope.
 *
 * Does NOT:
 *   - Perform business logic or calculations.
 *   - Store persistent state outside React.
 *
 * Dependencies:
 *   - adminApi from @/features/admin/api.
 *   - useAuth from @/auth/useAuth.
 *
 * Example:
 *   <SecretManagement />
 */

import { useState, useEffect, useCallback } from "react";
import { useAuth } from "@/auth/useAuth";
import { adminApi, type SecretMetadata } from "@/features/admin/api";

/**
 * SecretManagement page component.
 *
 * Renders a table of secrets with rotation status, expiration indicators,
 * and per-secret rotation controls.
 *
 * Returns:
 *   JSX element containing the secret management page.
 */
export default function SecretManagement() {
  useAuth(); // Ensure authenticated

  // Secret list state
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Filter state
  const [showExpiringOnly, setShowExpiringOnly] = useState(false);
  const [displaySecrets, setDisplaySecrets] = useState<SecretMetadata[]>([]);

  // Rotate secret state
  const [rotatingKey, setRotatingKey] = useState<string | null>(null);
  const [rotateValue, setRotateValue] = useState("");
  const [rotateLoading, setRotateLoading] = useState(false);
  const [rotateError, setRotateError] = useState<string | null>(null);

  /**
   * Fetch secrets from API.
   */
  const fetchSecrets = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const result = showExpiringOnly
        ? await adminApi.listExpiringSecrets(90)
        : await adminApi.listSecrets();
      setDisplaySecrets(result);
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err);
      setError(`Failed to fetch secrets: ${msg}`);
    } finally {
      setLoading(false);
    }
  }, [showExpiringOnly]);

  /**
   * Fetch secrets on mount or when toggle changes.
   */
  useEffect(() => {
    fetchSecrets();
  }, [fetchSecrets]);

  /**
   * Calculate days since last rotation.
   */
  const getDaysSinceRotation = (lastRotated: string | null): number | null => {
    if (!lastRotated) return null;
    const last = new Date(lastRotated);
    const now = new Date();
    const diffMs = now.getTime() - last.getTime();
    const days = Math.floor(diffMs / (1000 * 60 * 60 * 24));
    return days;
  };

  /**
   * Get expiration indicator color and text.
   */
  const getExpirationIndicator = (lastRotated: string | null): { color: string; text: string } => {
    const days = getDaysSinceRotation(lastRotated);
    if (days === null) {
      return { color: "bg-red-100 text-red-800", text: "Never rotated" };
    }
    if (days >= 90) {
      return { color: "bg-red-100 text-red-800", text: `${days} days` };
    }
    if (days >= 60) {
      return { color: "bg-yellow-100 text-yellow-800", text: `${days} days` };
    }
    return { color: "bg-green-100 text-green-800", text: `${days} days` };
  };

  /**
   * Handle secret rotation.
   */
  const handleRotateSecret = async (key: string) => {
    if (!rotateValue.trim()) {
      setRotateError("Please enter a value");
      return;
    }
    setRotateLoading(true);
    setRotateError(null);
    try {
      await adminApi.rotateSecret(key, rotateValue);
      setRotatingKey(null);
      setRotateValue("");
      // Refresh secret list
      await fetchSecrets();
    } catch (err) {
      const msg = err instanceof Error ? err.message : String(err);
      setRotateError(`Failed to rotate secret: ${msg}`);
    } finally {
      setRotateLoading(false);
    }
  };

  return (
    <div className="space-y-6" data-testid="secret-management">
      <div>
        <h1 className="text-2xl font-bold text-surface-900">Secret Management</h1>
        <p className="mt-1 text-sm text-surface-500">View and rotate application secrets</p>
      </div>

      {/* Toggle and Controls */}
      <div className="flex items-center gap-4 rounded-lg border border-surface-200 bg-white p-4">
        <label className="flex items-center gap-2">
          <input
            type="checkbox"
            checked={showExpiringOnly}
            onChange={(e) => setShowExpiringOnly(e.target.checked)}
            data-testid="show-expiring-toggle"
            className="rounded border border-surface-300"
          />
          <span className="text-sm font-medium text-surface-700">
            Show expiring only (90+ days)
          </span>
        </label>
      </div>

      {/* Error message */}
      {error && <div className="rounded bg-red-50 p-3 text-sm text-red-700">{error}</div>}

      {/* Loading state */}
      {loading ? (
        <div
          data-testid="loading-state"
          className="rounded border border-surface-200 bg-surface-50 p-8 text-center text-surface-600"
        >
          Loading secrets...
        </div>
      ) : displaySecrets.length === 0 ? (
        <div
          data-testid="empty-state"
          className="rounded border border-surface-200 bg-surface-50 p-8 text-center text-surface-600"
        >
          {showExpiringOnly ? "No expiring secrets found" : "No secrets found"}
        </div>
      ) : (
        /* Secrets table */
        <div className="overflow-x-auto">
          <table
            data-testid="secret-table"
            className="w-full border-collapse border border-surface-200 bg-white"
          >
            <thead className="bg-surface-100">
              <tr>
                <th className="border border-surface-200 px-4 py-2 text-left text-xs font-semibold uppercase text-surface-700">
                  Key
                </th>
                <th className="border border-surface-200 px-4 py-2 text-left text-xs font-semibold uppercase text-surface-700">
                  Source
                </th>
                <th className="border border-surface-200 px-4 py-2 text-center text-xs font-semibold uppercase text-surface-700">
                  Is Set
                </th>
                <th className="border border-surface-200 px-4 py-2 text-left text-xs font-semibold uppercase text-surface-700">
                  Last Rotated
                </th>
                <th className="border border-surface-200 px-4 py-2 text-left text-xs font-semibold uppercase text-surface-700">
                  Description
                </th>
                <th className="border border-surface-200 px-4 py-2 text-center text-xs font-semibold uppercase text-surface-700">
                  Actions
                </th>
              </tr>
            </thead>
            <tbody>
              {displaySecrets.map((secret) => {
                const indicator = getExpirationIndicator(secret.last_rotated);
                return (
                  <tr
                    key={secret.key}
                    data-testid={`secret-row-${secret.key}`}
                    className="border-b border-surface-200 hover:bg-surface-50"
                  >
                    <td className="border border-surface-200 px-4 py-2 font-mono text-sm font-semibold text-surface-900">
                      {secret.key}
                    </td>
                    <td className="border border-surface-200 px-4 py-2 text-sm text-surface-700">
                      {secret.source}
                    </td>
                    <td className="border border-surface-200 px-4 py-2 text-center text-sm">
                      <span
                        className={`inline-block rounded px-2 py-1 text-xs font-semibold ${
                          secret.is_set ? "bg-green-100 text-green-800" : "bg-red-100 text-red-800"
                        }`}
                      >
                        {secret.is_set ? "Yes" : "No"}
                      </span>
                    </td>
                    <td className="border border-surface-200 px-4 py-2 text-center">
                      <span
                        data-testid={`expiring-indicator-${secret.key}`}
                        className={`inline-block rounded px-2 py-1 text-xs font-semibold ${indicator.color}`}
                      >
                        {indicator.text}
                      </span>
                    </td>
                    <td className="border border-surface-200 px-4 py-2 text-sm text-surface-700">
                      {secret.description}
                    </td>
                    <td className="border border-surface-200 px-4 py-2 text-center">
                      {rotatingKey === secret.key ? (
                        <div className="flex gap-1">
                          <input
                            type="password"
                            placeholder="New value"
                            value={rotateValue}
                            onChange={(e) => setRotateValue(e.target.value)}
                            data-testid={`rotate-input-${secret.key}`}
                            className="w-32 rounded border border-surface-300 px-2 py-1 text-xs"
                          />
                          <button
                            onClick={() => handleRotateSecret(secret.key)}
                            disabled={rotateLoading}
                            data-testid={`rotate-confirm-${secret.key}`}
                            className="rounded bg-green-600 px-2 py-1 text-xs text-white hover:bg-green-700 disabled:opacity-50"
                          >
                            Confirm
                          </button>
                          <button
                            onClick={() => {
                              setRotatingKey(null);
                              setRotateValue("");
                              setRotateError(null);
                            }}
                            className="rounded bg-gray-300 px-2 py-1 text-xs text-gray-700 hover:bg-gray-400"
                          >
                            Cancel
                          </button>
                        </div>
                      ) : (
                        <button
                          onClick={() => setRotatingKey(secret.key)}
                          data-testid={`rotate-button-${secret.key}`}
                          className="rounded bg-blue-600 px-3 py-1 text-xs text-white hover:bg-blue-700"
                        >
                          Rotate
                        </button>
                      )}
                      {rotateError && (
                        <div className="mt-2 rounded bg-red-50 p-1 text-xs text-red-700">
                          {rotateError}
                        </div>
                      )}
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
