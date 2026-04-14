/**
 * Axios HTTP client configured for the FXLab backend API.
 *
 * Purpose:
 *   Provide a pre-configured Axios instance that all API calls flow through.
 *   Handles base URL, auth header injection, correlation IDs, and error
 *   interception (401 → logout).
 *
 * Responsibilities:
 *   - Inject Authorization: Bearer <token> on every request when available.
 *   - Attach X-Correlation-ID for distributed tracing.
 *   - Intercept 401 responses to trigger logout.
 *
 * Does NOT:
 *   - Store tokens (AuthProvider owns token state).
 *   - Contain business logic.
 *
 * Dependencies:
 *   - axios
 */

import axios from "axios";

const API_BASE_URL = import.meta.env.VITE_API_BASE_URL || "http://localhost:8000";

export const apiClient = axios.create({
  baseURL: API_BASE_URL,
  headers: {
    "Content-Type": "application/json",
  },
  timeout: 30000,
});

// ---------------------------------------------------------------------------
// Token injection — set by AuthProvider after login
// ---------------------------------------------------------------------------

let _getAccessToken: (() => string | null) | null = null;

/**
 * Register a callback that returns the current access token.
 * Called once by AuthProvider during initialization.
 */
export function registerTokenProvider(fn: () => string | null): void {
  _getAccessToken = fn;
}

/**
 * Canonical correlation header name. Both "X-Correlation-Id" (mixed case) and
 * the legacy "X-Correlation-ID" variant are tolerated on inbound config so we
 * never overwrite a caller-supplied trace identifier.
 */
const CORRELATION_HEADER = "X-Correlation-Id";
const CORRELATION_HEADER_LEGACY = "X-Correlation-ID";

// Request interceptor: inject auth header + correlation ID + client source.
// Only inject headers when caller has not already supplied them — feature modules like
// governance set their own correlation IDs to thread distributed traces across layers
// per CLAUDE.md §8. Client source is used for audit tracking (BE-07).
apiClient.interceptors.request.use((config) => {
  const token = _getAccessToken?.();
  if (token) {
    config.headers.Authorization = `Bearer ${token}`;
  }

  const existing = config.headers[CORRELATION_HEADER] ?? config.headers[CORRELATION_HEADER_LEGACY];
  if (!existing) {
    config.headers[CORRELATION_HEADER] = crypto.randomUUID();
  }

  // Inject client source for audit tracking (web-desktop for now, will be web-mobile when mobile is detected)
  config.headers["X-Client-Source"] = "web-desktop";

  return config;
});

// Response interceptor: handle auth failures globally.
apiClient.interceptors.response.use(
  (response) => response,
  (error) => {
    if (error.response?.status === 401) {
      // Emit a custom event so AuthProvider can react without circular deps.
      window.dispatchEvent(new CustomEvent("fxlab:auth:unauthorized"));
    }
    return Promise.reject(error);
  },
);

export default apiClient;
