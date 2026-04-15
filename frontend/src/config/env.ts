/**
 * Validated environment configuration.
 *
 * Purpose:
 *   Centralise all environment variables into a typed, validated config
 *   object. Fails fast on invalid or missing required variables in
 *   production. Provides sensible defaults for development.
 *
 * Responsibilities:
 *   - Parse and validate VITE_* environment variables.
 *   - Expose typed config via getConfig().
 *   - Fail fast in production if required values are missing.
 *
 * Does NOT:
 *   - Contain secrets (all values come from build-time VITE_ env vars).
 *   - Make API calls or perform I/O.
 *
 * Example:
 *   import { getConfig } from "@/config/env";
 *   const config = getConfig();
 *   console.log(config.apiBaseUrl); // "https://api.fxlab.io"
 */

export interface AuthConfig {
  /** Fraction of token lifetime to use as refresh buffer (0–1). */
  refreshBufferPercent: number;
  /** Max consecutive login failures before lockout. */
  maxLoginAttempts: number;
  /** Seconds to lock out after max failed attempts. */
  lockoutDurationSeconds: number;
}

export interface AppConfig {
  /** Base URL for the backend API. */
  apiBaseUrl: string;
  /** True when running in development mode (Vite dev server). */
  isDevelopment: boolean;
  /** True when running a production build. */
  isProduction: boolean;
  /** Vite build mode string. */
  mode: string;
  /** Auth-related configuration. */
  auth: AuthConfig;
}

let _cachedConfig: AppConfig | null = null;

/**
 * Build and validate the application configuration from environment variables.
 *
 * Returns:
 *   AppConfig with all fields populated and validated.
 *
 * Raises:
 *   Error if a required variable is missing or invalid in production mode.
 *
 * Example:
 *   const config = getConfig();
 *   fetch(config.apiBaseUrl + "/health");
 */
export function getConfig(): AppConfig {
  if (_cachedConfig) return _cachedConfig;

  const mode = import.meta.env.MODE || "development";
  const isProduction = mode === "production";
  const isDevelopment = !isProduction;

  // API base URL — required in production, defaults in dev
  const rawApiBaseUrl = import.meta.env.VITE_API_BASE_URL;
  let apiBaseUrl: string;

  if (rawApiBaseUrl) {
    // Validate that it's a real URL
    try {
      new URL(rawApiBaseUrl);
      apiBaseUrl = rawApiBaseUrl;
    } catch {
      throw new Error(
        `VITE_API_BASE_URL is not a valid URL: "${rawApiBaseUrl}". ` +
          "Expected format: https://api.example.com",
      );
    }
  } else if (isProduction) {
    throw new Error(
      "VITE_API_BASE_URL is required in production mode. " +
        "Set it in your .env.production or build environment.",
    );
  } else {
    apiBaseUrl = "http://localhost:8000";
  }

  // Auth config — use environment overrides or sensible defaults
  const refreshBufferPercent = parseFloat(
    import.meta.env.VITE_AUTH_REFRESH_BUFFER_PERCENT || "0.15",
  );
  const maxLoginAttempts = parseInt(import.meta.env.VITE_AUTH_MAX_LOGIN_ATTEMPTS || "5", 10);
  const lockoutDurationSeconds = parseInt(
    import.meta.env.VITE_AUTH_LOCKOUT_DURATION_SECONDS || "30",
    10,
  );

  _cachedConfig = {
    apiBaseUrl,
    isDevelopment,
    isProduction,
    mode,
    auth: {
      refreshBufferPercent,
      maxLoginAttempts,
      lockoutDurationSeconds,
    },
  };

  return _cachedConfig;
}

/**
 * Reset cached config — for testing only.
 * Allows tests to re-evaluate getConfig() after changing env vars.
 */
export function _resetConfigCache(): void {
  _cachedConfig = null;
}
